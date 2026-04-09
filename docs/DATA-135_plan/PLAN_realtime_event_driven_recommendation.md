# Phase 1: Hybrid Recommendation Engine — Real-Time Streaming Architecture

**Target:** Replace batch Celery scoring with an event-driven pipeline. A user event in ArangoDB triggers a score recalculation and NBA push within seconds, not hours.

---

## 1. Architecture & Component Breakdown

```
┌─────────────────────────────────────────────────────────────────┐
│  BLACK BOX CDP                                                  │
│  ArangoDB (cdp_trackingevent, cdp_profile, cdp_eventmetric)    │
└────────────────────────┬────────────────────────────────────────┘
                         │  WAL tail via /_api/replication/logger-follow
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  [NEW] CDC Poller Microservice  (Python)                        │
│  - Reads WAL ticks from ArangoDB HTTP API                       │
│  - Filters: collection=cdp_trackingevent, op=INSERT             │
│  - State: last_tick stored in Redis                             │
│  - Publishes: cdp.events.raw topic → Kafka                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Kafka                                                          │
│  Topics:                                                        │
│    cdp.events.raw          (CDC output, partitioned by ticker)  │
│    leo.score.updates       (scored events)                      │
│    leo.nba.actions         (NBA decisions)                      │
└───────┬──────────────────────────┬──────────────────────────────┘
        │                          │
        ▼                          ▼
┌───────────────┐        ┌──────────────────────────────────────┐
│ [NEW] Event   │        │ [NEW] NBA Publisher Service          │
│ Scoring       │        │ - Consumes leo.nba.actions           │
│ Consumer      │        │ - Calls predictive_engine +          │
│               │        │   prescriptive_engine                │
│ - Reuses      │        │ - Dispatches to Zalo/Email/Push      │
│   existing    │        │   (reuses existing channel code)     │
│   score       │        │ - Writes delivery_log → PG           │
│   formula     │        └──────────────────────────────────────┘
│ - Upserts PG  │
│   product_    │
│   recommendations│
└───────────────┘
```

**New components:**

| Component | Language | Infra |
|---|---|---|
| CDC Poller Microservice | Python | Docker container, Redis, Kafka producer |
| Event Scoring Consumer | Python | Kafka consumer group, PG writer |
| NBA Publisher Service | Python | Kafka consumer, reuses existing channel code |
| Redis tick state store | Redis | Existing Redis instance (`CELERY_REDIS_URL`) |
| Kafka cluster | Kafka 3.x / MSK | New infra (or Confluent Cloud for POC) |

**Existing components retained (batch fallback):**
- Celery Beat jobs remain active as a reconciliation layer — they catch any events the CDC poller missed.

---

## 2. The ArangoDB CDC Poller — Detailed Design

### 2.1 Core Polling Loop

```python
# cdc_poller/poller.py — skeleton only

ARANGO_WAL_URL = "{host}/_api/replication/logger-follow"
TICK_REDIS_KEY = "cdc:arango:last_tick"
POLL_INTERVAL_S = 2
BATCH_LIMIT = 500

def poll_once(arango_session, redis_client, kafka_producer):
    last_tick = redis_client.get(TICK_REDIS_KEY) or "0"
    resp = arango_session.get(
        ARANGO_WAL_URL,
        params={"from": last_tick, "chunkSize": 65536},
        stream=True,
        timeout=10,
    )
    # Response is NDJSON; each line is one WAL entry
    new_tick = last_tick
    batch = []
    for line in resp.iter_lines():
        entry = json.loads(line)
        new_tick = entry["tick"]
        if should_publish(entry):       # filter logic below
            batch.append(transform(entry))
        if len(batch) >= BATCH_LIMIT:
            flush(kafka_producer, batch)
            batch.clear()
    if batch:
        flush(kafka_producer, batch)
    # Only advance tick AFTER successful Kafka flush
    redis_client.set(TICK_REDIS_KEY, new_tick)
```

### 2.2 Tick State Management

- **Storage:** Redis string key `cdc:arango:last_tick` — atomic `SET` after each successful batch flush.
- **Bootstrap:** On first deploy (or after Redis flush), seed the tick by calling `GET /_api/replication/logger-state` and using `lastLogTick` as the starting point. This avoids replaying historical data.
- **Fault recovery:** If the poller crashes mid-batch, the tick is not advanced. On restart, it re-reads from the last committed tick. Duplicates are handled via **idempotent Kafka message keys** (`profile_id:ticker:event_timestamp`).
- **Tick expiry risk (critical):** ArangoDB's WAL is a rotating log. If the poller is down too long, old ticks are garbage-collected. Mitigation: monitor `/_api/replication/logger-state` and alert when `(current_tick - last_tick) > WARN_THRESHOLD`. If expired, fall back to a full Celery batch resync.

