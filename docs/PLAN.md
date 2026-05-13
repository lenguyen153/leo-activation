# PLAN.md — Zalo OA Promotional Message Integration

## Objective

Bridge CDP behavioral tracking → Zalo OA API to send **"Tin Truyền Thông" (Promotional Messages)** when a user's interest score for a ticker crosses the 0.70 threshold.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│              INBOUND (Zalo → CDP → Our DB)                      │
│                                                                 │
│  User clicks "Follow" on Zalo OA                                │
│       │                                                         │
│       ├── Zalo requests phone number during follow              │
│       ├── Zalo OA fires HTTP POST → CDP ingestion endpoint      │
│       ├── CDP stitches Zalo profile to existing user            │
│       │   via primaryPhone match                                │
│       ├── CDP writes "zalo_user_id:abc123" as a plain string    │
│       │   into the profile's mediaChannels[] array              │
│       │                                                         │
│       └── Our Celery sync worker pulls updated profile          │
│           from ArangoDB → PostgreSQL (incremental sync)         │
│           mediaChannels JSONB now contains the Zalo ID          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              OUTBOUND (Us → Zalo)                               │
│                                                                 │
│  Celery Worker (zalo_promo_dispatch)                            │
│       │                                                         │
│       ├── 1. Query eligible users (3 conditions)                │
│       │     A. media_channels contains zalo_user_id entry       │
│       │     B. behavioral event count > 3 for ticker            │
│       │     C. interest_score > 0.70 for ticker                 │
│       ├── 2. Check rate limit (1 msg/user/day via Redis+PG)    │
│       ├── 3. POST /v3.0/oa/message/promotion                   │
│       └── 4. Log to delivery_log                                │
│                                                                 │
│  Token: Reuses ZaloOAChannel._refresh_access_token()            │
│         (no new token logic)                                    │
└─────────────────────────────────────────────────────────────────┘
```

**Key architectural decision:** No custom `/zalo-webhook` or mini-login webview. The upstream LeoCDP handles Zalo OA webhook ingestion and phone-based identity stitching. Our backend only consumes the result via the existing Arango → PostgreSQL sync pipeline.

---

## 2. Data Model — Zalo ID in `media_channels` JSONB

### 2A. How the Zalo ID is stored

The Zalo `user_id` lives inside the existing `media_channels` JSONB column on `cdp_profiles` as a **plain string** using the `key:value` convention (same pattern as `identities` stores `"email:nam@gmail.com"`, `"phone:+84901234567"`).

After the CDP stitches the follow event, the ArangoDB profile's `mediaChannels` array will contain:

```json
["facebook", "zalo", "zalo_user_id:abc123encrypted"]
```

All entries remain plain strings. No mixed types, no dict objects.

### 2B. No data model changes needed

The existing `List[str]` type on both models already supports this:

| File | Field | Type | Status |
|------|-------|------|--------|
| `data_models/arango_profile.py:73` | `mediaChannels` | `List[str]` | No change |
| `data_models/pg_profile.py:67` | `media_channels` | `List[str]` | No change |

The full sync pipeline is unaffected:
- `arango_profile.py` AQL query (line 248) — already fetches `mediaChannels: p.mediaChannels`
- `arango_to_pg_profile_sync_service.py:100` — already maps `p.mediaChannels` directly
- `pg_profile_repository.py` UPSERT SQL — already writes `%(media_channels)s::jsonb`
- `pg_profile.py` `to_pg_row()` — already wraps with `Json(self.media_channels)`

### 2C. No schema migration needed

The `media_channels` column is already `JSONB NOT NULL DEFAULT '[]'::jsonb` in `sql-scripts/schema.sql`. A JSONB string array natively holds `"zalo_user_id:abc123"`. No `ALTER TABLE` required.

### 2D. Add delivery_log index for rate limiting

```sql
CREATE INDEX IF NOT EXISTS idx_delivery_log_rate_limit
    ON delivery_log (tenant_id, profile_id, channel, sent_at DESC);
