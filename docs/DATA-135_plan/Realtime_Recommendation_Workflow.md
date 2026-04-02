# Real-Time Interest Score — End-to-End Workflow

## Overview

A user event in the app triggers a score recalculation and NBA push within seconds, not hours. The pipeline flows through 3 microservices connected by Kafka.

```
User Action → ArangoDB WAL → CDC Poller → Kafka → Scoring Consumer → Kafka → NBA Publisher → Channel Dispatch
```

---

## Stage 1: CDC Poller (ArangoDB WAL → Kafka)

```
USER ACTION                    ARANGODB                         CDC POLLER
─────────                      ────────                         ──────────
User views ticker "VNM"   ──►  INSERT into                 ──►  HTTP GET /_api/replication/
on the app                     cdp_trackingevent                 logger-follow?from={tick}
                               {
                                 fingerprintId: "fp_abc",        Poll every 2s
                                 metricName: "ticker-view",      │
                                 eventData: {                    ▼
                                   instrument_id: "VNM"     filters.py: should_publish()
                                 }                           ├─ type == 2300? (doc INSERT)
                               }                             ├─ cname == "cdp_trackingevent"?
                                                             └─ has instrument_id?
                                                                    │ YES
                                                                    ▼
                                                             metric_cache.py:
                                                              get_metric_score("ticker-view")
                                                              → lookup from cdp_eventmetric
                                                                (cached, refreshed every 5min)
                                                                    │
                                                                    ▼
                                                             transformer.py: transform()
                                                              Fan-out: 1 event → N messages
                                                              (1 per ticker, cap 20)
                                                                    │
                                                                    ▼
                                                             CdpEventMessage {
                                                               fingerprint_id: "fp_abc",
                                                               ticker: "VNM",
                                                               metric_score: 10.0,
                                                               metric_name: "ticker-view",
                                                               created_at: "2026-03-23T..."
                                                             }
                                                                    │
                                                             Kafka produce → cdp.events.raw
                                                             partition key = "VNM"
                                                                    │
                                                             tick_store.py: set_tick()
                                                             (advance ONLY after Kafka flush)
```

### CDC Poller Internals

| Component | File | Purpose |
|---|---|---|
| Polling loop | `services/cdc_poller/poller.py` | HTTP GET WAL, parse NDJSON, batch flush |
| Filter | `services/cdc_poller/filters.py` | Only pass `cdp_trackingevent` INSERTs with ticker data |
| Transform | `services/cdc_poller/transformer.py` | Fan-out per ticker, build `CdpEventMessage` |
| Tick state | `services/cdc_poller/tick_store.py` | Redis checkpoint, bootstrap from WAL logger-state |
| Metric cache | `services/cdc_poller/metric_cache.py` | AQL cache of `cdp_eventmetric` scores (5min refresh) |
| Leader election | `services/cdc_poller/poller.py` | Redis SETNX `cdc:poller:leader` 30s TTL |

---

## Stage 2: Scoring Consumer (Kafka → PG Upsert → Kafka)

