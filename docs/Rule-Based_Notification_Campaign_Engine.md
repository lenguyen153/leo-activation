# Rule-Based Notification Campaign Engine — System Design & Logical Architecture

## Context

LEO Activation currently dispatches marketing messages (Zalo promo, email stock picks) via hardcoded Celery beat tasks with inline eligibility SQL. Adding a new campaign means writing a new task, new SQL, and a new beat schedule — tightly coupled and non-scalable. We need a generic **Rule-Based Campaign Engine** that decouples campaign definitions from the execution engine, runs on an hourly cycle, and leverages the existing channel infrastructure.

---

## 1. Data Flow & Pipeline

### 1.1 High-Level Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  Hourly      │────>│  Data        │────>│  Rule Engine     │────>│  Message          │
│  Celery Beat │     │  Ingestion   │     │  (Evaluate all   │     │  Dispatch         │
│  Trigger     │     │  (Batch SQL) │     │   active rules)  │     │  (Channel Router) │
└─────────────┘     └──────────────┘     └─────────────────┘     └──────────────────┘
                           │                      │                        │
                     ┌─────┴──────┐        ┌──────┴───────┐        ┌──────┴───────┐
                     │ cdp_profiles│        │ campaign_rules│        │ delivery_log │
                     │ product_rec │        │ freq_cap state│        │ Redis rate   │
                     │ (PG read)   │        │ (PG + Redis)  │        │ limit keys   │
                     └────────────┘        └──────────────┘        └──────────────┘
