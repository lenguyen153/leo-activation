# Campaign Run Flow

End-to-end trace of a manual campaign send: from the UI button click to message delivery and audit log.

---

## Overview

```
UI (CampaignEngine)
  │
  ├─ 1. POST /campaigns/rules          → create rule, get rule_id
  ├─ 2. POST /campaigns/rules/:id/preview → dry-run, show audience count
  └─ 3. POST /campaigns/rules/:id/send → queue background job
              │
              └─ FastAPI BackgroundTasks
                          │
                          └─ run_single_rule(rule_id)
                                      │
                              for each profile (batches of 500):
                                      │
                                      ├─ freq cap check (Redis)
                                      ├─ circuit breaker check (Redis)
                                      ├─ render message (Jinja2)
                                      ├─ dispatch_message() → POST /notification/send
                                      └─ log_delivery() → delivery_log table
                                      │
                              write run summary → campaign_engine_runs table
```

---

## Step 1 — Build & Create Rule

**UI:** `CampaignEngine.jsx` → user fills in name, segment, channels, frequency cap.

**API call:** `POST /campaigns/rules`
```json
{
  "rule_name": "Q2 Stock Alert",
  "conditions": {
    "operator": "AND",
    "conditions": [{ "field": "segments", "op": "contains", "value": "High-Value Investor" }]
  },
  "channel": "email",
  "frequency_cap": { "cooldown_days": 7, "max_per_day": 1 },
  "schedule_cron": "0 9 * * 2"
}
```

**Backend:** `api/campaign_rules.py::create_rule()`
- Resolves tenant UUID from `TARGET_TENANT` env var (default: `master`)
- Inserts row into `campaign_rules` table
- Returns `{ rule_id, created_at }`

**State after:** Rule exists in DB with `status = 'paused'`.

---

## Step 2 — Dry-Run Preview

**UI:** "Dry-Run / Preview Campaign" button → `previewCampaign({ name, seg, channels })`

**API call:** `POST /campaigns/rules/{rule_id}/preview`

**Backend:** `api/campaign_rules.py::preview_rule()`
1. Loads `conditions` + `audience_filter` from `campaign_rules`
2. Builds SQL `WHERE` clause via `ConditionEvaluator.to_sql()`
3. Adds segment filter: `p.segments @> '[{"name": "..."}]'::jsonb` if `audience_filter.segments` is set
4. Runs COUNT query → `matched_profiles`
5. Runs LIMIT 10 sample query → `sample_profiles`
6. **No messages sent**

**Response:**
```json
{
  "rule_id": "uuid",
  "matched_profiles": 1250,
  "sample_profiles": [{ "profile_id": "...", "primary_email": "...", "first_name": "..." }]
}
```

**UI:** Stores `rule_id` in state, shows reach / conversion / revenue projections.

---

## Step 3 — Send Now

**UI:** "Send Now" button → `triggerCampaign(ruleId)` → `POST /campaigns/rules/{rule_id}/send`

**API call:**
```json
{ "background": true }
```

**Backend:** `api/campaign_rules.py::send_rule_now()`
1. Opens dev DB connection via `_get_conn()`
2. Resolves tenant UUID via `_get_tenant_id(conn)`
3. Verifies rule exists (any status — manual sends bypass `active` filter)
4. Closes connection
5. Registers `run_single_rule(rule_id)` as a **FastAPI BackgroundTask**
6. Returns immediately: `{ "status": "queued", "rule_id": "uuid" }` (HTTP 202)

---

## Step 4 — Background Execution: `run_single_rule()`

**File:** `data_workers/campaign_engine/engine.py`

```
run_single_rule(rule_id)
  │
  ├─ Open PG connection (dev DB)
  ├─ Open Redis connection (REDIS_URL)
  ├─ Resolve tenant UUID via resolve_ids()
  ├─ SELECT rule by rule_id (no status filter)
  └─ _process_rule(conn, redis, rule, tenant_id, today_str)
        │
        ├─ Check circuit breaker → skip if channel is "open"
        ├─ _load_template(conn, template_id) → optional Jinja2 template
        ├─ _build_audience_query(rule) → SQL + params via ConditionEvaluator
        │
        └─ Paginate profiles (LIMIT 500 OFFSET n):
              │
              for each profile:
                │
                ├─ if iterate_field set (e.g. ext_data.abandoned_tickers):
                │     → _dispatch_iterate_for_profile() (one send per list item)
                └─ else:
                      → _dispatch_for_profile()
```

### Per-Profile Dispatch (`_dispatch_for_profile`)

