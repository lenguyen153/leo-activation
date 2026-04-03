# Real-Time Event-Driven Recommendation Engine — Full Execution Plan

## Context

Current scoring is batch-only (not even scheduled in Celery beat). A user event in ArangoDB can take hours to surface as a score. This plan adds a real-time CDC pipeline: ArangoDB WAL → Kafka → Scoring Consumer → NBA Publisher, with Celery batch demoted to 6h reconciliation.

---

## Execution Order (33 files, 4 phases)

### Phase 1a — Shared Infrastructure + CDC Poller

**Step 1: Dependencies + Config**
- `requirements.txt` — add `confluent-kafka>=2.3.0`, `structlog>=24.0`, `prometheus_client>=0.20`
- `main_configs.py` — add after line 104:
  - `KAFKA_BOOTSTRAP_SERVERS` (default `kafka:9092`)
  - `CDC_POLL_INTERVAL_S` (default `2`)
  - `ACTIVATION_APP_WEBHOOK_URL` (default `None`)
  - `REALTIME_SCORING_ENABLED` (default `False`)

**Step 2: Shared module** (`services/shared/`)
- `__init__.py`
- `schemas.py` — 3 Pydantic models: `CdpEventMessage`, `ScoreUpdateMessage`, `NbaActionMessage`
- `kafka_utils.py` — `create_producer()` (acks=all, idempotent), `create_consumer()` (earliest offset)

