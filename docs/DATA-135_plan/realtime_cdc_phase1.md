# Real-Time Event-Driven Recommendation Engine — Phase 1

## Overview

Adds a real-time CDC pipeline: ArangoDB WAL → Kafka → Scoring Consumer → NBA Publisher.
Batch scoring via Celery is demoted to 6h reconciliation (Phase 1d, not yet implemented).

---

## Phase 1a — Shared Infrastructure + CDC Poller

### Step 1: Dependencies + Config
- `requirements.txt` — added `confluent-kafka>=2.3.0`, `structlog>=24.0`, `prometheus_client>=0.20`
- `main_configs.py` — added:
  - `KAFKA_BOOTSTRAP_SERVERS` (default `kafka:9092`)
  - `CDC_POLL_INTERVAL_S` (default `2`)
  - `ACTIVATION_APP_WEBHOOK_URL` (default `None`)
  - `REALTIME_SCORING_ENABLED` (default `False`)

### Step 2: Shared module (`services/shared/`)
- `schemas.py` — 3 Pydantic models: `CdpEventMessage`, `ScoreUpdateMessage`, `NbaActionMessage`
- `kafka_utils.py` — `create_producer()` (acks=all, idempotent), `create_consumer()` (earliest offset)

### Step 3: CDC Poller (`services/cdc_poller/`)
- `config.py` — env vars for ArangoDB, Redis (DB 2), Kafka, poll interval, batch limit
- `tick_store.py` — Redis key `cdc:arango:last_tick`, get/set/bootstrap from WAL logger-state
- `metric_cache.py` — AQL loads `cdp_eventmetric` scores, refreshes every 5min via background thread
- `filters.py` — `should_publish(entry)`: type==2300, cname==`cdp_trackingevent`, has instrument_id or instrument_id_list
- `transformer.py` — fan-out: extracts tickers (capped at 20), emits `CdpEventMessage` per ticker
- `poller.py` — HTTP GET `/_api/replication/logger-follow`, NDJSON parse, filter→transform→batch(500)→flush to `cdp.events.raw` (partition key=ticker), advances tick ONLY after Kafka flush. Leader election via Redis SETNX 30s TTL.
- `Dockerfile` — python:3.11-slim, entrypoint `python -m services.cdc_poller.poller`