```

### 1.2 Efficient Ingestion Strategy

**Problem:** Loading all profiles every hour is wasteful.

**Solution: Rule-First, Then Fetch**
1. Load all **active campaign rules** first (small set, ~10-50 rules).
2. For each rule, build a **targeted SQL query** against `cdp_profiles` + `product_recommendations` that only fetches profiles matching that rule's conditions.
3. Use cursor-based pagination (`LIMIT 500 OFFSET ...` or keyset pagination on `profile_id`) to process in batches — never load all users into memory.
4. The 90-day rolling window is enforced at query time: `WHERE last_interaction_at >= NOW() - INTERVAL '90 days'` or equivalent filter on `event_statistics`.

**Why this works for thousands of users:**
- Each rule produces a focused query (e.g., "users with no login in 14 days" hits an index, returns ~hundreds not thousands).
- Batch size of 500 keeps memory bounded.
- Read replicas or connection pooling via existing `psycopg` async setup handle concurrency.

### 1.3 Pipeline Sequence (Single Hourly Run)

```
1. campaign_engine_task()              # Celery task, hourly beat
2.   ├── load_active_campaigns()       # SELECT * FROM campaign_rules WHERE status='active' AND schedule matches
3.   ├── for each campaign:
4.   │     ├── build_audience_query()   # Translate rule conditions → SQL WHERE clause
5.   │     ├── for each batch (500 profiles):
6.   │     │     ├── check_frequency_caps()   # Filter out already-contacted users
7.   │     │     ├── render_messages()         # Apply message template with profile data
8.   │     │     └── dispatch_batch()          # Route to correct channel, log delivery
9.   │     └── log_campaign_run()       # Record run metadata (matched, sent, skipped, errored)
10.  └── done
```

---

## 2. Rule Engine (Campaign Logic)

### 2.1 Campaign Rule Schema

New SQLAlchemy model: `CampaignRule` in a new file `data_models/dbo_campaign_rule.py`.

```
campaign_rules
├── rule_id          UUID PK
├── tenant_id        FK → tenant
├── campaign_id      FK → campaign (nullable, for grouping)
├── rule_name        VARCHAR        e.g. "Abandoned KYC Reminder"
├── rule_description TEXT
├── status           VARCHAR        'active' | 'paused' | 'archived'
├── priority         INT            lower = higher priority (for conflict resolution)
├── conditions       JSONB          ← the rule tree (see below)
├── channel          VARCHAR        'push' | 'email' | 'zalo' | 'sms'
├── template_id      FK → message_templates (nullable)
├── message_config   JSONB          fallback if no template: {subject, body, topic_type}
├── frequency_cap    JSONB          {max_per_day: 1, cooldown_days: 7}
├── schedule_cron    VARCHAR        '0 * * * *' (hourly), '0 9 * * *' (daily 9am)
├── audience_filter  JSONB          static audience filter: {segments: [...], min_score: 0.5}
├── created_at       TIMESTAMP
├── updated_at       TIMESTAMP
```

### 2.2 Condition Tree (JSONB Structure)

Conditions are expressed as a **composable tree** of operators — no hardcoded if/else. The engine walks the tree and either:
- (a) Translates it to SQL WHERE clauses for bulk evaluation, or
- (b) Evaluates it in Python per-profile for complex conditions.

**Structure:**

```json
{
  "operator": "AND",
  "conditions": [
    {
      "field": "event_statistics.last_login_at",
      "op": "older_than_days",
      "value": 14
    },
    {
      "field": "segments",
      "op": "contains",
      "value": "Active in last 3 months"
    },
    {
      "operator": "OR",
      "conditions": [
        {"field": "identities.kyc_status", "op": "eq", "value": "incomplete"},
        {"field": "interest_score_max", "op": "gte", "value": 0.3}
      ]
    }
  ]
}
```

**Supported operators:**
| Op | SQL Translation | Description |
|---|---|---|
| `eq` / `neq` | `= / !=` | Exact match |
| `gt` / `gte` / `lt` / `lte` | `> / >= / < / <=` | Numeric comparison |
| `contains` | `@>` (JSONB) or `LIKE` | Array/string containment |
| `not_contains` | `NOT @>` | Negated containment |
| `older_than_days` | `< NOW() - INTERVAL 'N days'` | Time-based decay |
| `newer_than_days` | `> NOW() - INTERVAL 'N days'` | Recent activity |
| `is_null` / `is_not_null` | `IS NULL / IS NOT NULL` | Existence check |
| `in` | `IN (...)` | Set membership |

**Logical combinators:** `AND`, `OR`, `NOT` — nestable to any depth.

### 2.3 Example Campaign Definitions

**Abandoned KYC:**
```json
{
  "rule_name": "Abandoned KYC Reminder",
  "conditions": {
    "operator": "AND",
    "conditions": [
      {"field": "identities.kyc_status", "op": "eq", "value": "incomplete"},
      {"field": "event_statistics.last_login_at", "op": "newer_than_days", "value": 30}
    ]
  },
  "channel": "push",
  "message_config": {
    "topic_type": "ASSISTANT_NOTIFICATION",
    "title": "Complete your KYC",
    "body": "You're almost there! Complete verification to start trading."
  },
  "frequency_cap": {"cooldown_days": 7, "max_per_day": 1}
}
```

**Sudden Inactivity:**
```json
{
  "conditions": {
    "operator": "AND",
    "conditions": [
      {"field": "segments", "op": "contains", "value": "Active in last 3 months"},
      {"field": "event_statistics.last_login_at", "op": "older_than_days", "value": 14}
    ]
  },
  "channel": "email",
  "template_id": "uuid-of-winback-template",
  "frequency_cap": {"cooldown_days": 14, "max_per_day": 1}
}
```

**Viewed Ticker but Didn't Buy:**
```json
{
  "conditions": {
    "operator": "AND",
    "conditions": [
      {"field": "product_recommendations.interest_score", "op": "gte", "value": 0.5},
      {"field": "product_recommendations.recommendation_context", "op": "not_contains", "value": "order-created"}
    ]
  },
  "channel": "push",
  "frequency_cap": {"cooldown_days": 3, "max_per_day": 2}
}
```

### 2.4 Condition Evaluator Module

New file: `data_workers/campaign_engine/condition_evaluator.py`

```python
class ConditionEvaluator:
    """Translates a condition tree → SQL WHERE clause + params."""

    def to_sql(self, condition_tree: dict) -> Tuple[str, dict]:
        """Returns (where_clause, bind_params) for bulk query."""

    def evaluate(self, condition_tree: dict, profile: dict) -> bool:
        """In-memory evaluation for a single profile (fallback)."""
```

**SQL-first approach:** Most conditions map directly to SQL (efficient for bulk). The evaluator builds a parameterized WHERE clause from the tree. Only conditions that require cross-table joins or Python logic fall back to in-memory evaluation.

---

## 3. Frequency Capping & Anti-Spam

### 3.1 Two-Layer State Management

**Layer 1: Redis (fast, ephemeral checks)**
```
Key: leo:campaign:{rule_id}:{profile_id}:last_sent
Value: ISO timestamp
TTL: max(cooldown_days) * 86400

Key: leo:notif:daily:{profile_id}:{YYYY-MM-DD}
Value: integer counter (INCR)
TTL: 86400 (auto-expire at end of day)
```

**Layer 2: PostgreSQL (durable, queryable audit)**
- `delivery_log` table already exists with `(profile_id, marketing_event_id, sent_at)`.
- Query: `SELECT COUNT(*) FROM delivery_log WHERE profile_id = ? AND sent_at > NOW() - INTERVAL '7 days' AND marketing_event_id = ?`
- Used as ground truth; Redis is the fast path.

### 3.2 Frequency Cap Check Flow

```python
def check_frequency_cap(rule: CampaignRule, profile_id: str) -> bool:
    cap = rule.frequency_cap  # e.g. {"cooldown_days": 7, "max_per_day": 2}

    # Check 1: Campaign-specific cooldown (Redis)
    last_sent = redis.get(f"leo:campaign:{rule.rule_id}:{profile_id}:last_sent")
    if last_sent and (now - parse(last_sent)).days < cap["cooldown_days"]:
        return False  # Too soon for this specific campaign

    # Check 2: Global daily cap (Redis)
    daily_count = redis.get(f"leo:notif:daily:{profile_id}:{today}")
    if daily_count and int(daily_count) >= cap.get("max_per_day", 3):
        return False  # User hit daily limit

    return True  # OK to send
