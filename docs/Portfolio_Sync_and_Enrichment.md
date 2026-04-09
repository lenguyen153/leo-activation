# Portfolio Sync & Enrichment Pipeline

Temporary pipeline to sync financial portfolio data from ArangoDB front-end events into PostgreSQL, and enrich real-time scored events with account identity.

**Status:** Temporary. Will be retired once the backend source-of-truth collection and CDC pipeline are restored.

---

## Architecture Overview

```
                        BATCH (Celery Beat, daily 08:30 VN)
                        ====================================

  ArangoDB                                              PostgreSQL
  cdp_trackingevent ──── AQL Query ────► Python ──── UPSERT ────► portfolios
  (asset-detail-view)   (latest per     Transform                 portfolio_holdings
  (login-success)        account)       (parse locale
                                         numbers, suffix,
                                         holdings string)

                        REAL-TIME (Kafka Pipeline)
                        ====================================

  Kafka                   Scoring         PG Lookup       Kafka / WS
  cdp.events.raw ──────► Consumer ──────► portfolios ──► leo.score.updates
  (CdpEventMessage)      (score +         (profile_id     (ScoreUpdateMessage
                          enrich)          → base_         with base_account_id)
                                           account_id)

                        API (FastAPI)
                        ====================================

  Client ── GET /portfolio/user?q=...&env=... ──► PostgreSQL
                                                   portfolios + cdp_profiles
```

---

## 1. Batch Sync: ArangoDB → PostgreSQL

### Source

ArangoDB collection `cdp_trackingevent`, two event types:

| Event | Key fields in `eventData` |
|---|---|
| `asset-detail-view` | `current_account_id`, `nav`, `cash_total`, `debt_total`, `collaterals`, `margin_limit`, `PNL`, `RTT`, `holdings`, `asset_allocation` |
| `login-success` | `account_id` (no financial data, used for account discovery only) |

**ID Resolution:** `refProfileId` preferred, fallback to `fingerprintId`. Maps to `profile_id` in PostgreSQL.

**Cutoff:** Only events from the last 30 days (configurable via `CUTOFF_DAYS`).

### AQL Strategy

Two separate AQL queries (different event shapes), merged in Python with `login-success` taking priority:

1. `AQL_LOGIN_SUCCESS` — Groups by `(account_id, profile_id)`, returns latest `createdAt`. Financial fields are null (login events don't carry them).
2. `AQL_ASSET_DETAIL_VIEWS` — Groups by `(account_id, profile_id)`, returns the full financial snapshot from the latest event.

Both use `SORT event.createdAt DESC` then `COLLECT ... INTO grp` so `grp[0]` is always the most recent event per group.

### Transform (Python)

**Suffix parsing:** The last character of `current_account_id` determines the account type.
```
"999C0000171" → base="999C000017", suffix="1", type="CASH"
```

| Suffix | Account Type |
|---|---|
| `1` | CASH |
| `2`, `6` | MARGIN |
| `8` | DERIVATIVES |
| other | UNKNOWN |

**Locale number parsing:** FE sends Vietnamese-formatted strings.
```
"96.690.000" → 96690000.0   (dots = thousands separators)
"-"          → 0             (dash = empty)
"-%"         → 0
```

**Holdings parsing:** FE sends a JSON-encoded string array.
```
'["AAS - 100%","BCM - 40%"]' → [{"symbol": "AAS", "pct": 100.0}, ...]
```

**Asset allocation parsing:** Same format, converted to a JSONB map.
```
'["cash - 92%","stock - 8%"]' → {"cash": 0.92, "stock": 0.08}
```

### Load (PostgreSQL)

**Orphan isolation:** Before upserting, all `profile_id`s are validated against `cdp_profiles`. Events for unknown profiles are dropped.

**FK safety:** `portfolio_holdings.account_id` references `portfolios.account_id`, so portfolios are upserted first. Holdings are only created for accounts that exist in the portfolios table.

**Optimistic timestamp locking:** Both tables use:
```sql
ON CONFLICT ... DO UPDATE SET ...
WHERE table.source_timestamp IS NULL
   OR EXCLUDED.source_timestamp > table.source_timestamp
```
This ensures older events never overwrite newer data.

### Target Tables

**`portfolios`** — One row per sub-account (CASH, MARGIN, DERIVATIVES).
- PK: `account_id`
- Unique: `(tenant_id, account_id)`
- Key columns: `base_account_id`, `account_type`, `account_suffix`, `profile_id`, `nav`, `cash_total`, `debt_total`, `collaterals`, `margin_limit`, `pnl`, `rtt_ratio`, `asset_allocation`

**`portfolio_holdings`** — One row per (account, symbol).
- PK: `(tenant_id, account_id, symbol)`
- Computed columns: `market_value`, `unrealized_pnl` (GENERATED ALWAYS AS STORED)
- Note: `quantity`, `avg_price`, `current_price` default to 0 since FE events only carry allocation percentages, not absolute quantities.

### Scheduling

| Method | Detail |
|---|---|
| Celery Beat | `sync-active-users-portfolios` task, daily at 01:30 UTC (08:30 VN) |
| CLI | `python -m data_workers.sync.sync_active_users_portfolios` |
| Shell script | `shell-scripts/sync_and_score_hourly.sh` |

Task config: `autoretry_for=(Exception,)`, `retry_backoff=60`, `max_retries=2`.

### Files

| File | Purpose |
|---|---|
| `data_workers/sync/sync_active_users_portfolios.py` | AQL queries, transforms, upserts, orchestrator |
| `data_workers/tasks.py` | `sync_active_users_portfolios_task` Celery wrapper |
| `data_workers/celery_app.py` | Beat schedule entry |

---

## 2. Real-Time Enrichment: Scoring Consumer

When the CDC pipeline scores a user event, it enriches the outbound message with `base_account_id` by querying the `portfolios` table.

### Flow

1. Scoring consumer reads `CdpEventMessage` from Kafka `cdp.events.raw`
2. Resolves `fingerprint_id → profile_id` via Redis
3. Computes incremental interest score, upserts to `product_recommendations`
4. **Queries `portfolios` table:** `SELECT base_account_id FROM portfolios WHERE profile_id = %s LIMIT 1`
5. Publishes `ScoreUpdateMessage` (with `base_account_id`) to `leo.score.updates`
6. Optionally forwards `ScoredEventForward` (with `base_account_id`) via HTTP POST

### Schema Changes

`base_account_id: Optional[str] = None` added to:
- `ScoreUpdateMessage` (Kafka output)
- `ScoredEventForward` (HTTP forward)

Field is nullable — profiles without a portfolio row get `null`.

### Why WebSocket Forwarding?

The scored events are streamed over a persistent WebSocket connection to an external team that consumes them for two purposes:

1. **ML Training Data** — The enriched events (interest scores, score deltas, ticker, account identity) feed into the external team's ML training pipelines. `base_account_id` allows them to join our behavioral scores with their own account-level features.
2. **Notification System** — The external team triggers their own notifications (push, in-app) based on score thresholds and ticker activity. Having `base_account_id` in the payload lets them route notifications to the correct trading account without a separate lookup.

The WS forwarder (`services/ws_forwarder/`) bridges Kafka → WebSocket with delivery guarantees (ACK-based commit or fire-and-forget mode, DLQ for failures).

### Example Payload (WS Forwarder Output)

```json
{
  "event_id": "0:351",
  "data": {
    "tenant_id": "66b39b8b-...",
    "profile_id": "2hL7j6tCyBFD87y9SjSkXu",
    "base_account_id": "999C000017",
    "ticker": "ACB",
    "metric_name": "order-preview",
    "interest_score": 0.96,
    "raw_score": 1202.09,
    "score_delta": 0.0005,
    "updated_at": "2026-04-09T02:52:40+00:00"
  }
}
```

### Files

| File | Change |
|---|---|
| `services/shared/schemas.py` | Added `base_account_id` to `ScoreUpdateMessage`, `ScoredEventForward` |
| `services/scoring_consumer/pg_writer.py` | Added `fetch_base_account_id()` |
| `services/scoring_consumer/consumer.py` | Calls `fetch_base_account_id()`, passes to outbound messages |

---

## 3. Portfolio Lookup API

### `GET /portfolio/user`

Lookup user by email, profile_id, or base_account_id. Returns all matching CDP profiles with their associated base_account_id.

| Param | Type | Description |
|---|---|---|
| `lookup` | string (required) | Email, profile_id, or base_account_id |
| `env` | string (optional) | `uat`, `prod`, or omit for all |

**Response:** `List[PortfolioUserResponse]`
```json
[
  {"profile_id": "3t2FLijc...", "primary_email": "user@example.com", "base_account_id": "999C000019"},
  {"profile_id": "5V3dA2lk...", "primary_email": "user@example.com", "base_account_id": "999C000019"}
]
```

**Sibling backfill:** CDP can have duplicate profiles with the same email. If one profile has a portfolio (and thus a `base_account_id`) but the other doesn't, the API propagates the value to all siblings sharing the same `primary_email`.

### `GET /portfolio/accounts`

Returns all sub-accounts (CASH, MARGIN, DERIVATIVES) for a given base_account_id.

| Param | Type | Description |
|---|---|---|
| `baseAccountId` | string (required) | Base account ID |

### Files

| File | Purpose |
|---|---|
| `api/portfolio.py` | Router, SQL, caching, backfill logic |

---

## Data Model Relationships

```
cdp_profiles (PG)            portfolios (PG)              portfolio_holdings (PG)
+------------------+         +-------------------+         +---------------------+
| profile_id  (PK) |----+    | account_id   (PK) |----+   | tenant_id           |
| primary_email    |    +---►| profile_id   (FK) |    +--►| account_id     (FK) |
| segments (JSONB) |         | base_account_id   |        | symbol         (PK) |
+------------------+         | account_type      |        | quantity            |
                             | account_suffix    |        | avg_price           |
                             | nav               |        | current_price       |
                             | cash_total        |        | market_value  (GEN) |
                             | ...               |        | unrealized_pnl(GEN) |
                             +-------------------+        +---------------------+

Relationships:
  - 1 profile  → N accounts  (via profile_id FK)
  - 1 account  → N holdings  (via account_id FK)
  - 1 base_account_id → N account_ids  (suffix determines type)
```