```

This supports the daily-cap check: `WHERE channel = 'zalo_promo' AND sent_at >= <today_start>`.

### 2E. Helper function to extract Zalo ID from media_channels

Used by the Celery worker and anywhere we need to resolve the Zalo user ID from a profile:

```python
def extract_zalo_user_id(media_channels: list) -> Optional[str]:
    """Extract the Zalo encrypted user_id from the media_channels JSONB string array."""
    PREFIX = "zalo_user_id:"
    for entry in media_channels:
        if isinstance(entry, str) and entry.startswith(PREFIX):
            return entry[len(PREFIX):]
    return None
```

This lives in `agentic_tools/channels/zalo.py` as a module-level utility.

---

## 3. Sync Pipeline — How Zalo ID Flows from CDP to Our DB

### 3A. The existing pipeline (no changes to flow)

```
CDP writes to ArangoDB → Celery sync worker → PostgreSQL
         (1)                   (2)                (3)

1. CDP stitches Zalo follow event, writes:
   profile.mediaChannels = [..., "zalo_user_id:abc123"]

2. ArangoProfileRepository fetches via CDP_PROFILE_QUERY:
   mediaChannels: p.mediaChannels   (line 248 of arango_profile.py)

3. ArangoToPostgresSyncService.to_pg_profile() maps:
   media_channels=p.mediaChannels   (line 100)

4. PGProfileRepository.upsert_profile() writes:
   %(media_channels)s::jsonb        (line 63 of UPSERT SQL)
```

### 3B. What changes

Nothing. The Zalo ID is a plain string (`"zalo_user_id:abc123"`), so the existing `List[str]` types, AQL query, mapping, and SQL all work without any code changes.

### 3C. Sync timing

The existing Celery Beat schedule syncs profiles every 5 minutes (`CELERY_SYNC_PROFILES_CRON = "*/5 * * * *"`). After a user follows the Zalo OA:
- CDP processes the webhook and updates ArangoDB (seconds)
- Our sync picks it up within ≤5 minutes
- The Zalo user ID is then available in PostgreSQL for the eligibility query

This latency is acceptable since the promotional dispatch runs as a daily batch job.

---

## 4. Configuration Additions

In `main_configs.py` → `MarketingConfigs`:

```python
# Zalo Promotional Messages
ZALO_PROMO_API_URL: str = os.getenv(
    "ZALO_PROMO_API_URL",
    "https://openapi.zalo.me/v3.0/oa/message/promotion"
)
ZALO_PROMO_INTEREST_THRESHOLD: float = float(
    os.getenv("ZALO_PROMO_INTEREST_THRESHOLD", "0.70")
)
ZALO_PROMO_EVENT_COUNT_THRESHOLD: int = int(
    os.getenv("ZALO_PROMO_EVENT_COUNT_THRESHOLD", "3")
)
```

No changes to `ZALO_APP_ID`, `ZALO_APP_SECRET`, or token configs — they are reused as-is.

---

## 5. Business Logic — Eligibility Evaluation

### 5A. Three strict conditions

| # | Condition | Source | Check |
|---|-----------|--------|-------|
| A | User follows the OA | `cdp_profiles.media_channels` contains a `"zalo_user_id:..."` string | `EXISTS` + `jsonb_array_elements_text` with `LIKE` |
| B | Behavioral event count > 3 for this ticker | `cdp_profiles.event_statistics` JSONB | Extract count for the ticker's metric key |
| C | Interest score > 0.70 for this ticker | `product_recommendations.interest_score` | SQL WHERE clause |

### 5B. Single eligibility query

```sql
SELECT DISTINCT ON (p.profile_id)
    p.profile_id,
    p.media_channels,
    r.product_id AS ticker,
    r.interest_score
FROM product_recommendations r
JOIN cdp_profiles p
    ON r.profile_id = p.profile_id
    AND r.tenant_id = p.tenant_id
WHERE r.tenant_id = %s
  AND r.interest_score > %s                                    -- Condition C (0.70)
  AND EXISTS (                                                 -- Condition A
        SELECT 1 FROM jsonb_array_elements_text(p.media_channels) AS ch
        WHERE ch LIKE 'zalo_user_id:%%'
      )
  AND (p.event_statistics ->> %s)::int > %s                    -- Condition B (> 3)