```

```python
def record_send(rule: CampaignRule, profile_id: str):
    # Redis: set cooldown
    redis.setex(
        f"leo:campaign:{rule.rule_id}:{profile_id}:last_sent",
        cap["cooldown_days"] * 86400,
        now.isoformat()
    )
    # Redis: increment daily counter
    key = f"leo:notif:daily:{profile_id}:{today}"
    redis.incr(key)
    redis.expire(key, 86400)
    # PG: insert delivery_log (existing pattern)
```

### 3.3 Global Caps (Configurable)

| Cap | Default | Scope |
|---|---|---|
| `MAX_NOTIFICATIONS_PER_DAY` | 3 | Per user, all campaigns |
| `MAX_SAME_CAMPAIGN_PER_WEEK` | 1 | Per user, per campaign rule |
| `MIN_COOLDOWN_HOURS` | 4 | Min gap between any two notifications to same user |

These are stored in `main_configs.py` (env-overridable) and can be overridden per-rule via `frequency_cap` JSONB.

---

## 4. Error Handling & Resilience

### 4.1 Per-Profile Isolation

```python
for batch in paginate_audience(rule, batch_size=500):
    for profile in batch:
        try:
            if not check_frequency_cap(rule, profile.profile_id):
                stats["skipped_freq_cap"] += 1
                continue
            message = render_message(rule, profile)
            await dispatch(rule.channel, profile, message)
            record_send(rule, profile.profile_id)
            stats["sent"] += 1
        except Exception as e:
            logger.error("Campaign %s failed for profile %s: %s", rule.rule_id, profile.profile_id, e)
            stats["errored"] += 1
            continue  # Never let one profile crash the batch
```

**Key principle:** One corrupted profile never stops the engine. Errors are logged and counted, not raised.

### 4.2 Channel Dispatch Resilience

```python
async def dispatch(channel: str, profile, message) -> DeliveryStatus:
    """Route to channel with retry + circuit breaker."""
    try:
        if channel == "push":
            return await send_push_notification(profile, message)
        elif channel == "email":
            return await send_email(profile, message)
        elif channel == "zalo":
            return await send_zalo(profile, message)
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            # External service down — log and mark for retry
            log_delivery(profile, channel, status="pending_retry", error=str(e))
            return DeliveryStatus.RETRY
        else:
            # Client error (4xx) — don't retry, log as failed
            log_delivery(profile, channel, status="failed", error=str(e))
            return DeliveryStatus.FAILED
    except httpx.RequestError:
        # Network error — mark for retry
        log_delivery(profile, channel, status="pending_retry", error=str(e))
        return DeliveryStatus.RETRY
```

### 4.3 Circuit Breaker Pattern

Track consecutive failures per channel in Redis:

```
Key: leo:circuit:{channel}
Value: {failures: int, last_failure: timestamp, state: "closed"|"open"|"half_open"}
TTL: 300 (5 min auto-reset)
```

- **Closed** (normal): Send as usual. On failure, increment counter.
- **Open** (> 5 consecutive failures): Skip all sends for this channel, log as `"channel_unavailable"`. Auto-transition to half-open after 60 seconds.
- **Half-open**: Allow 1 test send. If it succeeds, reset to closed. If it fails, back to open.

### 4.4 Retry Queue

Failed deliveries with `status="pending_retry"` in `delivery_log` are picked up by a separate Celery task:

```python
@celery_app.task(name="retry_failed_deliveries")
def retry_failed_deliveries():
    """Runs every 15 minutes. Retries pending deliveries up to 3 times."""