```
KAFKA: cdp.events.raw              SCORING CONSUMER
──────────────────                 ─────────────────
CdpEventMessage arrives   ──►     1. RESOLVE IDENTITY
                                     Redis GET fp:fp_abc → "profile_123"
                                     (populated by sync_segment_profiles
                                      every 5min, TTL 24h)
                                     │
                                     │ if no mapping → skip (profile not synced yet)
                                     ▼
                                  2. RESOLVE TENANT
                                     resolve_ids("master", "Active in last 3 months")
                                     → tenant_uuid (cached after first call)
                                     │
                                     ▼
                                  3. VALIDATE PROFILE
                                     SELECT 1 FROM cdp_profiles
                                     WHERE profile_id = 'profile_123'
                                     │
                                     │ if not found → skip (orphaned fingerprint)
                                     ▼
                                  4. READ CURRENT SCORE
                                     SELECT raw_score, interest_score, last_interaction_at
                                     FROM product_recommendations
                                     WHERE profile_id = 'profile_123'
                                       AND product_id = 'VNM'
                                       AND tenant_id = {tenant_uuid}
                                       AND journey_map_id = 'default_journey_map'
                                       AND journey_stage_id = 'default_stage'
                                       AND recommendation_model = 'default_model'
                                     │
                                     ├─ EXISTS: current_raw=45.0, prev_interest=0.47
                                     │          last_interaction_at=2026-03-22T10:00:00Z
                                     │
                                     └─ NOT EXISTS: current_raw=0.0, prev_interaction=None
                                     │
                                     ▼
                                  5. COMPUTE SCORE
                                     compute_incremental_score(
                                       current_raw = 45.0,
                                       incoming_points = 10.0,  ← from metric_score
                                       prev_interaction = 2026-03-22T10:00:00Z,
                                       last_event_time = 2026-03-23T08:00:00Z
                                     )
                                     │
                                     │  days_elapsed = (22h) / 86400 = 0.917 days
                                     │  decay_factor = 0.5^(0.917/7.0) = 0.906
                                     │  final_raw = (45.0 × 0.906) + 10.0 = 50.77
                                     │  final_interest = 50.77 / (50.77 + 50.0) = 0.5038
                                     │
                                     ▼
                                  6. UPSERT TO PG
                                     INSERT INTO product_recommendations (...)
                                     VALUES (tenant, 'profile_123', 'VNM', ...)
                                     ON CONFLICT (...6-col PK...)
                                     DO UPDATE SET
                                       raw_score = 50.77,
                                       interest_score = 0.5038,
                                       last_interaction_at = 2026-03-23T08:00:00Z
                                     │
                                     ▼
                                  7. PUBLISH SCORE UPDATE
                                     score_delta = 0.5038 - 0.4737 = 0.0301
                                     │
                                     ScoreUpdateMessage {
                                       tenant_id, profile_id: "profile_123",
                                       ticker: "VNM",
                                       interest_score: 0.5038,
                                       raw_score: 50.77,
                                       score_delta: 0.0301
                                     }
                                     │
                                     Kafka produce → leo.score.updates
                                     commit offset
```

### Scoring Consumer Internals

| Component | File | Purpose |
|---|---|---|
| Main loop | `services/scoring_consumer/consumer.py` | Kafka consume, orchestrate steps 1-7 |
| PG read/write | `services/scoring_consumer/pg_writer.py` | SELECT existing score, UPSERT new score |
| Score formula | `agentic_tools/recommendation_system/interest_score.py` | `compute_incremental_score()` |
| Identity resolution | Redis DB 2 key `fp:{fingerprintId}` | Populated by `sync_segment_profiles.py` |
| Tenant resolution | `interest_score.py:resolve_ids()` | Cached after first call |
| Error handling | `consumer.py` | 3 retries then publish to `leo.dlq` |

### The 6-Column Primary Key

Every read/write to `product_recommendations` uses all 6 PK columns:

```
(tenant_id, profile_id, journey_map_id, journey_stage_id, product_id, recommendation_model)
```

Real-time scoring uses dummy values for journey context:
- `journey_map_id = "default_journey_map"`
- `journey_stage_id = "default_stage"`
- `recommendation_model = "default_model"`
- `product_type = "stock"`

---

## Stage 3: NBA Publisher (Kafka → Engines → Channel Dispatch)