**Step 3: CDC Poller** (`services/cdc_poller/`)
- `__init__.py`
- `config.py` — env vars: `ARANGO_HOST`, `ARANGO_DB`, `ARANGO_USER`, `ARANGO_PASSWORD`, `REDIS_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `POLL_INTERVAL_S=2`, `BATCH_LIMIT=500`, `WAL_CHUNK_SIZE=65536`
- `tick_store.py` — Redis key `cdc:arango:last_tick`, get/set/bootstrap from WAL logger-state
- `metric_cache.py` — AQL query `FOR m IN cdp_eventmetric RETURN {name: m.eventName, score: m.score}`, refresh every 5min via background thread
- `filters.py` — `should_publish(entry)`: type==2300, cname==`cdp_trackingevent`, has instrument_id or instrument_id_list in eventData
- `transformer.py` — fan-out: extract tickers (cap at 20), emit `CdpEventMessage` per ticker. Fields from WAL entry `data`: `_key`, `fingerprintId`, `metricName`, `createdAt`, `eventData.instrument_id[_list]`
- `poller.py` — HTTP GET `/_api/replication/logger-follow?from={tick}&chunkSize=65536`, NDJSON parse, filter→transform→batch(500)→flush to `cdp.events.raw` (partition key=ticker), advance tick ONLY after Kafka flush. Leader election via Redis SETNX `cdc:poller:leader` 30s TTL.
- `Dockerfile` — python:3.11-slim, copy `services/cdc_poller/` + `services/shared/`, entrypoint `python -m cdc_poller.poller`

**Step 4: docker-compose.yml additions**
- `zookeeper` (confluentinc/cp-zookeeper:7.6.0)
- `kafka` (confluentinc/cp-kafka:7.6.0, port 9092)
- `cdc-poller` (build ./services/cdc_poller, REDIS_URL=redis://redis:6379/2)

---

### Phase 1b — Scoring Consumer

**Step 5: Extract pure scoring function**
- File: `agentic_tools/recommendation_system/interest_score.py`
- Add `compute_incremental_score()` as a standalone function (lines ~213-237 logic)
- Original `run_batch_scoring_job()` loop is untouched — backward compatible
- Constants reused: `HALF_LIFE_DAYS=7.0`, `SCORING_K_FACTOR=50.0`

**Step 6: Fix batch_size bug**
- File: `data_workers/sync_segment_profiles.py:58`
- Change `batch_size=2` → `batch_size=500`

**Step 7: Fingerprint→profile_id Redis cache**
- File: `data_workers/sync_segment_profiles.py` — added `_populate_fingerprint_cache()`
- `fingerprintId` is NOT in `CDP_PROFILE_QUERY` or `ArangoProfile` model — needs separate AQL
- After `sync_service.sync_segment()` completes, runs:
  ```
  FOR p IN cdp_profile
    FILTER @segment_id IN p.inSegments[*].id
    FILTER p.fingerprintId != null
    RETURN { fid: p.fingerprintId, pid: p._key }
  ```
- For each result: `redis.setex(f"fp:{fid}", 86400, pid)` in Redis DB 2
- Non-fatal: if cache fails, profile sync still succeeds

**Step 8: Scoring Consumer** (`services/scoring_consumer/`)
- `__init__.py`
- `config.py` — env vars for PG, Redis, Kafka
- `pg_writer.py` — SELECT existing score by 6-column PK (using dummy values: `default_journey_map`, `default_stage`, `default_model`, `stock`), call `compute_incremental_score()`, INSERT ON CONFLICT DO UPDATE
- `consumer.py` — consumer group `leo-scoring-v1`, topic `cdp.events.raw`. Per message: resolve fingerprint→profile_id (Redis), resolve tenant_id (cached), validate profile in PG, read current score, compute, upsert, publish `ScoreUpdateMessage` to `leo.score.updates`, commit offset
- Dead-letter queue: 3 retries then publish to `leo.dlq` with error metadata
- `Dockerfile` — includes project root for `compute_incremental_score` import

**Step 9: docker-compose.yml** — add `scoring-consumer` service

---

### Phase 1c — NBA Publisher

**Step 10: NBA Publisher** (`services/nba_publisher/`)
- `__init__.py`
- `config.py` — thresholds: `score_delta > 0.1` OR `interest_score > 0.70`
- `throttle.py` — `is_throttled(profile_id, ticker)` checks `nba_throttle:{profile_id}:{ticker}`, `set_throttle()` SETEX 86400s
- `publisher.py` — consumer group `leo-nba-v1`, topic `leo.score.updates`. Per `ScoreUpdateMessage`:
  1. Threshold: `score_delta > 0.1` OR `interest_score > 0.70`
  2. Throttle check
  3. Fetch segments from PG `cdp_profiles.segments`
  4. `predict_user_event(score, segment_names)` — import from `agentic_tools/recommendation_system/predictive_engine.py`
  5. `recommend_system_action(score, predicted_event)` — import from `prescriptive_engine.py`
  6. Channel dispatch: `PUSH_NOTIFICATION`→mobile_push/web_push, `EMAIL_DIGEST`→email, `IN_APP_*`/`NONE`→skip. Uses `CHANNEL_REGISTRY` from `agentic_tools/marketing_tools.py`
  7. Set throttle, update PG NBA columns (reuse SQL pattern from `recommendation_orchestrator.py:86-98`), publish `NbaActionMessage` to `leo.nba.actions`, POST to webhook if configured
- Dead-letter queue: 3 retries then DLQ
- `Dockerfile` — PYTHONPATH includes project root

**Step 11: docker-compose.yml** — add `nba-publisher` service

---

### Phase 1d — Hardening & Cutover (NOT YET IMPLEMENTED)

**Step 12: Dead-Letter Queue**
- Already wired into scoring consumer + NBA publisher: try/except per message, 3 retries then publish to `leo.dlq` with error metadata

**Step 13: Prometheus metrics**
- Each service exposes `/metrics` via `prometheus_client` (infrastructure in place)
- Poller (:8080): `cdc_events_published_total`, `cdc_poll_latency_seconds`, `cdc_tick_lag`
- Scoring (:8081): `scoring_events_processed_total`, `scoring_latency_seconds`, `scoring_errors_total`
- NBA (:8082): `nba_dispatches_total` (by channel), `nba_throttled_total`, `nba_latency_seconds`
- TODO: Prometheus scrape config + Grafana dashboard

**Step 14: Celery batch reconciliation**
- File: `data_workers/celery_app.py` — add to beat schedule:
  ```python
  "batch-scoring-reconciliation": {
      "task": "data_workers.tasks.batch_scoring_reconciliation",
      "schedule": crontab(minute="0", hour="*/6"),
  },
  ```
- File: `data_workers/tasks.py` — add `batch_scoring_reconciliation` task that calls `run_batch_scoring_job()` and `run_batch_nba_update()`

**Step 15: Feature flag**
- Already wired: all 3 new services check `REALTIME_SCORING_ENABLED` at startup; if False → consume but don't write (dry-run)

**Step 16: Load test**
- `tests/load_test_cdc.py` — bulk-insert 10k events into ArangoDB, assert tick lag < 30s

---

## Critical Code Reuse Map

| What | Source File | Line Refs |
|---|---|---|
| Scoring constants | `interest_score.py:14-16,22-25` | `HALF_LIFE_DAYS`, `SCORING_K_FACTOR`, dummy PK values |
| Decay + normalize formula | `interest_score.py` | Extracted to `compute_incremental_score()` |
| Upsert SQL pattern | `interest_score.py:241-264` | 6-column PK ON CONFLICT |
| NBA UPDATE SQL | `recommendation_orchestrator.py:86-98` | 4 NBA columns + 6-column WHERE |
| `predict_user_event()` | `predictive_engine.py:28` | `(score, segment_names) → (event, prob)` |
| `recommend_system_action()` | `prescriptive_engine.py:27` | `(score, event) → (action, channel, conf, reason)` |
| `CHANNEL_REGISTRY` | `marketing_tools.py:17-22` | Channel class lookup |
| `resolve_ids()` | `interest_score.py:28-78` | Tenant+segment UUID resolution |
| `DatabaseSettings` | `data_utils/settings.py` | PG DSN, ArangoDB connection factory |

---

## Key Codebase Facts (verified)

- `fingerprintId` is NOT in `CDP_PROFILE_QUERY` or `ArangoProfile` model — needs separate AQL for Redis cache
- `run_batch_scoring_job` and `run_batch_nba_update` are NOT in Celery beat — first time scheduling (Phase 1d)
- `batch_size=2` at `sync_segment_profiles.py:58` — confirmed bug, fixed to 500
- `get_pg_connection()` returns `dict_row` connections — all consumer SQL handles dict results
- PG `product_recommendations` PK is 6-column: `(tenant_id, profile_id, journey_map_id, journey_stage_id, product_id, recommendation_model)`
- ArangoDB WAL API: `/_api/replication/logger-follow` returns NDJSON, type 2300 = document INSERT
- Existing Redis DBs: 0 (app cache), 1 (Celery). CDC services use DB 2

---

## New Files Summary

### New (20 files)
```
services/__init__.py
services/shared/__init__.py
services/shared/schemas.py
services/shared/kafka_utils.py
services/cdc_poller/__init__.py
services/cdc_poller/config.py
services/cdc_poller/tick_store.py
services/cdc_poller/metric_cache.py
services/cdc_poller/filters.py
services/cdc_poller/transformer.py
services/cdc_poller/poller.py
services/cdc_poller/Dockerfile
services/scoring_consumer/__init__.py
services/scoring_consumer/config.py
services/scoring_consumer/pg_writer.py
services/scoring_consumer/consumer.py
services/scoring_consumer/Dockerfile
services/nba_publisher/__init__.py
services/nba_publisher/config.py
services/nba_publisher/throttle.py
services/nba_publisher/publisher.py
services/nba_publisher/Dockerfile
```

### Modified (5 files)
```
requirements.txt          — added confluent-kafka, structlog, prometheus_client
main_configs.py           — added Kafka/CDC/realtime config vars
docker-compose.yml        — added zookeeper, kafka, cdc-poller, scoring-consumer, nba-publisher
interest_score.py         — added compute_incremental_score() (batch logic untouched)
sync_segment_profiles.py  — fixed batch_size=500, added fingerprint cache population
```

---

## Architecture Diagram

```
┌─────────────────┐
│   ArangoDB      │
│  (WAL Stream)   │
└────────┬────────┘
         │ HTTP logger-follow (poll every 2s)
         ▼