ORDER BY p.profile_id, r.interest_score DESC
```

**Key difference from v1:** Condition A uses `EXISTS` + `jsonb_array_elements_text` with a prefix match on `"zalo_user_id:"` strings instead of a dedicated column check. The `%%` is Python's escaped `%` for psycopg parameter substitution.

The `DISTINCT ON` + `ORDER BY interest_score DESC` ensures only the highest-scoring ticker per user is returned (since we can only send 1 msg/user/day).

The Zalo user ID is then extracted in Python via `extract_zalo_user_id(row['media_channels'])`.

The `event_statistics` JSONB key pattern is `id_default_journey-<metric_name>` (confirmed from `cdp_profiles` schema comments). The ticker-specific key will be constructed as `id_default_journey-view-<ticker>`.

### 5C. Where this runs

**Inside a new Celery task** (`data_workers/tasks.py`), NOT inside `activate_channel`.

Rationale:
- `activate_channel` is the agent-facing tool (synchronous, single-segment)
- Promotional message dispatch is a **scheduled batch job** that scans all eligible users
- Keeping it in Celery allows cron scheduling (e.g., daily at 9am) and retry semantics

---

## 6. Rate Limiting — 1 Message / User / Day

### 6A. Strategy: Redis + delivery_log (dual layer)

**Fast path (Redis):** Before sending, check key `leo:zalo_promo:{profile_id}:{date}`.
- If exists → skip (already sent today)
- If absent → proceed, then SET with TTL 86400s after successful send

**Durable path (delivery_log):** On successful Zalo API response, INSERT into `delivery_log` with `channel = 'zalo_promo'`. This is the audit trail and fallback if Redis is flushed.

**Pre-batch startup:** The Celery task can optionally load today's already-sent profile IDs from `delivery_log` into a set for O(1) lookup, but the Redis check is the primary gate.

### 6B. Why not Redis-only

Redis is ephemeral. A restart between send and next check would cause a duplicate. The `delivery_log` INSERT is the source of truth; Redis is the performance layer.

---

## 7. Message Execution — Expanding `ZaloOAChannel`

### 7A. New method: `send_promotion()`

Added to `agentic_tools/channels/zalo.py` → `ZaloOAChannel`:

```python
def send_promotion(self, zalo_user_id: str, template_data: dict) -> Tuple[bool, int, str]:
    """
    Sends a Tin Truyền Thông (Promotional Message) to a single user.
    Uses the existing token management (self.access_token, auto-refresh).
    """
```

**Target URL:** `https://openapi.zalo.me/v3.0/oa/message/promotion`

**Payload format:**
```json
{
  "recipient": {
    "user_id": "<encrypted_zalo_user_id>"
  },
  "message": {
    "attachment": {
      "type": "template",
      "payload": {
        "template_type": "list",
        "elements": [
          {
            "title": "Breaking: VNM đạt đỉnh 52 tuần",
            "subtitle": "Interest score: 0.85 — Xem phân tích chi tiết",
            "image_url": "<dynamic_from_template_data>",
            "default_action": {
              "type": "oa.open.url",
              "url": "<deep_link_to_analysis>"
            }
          }
        ],
        "buttons": [
          {
            "title": "Xem chi tiết",
            "type": "oa.open.url",
            "payload": {
              "url": "<dynamic_url>"
            }
          }
        ]
      }
    }
  }
}
```

### 7B. Token reuse

`send_promotion()` calls the same `_execute_zns_call()` pattern (headers with `access_token`). On error code `-124`, it calls the existing `_refresh_access_token()` and retries. **Zero new token logic.**

### 7C. No changes to `send()`

The existing `send()` method (ZNS/transactional) is untouched. `send_promotion()` is a parallel method for the promotional API.

---

## 8. Celery Worker — `zalo_promo_dispatch`

### 8A. New task in `data_workers/tasks.py`