```
KAFKA: leo.score.updates           NBA PUBLISHER
────────────────────              ──────────────
ScoreUpdateMessage arrives  ──►   1. THRESHOLD CHECK
                                     score_delta > 0.1?  → NO (0.03)
                                     interest_score > 0.70? → NO (0.50)
                                     │
                                     └─ BOTH FAIL → skip, no action
                                        (user needs more engagement
                                         before triggering NBA)

─── LATER: user views VNM 5 more times, score reaches 0.75 ───

ScoreUpdateMessage {               1. THRESHOLD CHECK
  interest_score: 0.75,               score > 0.70? → YES ✓
  score_delta: 0.12                    │
}                                      ▼
                                  2. THROTTLE CHECK
                                     Redis EXISTS nba_throttle:profile_123:VNM
                                     → 0 (not throttled)
                                     │
                                     ▼
                                  3. FETCH SEGMENTS
                                     SELECT segments FROM cdp_profiles
                                     WHERE profile_id = 'profile_123'
                                     → ["Active in last 3 months",
                                        "High-Frequency Traders"]
                                     │
                                     ▼
                                  4. PREDICTIVE ENGINE
                                     predict_user_event(0.75, segments)
                                     │
                                     │ score ≥ 0.7 + "High-Frequency Traders"
                                     │ → ("order-created", 0.85)
                                     │
                                     ▼
                                  5. PRESCRIPTIVE ENGINE
                                     recommend_system_action(0.75, "order-created")
                                     │
                                     │ → ("STRONG_BUY_ALERT",
                                     │    "PUSH_NOTIFICATION",
                                     │    0.95,
                                     │    "High intent. Nudge to execute order.")
                                     │
                                     ▼
                                  6. CHANNEL DISPATCH
                                     PUSH_NOTIFICATION → mobile_push + web_push
                                     CHANNEL_REGISTRY["mobile_push"].send(...)
                                     CHANNEL_REGISTRY["web_push"].send(...)
                                     │
                                     ▼
                                  7. SET THROTTLE
                                     Redis SETEX nba_throttle:profile_123:VNM
                                     86400 "1"  (blocks re-dispatch for 24h)
                                     │
                                     ▼
                                  8. UPDATE PG NBA COLUMNS
                                     UPDATE product_recommendations
                                     SET next_best_action = 'STRONG_BUY_ALERT',
                                         nba_confidence = 0.95,
                                         predicted_user_event = 'order-created',
                                         prediction_probability = 0.85
                                     WHERE ...6-col PK...
                                     │
                                     ▼
                                  9. PUBLISH + WEBHOOK
                                     → Kafka: leo.nba.actions
                                     → POST ACTIVATION_APP_WEBHOOK_URL (if set)
```

### NBA Publisher Internals

| Component | File | Purpose |
|---|---|---|
| Main loop | `services/nba_publisher/publisher.py` | Kafka consume, orchestrate steps 1-9 |
| Throttle | `services/nba_publisher/throttle.py` | Redis SETEX 24h per (profile, ticker) |
| Predictive engine | `agentic_tools/recommendation_system/predictive_engine.py` | Score + segments → predicted event |
| Prescriptive engine | `agentic_tools/recommendation_system/prescriptive_engine.py` | Score + event → action + channel |
| Channel registry | `agentic_tools/marketing_tools.py` | `CHANNEL_REGISTRY` class lookup |
| Error handling | `publisher.py` | 3 retries then publish to `leo.dlq` |

### Channel Mapping

| Prescriptive Output | Dispatched To | Skip? |
|---|---|---|
| `PUSH_NOTIFICATION` | `mobile_push` + `web_push` | No |
| `EMAIL_DIGEST` | `email` | No |
| `IN_APP_BANNER` | — | Yes (in-app handled client-side) |
| `IN_APP_FEED` | — | Yes |
| `NONE` | — | Yes |

### NBA Decision Matrix

| Score Range | Predicted Event | NBA Action | Channel |
|---|---|---|---|
| 0.70–1.00 + Active Trader | `order-created` | `STRONG_BUY_ALERT` | PUSH_NOTIFICATION |
| 0.70–1.00 + Passive | `ticker-view` | `SEND_ANALYST_REPORT` | EMAIL_DIGEST |
| 0.50–0.69 | `watchlist-add` | `WATCHLIST_SUGGESTION` | IN_APP_BANNER |
| 0.10–0.49 | `search` | `DISCOVERY_NUDGE` | IN_APP_FEED |
| 0.00–0.09 | `ignore-content` | `WAIT` | NONE |

---

## The Scoring Formula

```
           ┌─────────────────────────────────────────────┐
           │  decay_factor = 0.5 ^ (days_elapsed / 7.0)  │
           │                                              │
           │  raw_score = (old_raw × decay_factor)        │
           │            + incoming_metric_score            │
           │                                              │
           │  interest_score = raw_score                   │
           │                  ─────────────────            │
           │                  raw_score + 50.0             │
           └─────────────────────────────────────────────┘

  - Half-life = 7 days (score halves if user is inactive for 7 days)
  - K-factor = 50.0 (normalizes to 0.0–1.0 range, 50 points = 0.50)
  - Same formula as batch scoring — just applied per-event instead of per-hour
```

### Score Progression Example