┌─────────────────┐     ┌──────────────────┐
│   CDC Poller    │────▶│  Kafka           │
│  (leader-elect) │     │  cdp.events.raw  │
└─────────────────┘     └────────┬─────────┘
                                 │
                                 ▼
                        ┌──────────────────┐     ┌───────────────────┐
                        │ Scoring Consumer │────▶│ Kafka             │
                        │ (leo-scoring-v1) │     │ leo.score.updates │
                        └──────────────────┘     └────────┬──────────┘
                                 │                        │
                                 │ upsert                 ▼
                                 ▼               ┌──────────────────┐
                        ┌──────────────┐         │  NBA Publisher   │
                        │  PostgreSQL  │◀────────│  (leo-nba-v1)   │
                        │  product_    │         └────────┬─────────┘
                        │  recomm.     │                  │
                        └──────────────┘                  ▼
                                                 ┌──────────────────┐
                                                 │ Channel Dispatch │
                                                 │ email / push /   │
                                                 │ webhook          │
                                                 └──────────────────┘

  Redis DB 2:
    - cdc:arango:last_tick      (WAL checkpoint)
    - cdc:poller:leader         (leader election)
    - fp:{fingerprintId}        (fingerprint→profile cache)
    - nba_throttle:{pid}:{tkr}  (24h dispatch throttle)
