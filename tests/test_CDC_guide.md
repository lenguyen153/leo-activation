# CDC Pipeline Testing Guide

## Level 1: Unit Tests (no infra needed)

```bash
python -m pytest tests/test_interest_score.py -v
```

Tests `compute_incremental_score()` — decay, normalization, edge cases. 11 tests.

---

## Level 2: Local Docker Smoke Test

```bash
# 1. Start infrastructure only
docker compose up -d redis zookeeper kafka

# 2. Wait for Kafka to be ready (~15s)
docker compose logs kafka | grep "started (kafka.server.KafkaServer)"

# 3. Start CDC poller in dry-run mode (REALTIME_SCORING_ENABLED=False)
docker compose up -d cdc-poller

# 4. Check poller logs — should show "dry-run mode" and WAL polling
docker compose logs -f cdc-poller
```

Expected: poller connects to ArangoDB WAL, polls every 2s, logs events but doesn't write to Kafka.

---

## Level 3: End-to-End with Kafka Messages

```bash
# 1. Enable real-time mode
export REALTIME_SCORING_ENABLED=true

# 2. Start full pipeline
docker compose up -d redis zookeeper kafka cdc-poller scoring-consumer nba-publisher

# 3. Open a Kafka console consumer to watch messages
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server kafka:9092 \
  --topic cdp.events.raw \
  --from-beginning

# 4. In another terminal — insert a test event into ArangoDB:
python -c "
from data_utils.settings import DatabaseSettings
db = DatabaseSettings().get_arango_db()
db.collection('cdp_trackingevent').insert({
    'fingerprintId': 'test-fp-001',
    'metricName': 'ticker-view',
    'createdAt': '2026-04-01T10:00:00Z',
    'eventData': {'instrument_id': 'VNM'}
})
print('Inserted test event')
"

# 5. Verify in kafka console consumer — should see CdpEventMessage within 5s

# 6. Check scoring consumer processed it:
docker compose logs scoring-consumer | grep "VNM"

# 7. Check PG for updated score:
python -c "
from data_utils.settings import DatabaseSettings
conn = DatabaseSettings().get_pg_connection()
with conn.cursor() as cur:
    cur.execute(\"\"\"
        SELECT profile_id, product_id, raw_score, interest_score
        FROM product_recommendations
        WHERE product_id = 'VNM'
        ORDER BY updated_at DESC LIMIT 5
    \"\"\")
    for row in cur.fetchall():
        print(row)
conn.close()
"
```

---

## Level 4: Verify Each Service Individually

### CDC Poller health

```bash
# Prometheus metrics
curl http://localhost:8080/metrics | grep cdc_events_published

# Redis tick state
docker compose exec redis redis-cli -n 2 GET cdc:arango:last_tick

# Leader election
docker compose exec redis redis-cli -n 2 TTL cdc:poller:leader
```

### Scoring Consumer

```bash
# Check consumer lag
docker compose exec kafka kafka-consumer-groups \
  --bootstrap-server kafka:9092 \
  --group leo-scoring-v1 \
  --describe
```

### NBA Publisher — throttle

```bash
# After a dispatch, check throttle key
docker compose exec redis redis-cli -n 2 KEYS "nba_throttle:*"
docker compose exec redis redis-cli -n 2 TTL "nba_throttle:test-profile:VNM"
```

### DLQ — check for errors

```bash
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server kafka:9092 \
  --topic leo.dlq \
  --from-beginning
```

---

## Level 5: Fingerprint Cache Verification

```bash
# Trigger a profile sync (populates fp:* keys in Redis DB 2)
python -c "
from data_workers.sync.sync_segment_profiles import run_synch_profiles
run_synch_profiles(segment_name='Active in last 3 months')
"

# Verify cache populated
docker compose exec redis redis-cli -n 2 KEYS "fp:*" | head -10
docker compose exec redis redis-cli -n 2 GET "fp:<some-fingerprint-id>"
```

---

## Level 6: Reconciliation Task

```bash
# Trigger manually via Celery
docker compose exec celery-worker celery -A data_workers.celery_app.worker call data_workers.tasks.batch_scoring_reconciliation

# Or verify it's in the beat schedule
docker compose exec celery-beat celery -A data_workers.celery_app.worker inspect scheduled
```

---

## Key Success Criteria

| Test | Pass Criteria |
|---|---|
| ArangoDB INSERT -> Kafka message | < 5 seconds |
| Kafka message -> PG score update | < 10 seconds |
| Score > 0.70 -> channel dispatch | < 15 seconds |
| Duplicate within 24h -> throttled | Redis key exists with ~86400 TTL |
| Malformed message -> DLQ | Visible in `leo.dlq` topic |
| Kill poller mid-batch -> restart | Tick resumes from last flushed point |
| `compute_incremental_score` unit tests | 11/11 passing |