### Step 4: docker-compose.yml
- Added `zookeeper` (confluentinc/cp-zookeeper:7.6.0)
- Added `kafka` (confluentinc/cp-kafka:7.6.0)
- Added `cdc-poller` (build from `services/cdc_poller/Dockerfile`, REDIS_URL=redis://redis:6379/2)

---

## Phase 1b — Scoring Consumer

### Step 5: Extract pure scoring function
- `interest_score.py` — added `compute_incremental_score()` as a standalone function
- Original `run_batch_scoring_job()` loop is **untouched** — batch logic preserved as-is

### Step 6: Fix batch_size bug
- `sync_segment_profiles.py:58` — changed `batch_size=2` → `batch_size=500`

### Step 7: Fingerprint→profile_id Redis cache
- `sync_segment_profiles.py` — after `sync_service.sync_segment()` completes, runs separate AQL:
  ```
  FOR p IN cdp_profile
    FILTER @segment_id IN p.inSegments[*].id
    FILTER p.fingerprintId != null
    RETURN { fid: p.fingerprintId, pid: p._key }
  ```
- Stores each result as `redis.setex(f"fp:{fid}", 86400, pid)` in Redis DB 2
- Non-fatal: if cache population fails, sync still succeeds

### Step 8: Scoring Consumer (`services/scoring_consumer/`)
- `config.py` — env vars for PG, Redis, Kafka
- `pg_writer.py` — SELECT existing score by 6-column PK, upsert with ON CONFLICT DO UPDATE
- `consumer.py` — consumer group `leo-scoring-v1`, topic `cdp.events.raw`. Per message:
  1. Resolve fingerprint→profile_id (Redis)
  2. Resolve tenant_id (cached)
  3. Validate profile exists in PG
  4. Read current score
  5. Call `compute_incremental_score()`
  6. Upsert to PG
  7. Publish `ScoreUpdateMessage` to `leo.score.updates`
  8. Commit offset
- Dead-letter queue: 3 retries then publish to `leo.dlq` with error metadata
- `Dockerfile` — includes project root for `compute_incremental_score` import

### Step 9: docker-compose.yml
- Added `scoring-consumer` service

---

## Phase 1c — NBA Publisher

### Step 10: NBA Publisher (`services/nba_publisher/`)
- `config.py` — thresholds: `score_delta > 0.1` OR `interest_score > 0.70`
- `throttle.py` — `is_throttled(profile_id, ticker)` checks Redis key, `set_throttle()` SETEX 24h
- `publisher.py` — consumer group `leo-nba-v1`, topic `leo.score.updates`. Per message:
  1. Threshold check
  2. Throttle check
  3. Fetch segments from PG `cdp_profiles.segments`
  4. `predict_user_event(score, segment_names)` — from `predictive_engine.py`
  5. `recommend_system_action(score, predicted_event)` — from `prescriptive_engine.py`
  6. Channel dispatch: `PUSH_NOTIFICATION`→mobile_push/web_push, `EMAIL_DIGEST`→email, `IN_APP_*`/`NONE`→skip
  7. Set throttle
  8. Update PG NBA columns (reuses SQL pattern from `recommendation_orchestrator.py:86-98`)
  9. Publish `NbaActionMessage` to `leo.nba.actions`
  10. POST to webhook if `ACTIVATION_APP_WEBHOOK_URL` is configured
- Dead-letter queue: 3 retries then DLQ
- `Dockerfile` — includes project root for engine imports

### Step 11: docker-compose.yml
- Added `nba-publisher` service

---

## Phase 1d — Hardening & Cutover (NOT YET IMPLEMENTED)

Deferred items:
- Celery beat 6h reconciliation schedule (`batch_scoring_reconciliation` task)
- Prometheus `/metrics` endpoints (infrastructure is in place, scraping config not done)
- Feature flag dry-run is already wired into all 3 services via `REALTIME_SCORING_ENABLED`
- Load test script (`tests/load_test_cdc.py`)

---

## Files Summary

### New files (20)
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

### Modified files (5)
```
requirements.txt          — added confluent-kafka, structlog, prometheus_client
main_configs.py           — added Kafka/CDC/realtime config vars
docker-compose.yml        — added zookeeper, kafka, cdc-poller, scoring-consumer, nba-publisher
interest_score.py         — added compute_incremental_score() (batch logic untouched)
sync_segment_profiles.py  — fixed batch_size=500, added fingerprint cache population
```

---

## Testing Phase 1

### Setup

```bash
docker-compose up -d redis zookeeper kafka cdc-poller scoring-consumer nba-publisher
```

Set `REALTIME_SCORING_ENABLED=True` in `.env` (otherwise all 3 services run in dry-run mode — they consume but don't write).

### Pre-requisite: Fingerprint cache

The scoring consumer needs `fp:{fingerprintId}` → `profile_id` in Redis DB 2. Either:
- Run a profile sync (Celery `sync_profiles_task`) — it now auto-populates the cache
- Or manually seed: `redis-cli -n 2 SET fp:fp_test_user_123 <profile_id>`

### Test Scenario: User views stock ticker "VNM"

**1. Insert a tracking event into ArangoDB:**

```javascript
// ArangoDB web UI or arangosh:
db.cdp_trackingevent.insert({
  fingerprintId: "fp_test_user_123",
  metricName: "ticker-view",
  createdAt: new Date().toISOString(),
  eventData: {
    instrument_id: "VNM"
  }
});
```

**2. Pipeline flow (automatic, within seconds):**

| Service | What happens | Latency |
|---|---|---|
| CDC Poller | Reads WAL entry (type=2300, cname=cdp_trackingevent), transforms to `CdpEventMessage`, publishes to `cdp.events.raw` | ~2s |
| Scoring Consumer | Resolves `fp:fp_test_user_123` → profile_id, reads current score from PG, calls `compute_incremental_score()`, upserts, publishes to `leo.score.updates` | ~5s |
| NBA Publisher | Checks thresholds, runs predictive + prescriptive engines, dispatches to channel, updates NBA columns in PG, publishes to `leo.nba.actions` | ~8s |

**3. Verify each step:**

```bash
# CDC poller → Kafka (should appear < 5s after insert):
docker exec my_kafka kafka-console-consumer \
  --bootstrap-server kafka:9092 \
  --topic cdp.events.raw \
  --from-beginning --max-messages 1

# Scoring consumer → score update:
docker exec my_kafka kafka-console-consumer \
  --bootstrap-server kafka:9092 \
  --topic leo.score.updates \
  --from-beginning --max-messages 1

# NBA publisher → action dispatched:
docker exec my_kafka kafka-console-consumer \
  --bootstrap-server kafka:9092 \
  --topic leo.nba.actions \
  --from-beginning --max-messages 1

# PG updated:
psql -h localhost -p 5435 -U postgres -d leo_cdp -c \
  "SELECT profile_id, product_id, interest_score, next_best_action
   FROM product_recommendations
   WHERE product_id = 'VNM'
   ORDER BY updated_at DESC LIMIT 5;"
```

### Throttle Test

Insert the same event again within 24h. The NBA publisher should log "Throttled" and skip dispatch.

```bash
# Verify throttle key exists:
redis-cli -n 2 EXISTS nba_throttle:<profile_id>:VNM
```

### Dry-Run Test

Set `REALTIME_SCORING_ENABLED=False` and restart services. Events flow through the pipeline but no PG writes or channel dispatches occur. Check service logs for `[DRY-RUN]` messages.

### Dead-Letter Queue Test

Publish a malformed message to `cdp.events.raw`:
```bash
echo '{"invalid": "json"}' | docker exec -i my_kafka kafka-console-producer \
  --bootstrap-server kafka:9092 \
  --topic cdp.events.raw
```

After 3 retries, the message should appear in `leo.dlq`:
```bash
docker exec my_kafka kafka-console-consumer \
  --bootstrap-server kafka:9092 \
  --topic leo.dlq \
  --from-beginning --max-messages 1
```