### 2.3 Event Filtering (avoid Kafka overload)

Only publish events matching ALL of:

```python
def should_publish(entry: dict) -> bool:
    return (
        entry.get("type") == 2300           # INSERT operation (2300=document insert)
        and entry.get("cname") == "cdp_trackingevent"
        and entry.get("data", {}).get("eventData", {}).get("instrument_id") is not None
        # OR instrument_id_list is non-empty:
        or bool(entry.get("data", {}).get("eventData", {}).get("instrument_id_list"))
    )
```

Filter out: profile updates, segment mutations, system collections (`_*`), and events with no `instrument_id` (non-financial events).

### 2.4 Message Schema (Kafka payload)

```json
{
  "event_id": "cdp_trackingevent/<arango_key>",
  "profile_fingerprint": "fp_abc123",
  "ticker": "VNM",
  "event_name": "ticker-view",
  "metric_score": 10.0,
  "occurred_at": "2026-03-20T08:00:00Z",
  "source_tick": "12345678"
}
```

Kafka partition key: `ticker` — ensures all events for one ticker land on the same partition, enabling ordered processing.

### 2.5 Fault Tolerance Checklist

| Risk | Mitigation |
|---|---|
| ArangoDB WAL tick expires | Redis alert + fallback to Celery batch |
| Kafka broker unavailable | Exponential backoff with in-memory buffer (max 10k events); dead-letter log to disk |
| Duplicate events on restart | Idempotent upsert key in PG (`ON CONFLICT DO UPDATE`) |
| Schema change in `cdp_trackingevent` | Graceful skip with `structlog` warning; schema registry (Avro/Protobuf) in v2 |
| Single poller as SPOF | Run 2 replicas; use Redis `SET NX` distributed lock to elect leader |

---

## 3. Step-by-Step Implementation Strategy

### Phase 1a — POC (2 weeks)

**Goal:** Prove the WAL tap works and latency is acceptable.

1. **Spike: ArangoDB WAL API** — Manually `curl` `/_api/replication/logger-follow` on staging. Confirm `cdp_trackingevent` INSERT entries are visible and the `fingerprintId` + `instrument_id` fields are present in WAL data.
2. **Tick state prototype** — Write minimal Python poller that reads WAL, prints filtered events, stores tick in Redis. No Kafka yet.
3. **Local Kafka** — Spin up single-node Kafka via `docker-compose` extension. Add to the existing `docker-compose.yml`.
4. **Wire poller → Kafka** — Publish filtered events to `cdp.events.raw`. Verify with `kafka-console-consumer`.
5. **Validate duplicate handling** — Kill poller mid-batch, restart, confirm events are idempotent in PG upsert.

**Exit criteria:** End-to-end latency from ArangoDB INSERT → Kafka message < 5 seconds on staging.

---

### Phase 1b — Event Scoring Consumer (2 weeks)

**Goal:** Replace the scoring path with real-time calculation.

6. **Extract scoring logic** — Move the decay formula from `interest_score.py:run_batch_scoring_job` (lines ~121+) into a pure function `compute_incremental_score(current_raw, current_score, incoming_points, last_interaction_at)` with no DB dependencies.
7. **Build Kafka consumer** — Consumer group `leo-scoring-v1`. For each message:
   - Read current `(raw_score, last_interaction_at)` from PG `product_recommendations`.
   - Apply `compute_incremental_score`.
   - Upsert back with `ON CONFLICT (tenant_id, profile_id, ...) DO UPDATE`.
   - Publish result to `leo.score.updates`.
8. **Fix the `batch_size=2` bug** — In `data_workers/sync_segment_profiles.py:44`, change to `batch_size=500` while in this area of the code.
9. **Parallel run** — Run both Celery batch and Kafka consumer simultaneously. Compare PG scores after each batch run. Acceptable drift: < 2% on test segment.

**Exit criteria:** Score in PG is updated within 10 seconds of a `cdp_trackingevent` INSERT on staging.

---

### Phase 1c — NBA Publisher & Activation (1 week)

**Goal:** Complete the real-time push to channels.