```

---

## Verification Plan

### Phase 1a
`docker-compose up zookeeper kafka cdc-poller` → insert test event in ArangoDB → verify message in `cdp.events.raw` via kafka-console-consumer < 5s

### Phase 1b
Unit test `compute_incremental_score` with known inputs. Integration: insert event → PG updated < 10s

### Phase 1c
Synthetic event pushing score > 0.70 → channel dispatch < 15s. Duplicate within 24h → throttled

### Phase 1d
Malformed message → `leo.dlq`. 10k load test → lag < 30s. Celery 6h reconciliation works standalone

---

## Kafka Topics

| Topic | Producer | Consumer | Partition Key | Schema |
|---|---|---|---|---|
| `cdp.events.raw` | CDC Poller | Scoring Consumer | ticker | `CdpEventMessage` |
| `leo.score.updates` | Scoring Consumer | NBA Publisher | `{profile_id}:{ticker}` | `ScoreUpdateMessage` |
| `leo.nba.actions` | NBA Publisher | (external / monitoring) | `{profile_id}:{ticker}` | `NbaActionMessage` |
| `leo.dlq` | Scoring Consumer, NBA Publisher | (ops/monitoring) | — | Error envelope |

---

## Environment Variables (New)

| Variable | Default | Used By |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | All services |
| `CDC_POLL_INTERVAL_S` | `2` | CDC Poller |
| `ACTIVATION_APP_WEBHOOK_URL` | `None` | NBA Publisher |
| `REALTIME_SCORING_ENABLED` | `False` | All services (feature flag) |
| `CDC_REDIS_URL` | `redis://localhost:6379/2` | Fingerprint cache |
| `POLL_INTERVAL_S` | `2` | CDC Poller |
| `BATCH_LIMIT` | `500` | CDC Poller |
| `WAL_CHUNK_SIZE` | `65536` | CDC Poller |
| `NBA_SCORE_DELTA_THRESHOLD` | `0.1` | NBA Publisher |
| `NBA_INTEREST_SCORE_THRESHOLD` | `0.70` | NBA Publisher |