| Event # | incoming_points | days_since_last | decay | raw_score | interest_score |
|---|---|---|---|---|---|
| 1 (first view) | 10.0 | — | — | 10.0 | 0.167 |
| 2 (same day) | 10.0 | 0.0 | 1.000 | 20.0 | 0.286 |
| 3 (next day) | 10.0 | 1.0 | 0.906 | 28.1 | 0.360 |
| 4 (same day) | 10.0 | 0.0 | 1.000 | 38.1 | 0.432 |
| 5 (2 days later) | 10.0 | 2.0 | 0.820 | 41.2 | 0.452 |
| 6 (same day) | 15.0 | 0.0 | 1.000 | 56.2 | 0.529 |
| 7 (same day) | 15.0 | 0.0 | 1.000 | 71.2 | 0.587 |
| 8 (next day) | 15.0 | 1.0 | 0.906 | 79.5 | 0.614 |
| 9 (same day) | 20.0 | 0.0 | 1.000 | 99.5 | 0.665 |
| 10 (same day) | 20.0 | 0.0 | 1.000 | 119.5 | **0.705** ← triggers NBA |

---

## Fingerprint → Profile Resolution

The CDC events use `fingerprintId` (browser/device ID) but PG uses `profile_id`. The mapping is cached in Redis DB 2.

```
sync_segment_profiles.py (runs every 5min via Celery)
    │
    │ After profile sync completes:
    ▼
  AQL: FOR p IN cdp_profile
         FILTER @segment_id IN p.inSegments[*].id
         FILTER p.fingerprintId != null
         RETURN { fid: p.fingerprintId, pid: p._key }
    │
    ▼
  Redis DB 2: SETEX fp:{fingerprintId} 86400 {profile_id}
              SETEX fp:fp_abc         86400 profile_123
              SETEX fp:fp_def         86400 profile_456
              ...
```

---

## Feature Flag: Dry-Run Mode

All 3 services check `REALTIME_SCORING_ENABLED` at startup:

```
REALTIME_SCORING_ENABLED=False (default)
  ├─ CDC Poller: transforms + publishes to Kafka (normal)
  │              but logs [DRY-RUN] instead of producing
  ├─ Scoring Consumer: consumes messages, resolves identity
  │                    but skips PG upsert + Kafka publish
  └─ NBA Publisher: consumes score updates
                    but skips channel dispatch + PG update

REALTIME_SCORING_ENABLED=True
  └─ Full pipeline: CDC → Score → Upsert → NBA → Dispatch
```

---

## Error Handling: Dead-Letter Queue

```
Any message that fails 3 times:
    │
    ▼
  Wrapped in error envelope:
  {
    "original_topic": "cdp.events.raw",
    "original_value": "<raw message>",
    "error": "Profile not found: profile_123",
    "timestamp": "2026-03-23T08:00:00Z"
  }
    │
    ▼
  Kafka produce → leo.dlq
  (consumed by ops/monitoring for manual triage)
```

---

## Redis Keys Summary (DB 2)

| Key Pattern | Purpose | TTL | Set By |
|---|---|---|---|
| `cdc:arango:last_tick` | WAL checkpoint | permanent | CDC Poller |
| `cdc:poller:leader` | Leader election SETNX | 30s | CDC Poller |
| `fp:{fingerprintId}` | fingerprint → profile_id cache | 24h | sync_segment_profiles |
| `nba_throttle:{profile_id}:{ticker}` | Dispatch dedup | 24h | NBA Publisher |

---

## Kafka Topics

| Topic | Producer | Consumer | Partition Key | Schema |
|---|---|---|---|---|
| `cdp.events.raw` | CDC Poller | Scoring Consumer | ticker | `CdpEventMessage` |
| `leo.score.updates` | Scoring Consumer | NBA Publisher | `{profile_id}:{ticker}` | `ScoreUpdateMessage` |
| `leo.nba.actions` | NBA Publisher | External/monitoring | `{profile_id}:{ticker}` | `NbaActionMessage` |
| `leo.dlq` | Scoring + NBA | Ops/monitoring | — | Error envelope |

---

## Latency Budget

| Stage | Target | Bottleneck |
|---|---|---|
| ArangoDB INSERT → CDC Poller picks up | < 2s | Poll interval |
| CDC Poller → Kafka produce | < 1s | Kafka flush |
| Scoring Consumer: resolve + compute + upsert | < 3s | PG read-before-write |
| NBA Publisher: engines + dispatch | < 5s | Channel API latency |
| **End-to-end: event → channel dispatch** | **< 15s** | — |