```

### 4.5 Run-Level Logging

Each hourly run produces a summary record:

```
campaign_engine_runs
├── run_id          UUID PK
├── tenant_id       FK
├── started_at      TIMESTAMP
├── finished_at     TIMESTAMP
├── rules_evaluated INT
├── profiles_matched INT
├── sent            INT
├── skipped         INT          (frequency cap, consent, circuit breaker)
├── errored         INT
├── run_metadata    JSONB        (per-rule breakdown)
```

---

## 5. Future-Proofing: Marketing Manager UI

### 5.1 API Layer (Immediate)

Expose CRUD endpoints for `campaign_rules` — even before a UI exists, this enables Postman/internal tooling:

```
POST   /campaigns/rules          — Create new rule
GET    /campaigns/rules          — List all rules (filterable by status)
GET    /campaigns/rules/{id}     — Get rule detail
PUT    /campaigns/rules/{id}     — Update rule
PATCH  /campaigns/rules/{id}/status  — Activate / pause / archive
GET    /campaigns/rules/{id}/runs    — View execution history
POST   /campaigns/rules/{id}/preview — Dry-run: show matched profiles without sending
```

### 5.2 UI-Ready Design Decisions

1. **Condition tree as JSONB** — maps directly to a drag-and-drop rule builder UI (similar to Segment, Braze, or Customer.io rule builders). Each node is `{field, op, value}` or `{operator, conditions: [...]}`.

2. **Template references** — `message_templates` table already supports Jinja2 with versioning. A UI can offer a WYSIWYG editor that saves to this table.

3. **Preview/dry-run endpoint** — lets marketing managers test a rule against real data before activating. Returns matched profile count + sample profiles.

4. **Audit trail** — `campaign_engine_runs` + `delivery_log` provide full observability. A dashboard can show: "Campaign X sent 342 messages, 12 skipped (freq cap), 2 errors."

5. **Schedule picker** — `schedule_cron` field accepts standard cron expressions. A UI can provide presets ("Hourly", "Daily at 9am", "Weekdays only") that map to cron strings.

### 5.3 Progressive Enhancement Path

```
Phase 1 (Now):    JSONB rules + Celery engine + API endpoints
Phase 2 (Next):   Internal admin UI (React) for rule CRUD + preview
Phase 3 (Later):  Visual rule builder with drag-and-drop conditions
Phase 4 (Future): ML-assisted: "Suggest a campaign for users likely to churn"
                   (leverage existing interest_score + NBA system)
```

---

## 6. File Structure (New/Modified)

```
data_models/
  dbo_campaign_rule.py          # NEW: CampaignRule + CampaignEngineRun models

data_workers/
  campaign_engine/              # NEW: Package
    __init__.py
    engine.py                   # Orchestrator: load rules → evaluate → dispatch
    condition_evaluator.py      # Condition tree → SQL / in-memory evaluation
    frequency_cap.py            # Redis + PG frequency cap checks
    dispatcher.py               # Channel routing (reuses existing channels)
    circuit_breaker.py          # Redis-based circuit breaker

data_workers/
  celery_app.py                 # MODIFIED: Add hourly beat schedule
  tasks.py                      # MODIFIED: Add campaign_engine_task + retry_failed_deliveries

api/
  campaign_rules.py             # NEW: CRUD + preview endpoints

main_configs.py                 # MODIFIED: Add CampaignEngineConfigs section

sql-scripts/
  campaign_rules.sql            # NEW: DDL for campaign_rules + campaign_engine_runs
```

---

## 7. Reusable Existing Components

| Component | File | How It's Reused |
|---|---|---|
| `delivery_log` table | `data_models/dbo_execution.py` | Audit trail for all sends — already has profile_id, channel, status |
| `message_templates` table | `data_models/dbo_execution.py` | Jinja2 templates with versioning |
| `NotificationChannel` ABC | `agentic_tools/channels/activation.py` | Strategy pattern base class |
| `EmailChannel` | `agentic_tools/channels/email.py` | `MessageRenderer`, Brevo/SendGrid/SMTP dispatch |
| `ZaloOAChannel` | `agentic_tools/channels/zalo.py` | Promo + CS message dispatch |
| Push notification API | `api/notification.py` | `send_notification()` endpoint for mobile push |
| Redis rate-limit pattern | `agentic_tools/channels/email.py` | `leo:{channel}:{profile_id}:{date}` key pattern |
| `MarketingConfigs` | `main_configs.py` | Channel credentials and thresholds |
| `cron_from_expr()` | `data_workers/celery_app.py` | Convert cron strings to Celery crontab |
| `ConsentManagement` model | `data_models/dbo_cdp.py` | Check `is_allowed` per channel before send |

---

## 8. Verification & Testing

1. **Unit tests:** `ConditionEvaluator` — test each operator, nested AND/OR/NOT, edge cases (null fields, missing keys).
2. **Integration test:** Create a rule, insert test profiles in PG, run `campaign_engine_task()`, verify `delivery_log` entries.
3. **Frequency cap test:** Send once, run engine again, verify second send is blocked.
4. **Circuit breaker test:** Mock channel to fail 5 times, verify circuit opens and skips sends.
5. **Preview endpoint test:** `POST /campaigns/rules/{id}/preview` returns matched count without sending.
6. **Resilience test:** Insert a profile with corrupted data, verify engine continues processing remaining profiles.