10. **Build NBA Publisher** — Consumes `leo.score.updates`. For each update where `interest_score` crosses a threshold (e.g., jumps > 0.1 in one event or exceeds 0.70):
    - Call `predict_user_event(score, segment_names)` from `predictive_engine.py`.
    - Call `recommend_system_action(score, predicted_event)` from `prescriptive_engine.py`.
    - Dispatch via the appropriate channel (Zalo/Email/Push).
    - Publish `leo.nba.actions` for audit log.
11. **Throttle guard** — A user MUST NOT receive more than 1 NBA push per 24h per ticker. Implement as Redis `SETEX` with 86400s TTL: key = `nba_throttle:{profile_id}:{ticker}`.
12. **Activation App webhook** — Publish NBA action to `leo.nba.actions` AND POST to `ACTIVATION_APP_WEBHOOK_URL` (new env var) for real-time push to mobile/web.

**Exit criteria:** A synthetic `cdp_trackingevent` INSERT triggers a Zalo/email dispatch within 15 seconds.

---

### Phase 1d — Hardening & Cutover (1 week)

13. **Dead-letter queue** — Configure Kafka DLQ topic `leo.dlq`. Route malformed or repeatedly-failing events there for manual triage.
14. **Monitoring** — Add Prometheus metrics to all three new services: `cdc_events_published_total`, `scoring_latency_p99`, `nba_dispatches_total`. Wire to existing Grafana.
15. **Celery batch as fallback** — Keep `run_batch_scoring_job` Celery task but reduce frequency from `*/5 * * * *` to `0 */6 * * *` (every 6 hours). Its role is now **gap reconciliation**, not primary scoring.
16. **Load test** — Simulate 10k concurrent events via a script that bulk-inserts into ArangoDB staging. Confirm poller lag stays < 30s.
17. **Production cutover** — Deploy CDC poller and consumers behind a feature flag. Enable on 5% of tenant traffic first, then 100%.

---

## 4. Key Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **WAL tick GC** — ArangoDB rotates the WAL; if poller is down >N hours, old ticks are gone. | High | Monitor `logger-state.lastLogTick` vs stored tick. If delta > threshold, alert ops and trigger a Celery full-resync. Never let the poller be down for >1 WAL retention window. |
| **ArangoDB WAL is not a public API** — `/_api/replication/logger-follow` is documented but designed for replication, not CDC. Field names may change. | High | Pin ArangoDB version in Docker. Add integration test that validates WAL entry schema on every deploy. |
| **Kafka partition ordering** — Ticker-partitioned ordering breaks if a single user has rapid burst events (e.g., 100 ticks in 1s). | Medium | Use idempotent upsert (not append) in PG. Score is a convergent CRDT-like accumulator; out-of-order application produces the same final state. |
| **PG read-before-write in scoring consumer** — Every event does a SELECT then UPDATE, creating lock contention under high load. | Medium | Use `INSERT ... ON CONFLICT DO UPDATE SET raw_score = product_recommendations.raw_score + EXCLUDED.raw_score` directly in SQL to make it a single atomic operation. |
| **Duplicate NBA dispatches** — Score threshold can be crossed multiple times quickly (score bounces around 0.70). | High | Redis `SETEX` throttle guard (Phase 1c, step 11) is mandatory before enabling NBA dispatch. |
| **CDC poller as SPOF** | Medium | Run 2 replicas with Redis `SET NX` leader election. Follower polls but does not publish. |
| **Scoring fan-out** — One event may affect hundreds of (profile, ticker) pairs if `instrument_id_list` has many tickers. | Low-Medium | Process each `(profile_id, ticker)` pair as a separate Kafka message. Cap `instrument_id_list` fan-out at 20 tickers per event; log and discard the rest with a warning. |

---

## 5. docker-compose additions (reference)

Add to the existing `docker-compose.yml`:

```yaml
  zookeeper:
    image: confluentinc/cp-zookeeper:7.6.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    depends_on: [zookeeper]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
    ports: ["9092:9092"]

  cdc-poller:
    build: ./services/cdc_poller
    environment:
      ARANGO_HOST: ${ARANGO_HOST}
      ARANGO_DB: ${ARANGO_DB}
      REDIS_URL: ${CELERY_REDIS_URL}
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
    depends_on: [kafka]
    restart: unless-stopped
```

---

## Implementation Priority Order

1. WAL spike (validate feasibility before writing any production code)
2. `compute_incremental_score` extraction (lowest risk, highest value — also makes the batch path testable)
3. CDC Poller → Kafka
4. Event Scoring Consumer
5. NBA throttle guard
6. NBA Publisher + Activation webhook
7. Monitoring + cutover