```
check_frequency_cap(redis, rule_id, profile_id, freq_cap)
  ├─ Global daily cap: leo:notif:daily:{profile_id}:{date}   (max_per_day, default 3)
  ├─ Min cooldown:     leo:notif:last:{profile_id}           (MIN_COOLDOWN_HOURS, default 4h)
  └─ Campaign cap:     leo:campaign:{rule_id}:{profile_id}:last_sent  (cooldown_days TTL)
  → SKIP if any cap exceeded

is_channel_available(redis, channel)
  → SKIP if circuit breaker is OPEN for this channel

dispatch_message(channel, profile, message_config, conn, rule_id, template_row)
  ├─ Resolve base_account_id: SELECT base_account_id FROM portfolios WHERE profile_id = ?
  ├─ Render message: MessageRenderer.render() with Jinja2 template + profile fields
  ├─ Build adminnotify payload:
  │     {
  │       "base_account_id": "999C000001",
  │       "data": { "Data": {
  │         "type": "INVESTMENT_ADVICE | MARKET_INFO | ...",
  │         "content": { "title": "...", "body": "..." },
  │         "notification_id": "CDP-...",
  │         "created_at": "ISO"
  │       }}
  │     }
  └─ POST /notification/send (internal FastAPI endpoint)
        └─ forward to external adminnotify hub

→ Returns DeliveryStatus: SENT | FAILED | RETRY

log_delivery(conn, tenant_id, rule_id, profile_id, channel, status, response, today_str)
  └─ INSERT INTO delivery_log

if SENT:
  record_send(redis, rule_id, profile_id, freq_cap)   ← update Redis caps
  record_success(redis, channel)                       ← update circuit breaker
if RETRY:
  record_failure(redis, channel)                       ← may open circuit breaker
```

---

## Step 5 — Audit: `campaign_engine_runs`

After all profiles are processed:

```sql
INSERT INTO campaign_engine_runs
  (tenant_id, started_at, finished_at,
   rules_evaluated, profiles_matched, sent, skipped, errored, run_metadata)
VALUES (...)
```

`run_metadata` is a JSONB array with per-rule stats:
```json
[{
  "rule_id": "uuid",
  "rule_name": "Q2 Stock Alert",
  "matched": 1250,
  "sent": 890,
  "skipped": 340,
  "errored": 20
}]
```

**Check results:** `GET /campaigns/rules/{rule_id}/runs`

---

## Circuit Breaker States

```
CLOSED (normal)
  → 5 consecutive failures → OPEN (all sends skipped)
  → after 60s → HALF-OPEN (test one send)
    → success → CLOSED
    → failure → OPEN again

Redis key: leo:circuit:{channel}   TTL: 300s
```

---

## Condition Evaluator — Audience SQL

`conditions` JSONB is compiled to a PostgreSQL `WHERE` clause:

| Condition | SQL Output |
|---|---|
| `{ field: "segments", op: "contains", value: "VIP" }` | `p.segments @> '[{"name":"VIP"}]'::jsonb` |
| `{ field: "event_statistics.last_login_at", op: "newer_than_days", value: 30 }` | `(p.event_statistics->>'last_login_at')::timestamptz > NOW() - INTERVAL '30 days'` |
| `{ field: "product_recommendations.interest_score", op: "gte", value: 0.7 }` | triggers `JOIN product_recommendations pr ON ...` |
| `{ operator: "AND", conditions: [...] }` | `(clause1) AND (clause2)` |
| `{ operator: "OR", conditions: [...] }` | `(clause1) OR (clause2)` |

---

## Key Tables

| Table | Role |
|---|---|
| `campaign_rules` | Rule definitions (conditions, channel, message_config, freq_cap, cron) |
| `cdp_profiles` | Audience source (segments, email, ext_data, event_statistics) |
| `portfolios` | Maps `profile_id → base_account_id` (required for dispatch) |
| `product_recommendations` | Interest scores per ticker per profile |
| `delivery_log` | Per-send audit (profile, channel, status, provider response) |
| `campaign_engine_runs` | Per-run summary (totals + per-rule breakdown in JSONB) |

---

## Cron-Based Flow (Scheduled Sends)

The same `_process_rule()` is also called by the scheduled engine:

```
shell-scripts/run_campaign_engine.sh  (called by crontab hourly)
  └─ run_campaign_engine(tenant_name)
        ├─ _load_active_rules()   ← only status='active' rules
        ├─ _should_run_now(schedule_cron)  ← skip if cron doesn't match current hour
        └─ _process_rule(...)     ← same dispatch logic as manual send
```

**Difference from manual send:**
- Cron only runs `status = 'active'` rules; manual send runs any rule
- Cron checks `_should_run_now()`; manual send bypasses it
- Cron writes one `campaign_engine_runs` row for all rules; manual send writes one row per rule