```
Task: zalo_promo_dispatch
Schedule: Daily at 09:00 VN time (via Celery Beat)

Steps:
  1. Resolve tenant_uuid via resolve_ids()
  2. Run eligibility query (Section 5B) → List[{profile_id, media_channels, ticker, score}]
  3. For each eligible row:
     a. Extract zalo_user_id via extract_zalo_user_id(media_channels)
        - If None → skip (malformed entry)
     b. Rate-limit check: Redis GET leo:zalo_promo:{profile_id}:{YYYY-MM-DD}
        - If exists → skip
     c. Build template_data from ticker + score + news URL
     d. Call ZaloOAChannel().send_promotion(zalo_user_id, template_data)
     e. On success:
        - Redis SETEX leo:zalo_promo:{profile_id}:{YYYY-MM-DD} 86400 "1"
        - INSERT delivery_log (channel='zalo_promo', status='sent')
     f. On failure:
        - INSERT delivery_log (channel='zalo_promo', status='failed', provider_response=<error>)
        - Log error, continue to next user (do not abort batch)
  4. Log summary: total eligible, sent, skipped (rate-limited), failed
```

### 8B. Prioritization

If multiple tickers qualify for the same user (and only 1 msg/day allowed), pick the ticker with the **highest interest_score**. The eligibility query already uses `DISTINCT ON (p.profile_id) ... ORDER BY p.profile_id, r.interest_score DESC` to enforce this at the SQL level.

---

## 9. New FastAPI Routes Summary

**No new routes.** The CDP-driven architecture eliminates the need for:
- ~~`POST /zalo-webhook`~~ — CDP handles webhook ingestion
- ~~`POST /zalo/link-account`~~ — CDP handles phone-based identity stitching

Our backend is purely outbound (Celery batch dispatch).

---

## 10. File Change Map

| File | Action | What |
|------|--------|------|
| `main_configs.py` | EDIT | Add `ZALO_PROMO_*` configs to `MarketingConfigs` |
| `agentic_tools/channels/zalo.py` | EDIT | Add `extract_zalo_user_id()` + `send_promotion()` method |
| `data_workers/tasks.py` | EDIT | Add `zalo_promo_dispatch` Celery task |
| `sql-scripts/schema.sql` | EDIT | Add `idx_delivery_log_rate_limit` index |

**Not needed (zero model/schema changes):**
- `data_models/arango_profile.py` — `List[str]` already holds `"zalo_user_id:abc123"`
- `data_models/pg_profile.py` — same, no type change
- `data_models/dbo_cdp.py` — no new ORM column
- `api/zalo_webhook.py` — CDP handles inbound
- `api/handlers.py` — no new routes to register

---

## 11. Execution Order

```
Phase 1 — Database Index
  Step 1: sql-scripts/schema.sql — CREATE INDEX idx_delivery_log_rate_limit

Phase 2 — Configuration
  Step 2: main_configs.py — Add ZALO_PROMO_* to MarketingConfigs

Phase 3 — Outbound Messaging
  Step 3: zalo.py — Add extract_zalo_user_id() utility
  Step 4: zalo.py — Add send_promotion() method
  Step 5: data_workers/tasks.py — Add zalo_promo_dispatch Celery task
  Step 6: data_workers/tasks.py — Add Celery Beat schedule entry

Phase 4 — Verification
  Step 7:  Verify sync pipeline carries Zalo ID correctly
           (insert test "zalo_user_id:test123" in Arango mediaChannels
            → trigger sync → check PostgreSQL media_channels JSONB)
  Step 8:  Test eligibility query with known data
  Step 9:  Test send_promotion() with Zalo sandbox
  Step 10: Test rate limiting (send twice, second should skip)
```

---

## 12. Constraints & Risks

| Risk | Mitigation |
|------|------------|
| Zalo refresh token is single-use | Reuse existing `_refresh_access_token()` with DB persistence — already handles this |
| Promotional API rate limit (1/user/day) | Redis fast-check + delivery_log durable check |
| `media_channels` string convention must be consistent | CDP must write `"zalo_user_id:<id>"` exactly — document the prefix contract in CDP integration guide |
| `event_statistics` key format may vary per tenant | Make the metric key pattern configurable via env var |
| Redis flush loses rate-limit state | Fallback query on `delivery_log` at task startup rebuilds today's sent set |
| Sync latency (up to 5 min) | Acceptable — promo dispatch is a daily batch, not real-time |
| Zalo user ID string could be malformed | `extract_zalo_user_id()` defensively checks `isinstance(entry, str)` and prefix before splitting |
