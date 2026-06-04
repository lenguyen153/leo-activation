# CDC Pipeline — Production Deployment Guide

## Overview

This document describes how to deploy the real-time CDC scoring pipeline to production. The pipeline consists of 5 new services (Zookeeper, Kafka, CDC Poller, Scoring Consumer, NBA Publisher) and 2 cron jobs (fingerprint cache, batch reconciliation).

**Production server:** `inno-cdp-data` at `/build/prod-app`
**Docker Compose file:** `docker-compose.prod.yml` (single file, no overlay)
**Registry:** `registry.innotech.vn/cdp-ai/c720-data-activation/`

---

## Prerequisites

- SSH access to production server
- Docker registry login: `docker login registry.innotech.vn`
- GitLab CI pipeline builds and pushes images automatically on merge to `api-ai-team`

---

## 1. Image Build & Push

CI handles this automatically via `.gitlab-ci.yml`. Four images are built:

| Image | Dockerfile | Contains |
|---|---|---|
| `core:latest` | `./Dockerfile` | FastAPI app + Celery tasks + cron scripts |
| `cdc-poller:latest` | `services/cdc_poller/Dockerfile` | CDC Poller microservice |
| `scoring-consumer:latest` | `services/scoring_consumer/Dockerfile` | Scoring Consumer microservice |
| `nba-publisher:latest` | `services/nba_publisher/Dockerfile` | NBA Publisher microservice |

Manual build (if needed):
```bash
docker build -t registry.innotech.vn/cdp-ai/c720-data-activation/core:latest .
docker build -f services/cdc_poller/Dockerfile -t registry.innotech.vn/cdp-ai/c720-data-activation/cdc-poller:latest .
docker build -f services/scoring_consumer/Dockerfile -t registry.innotech.vn/cdp-ai/c720-data-activation/scoring-consumer:latest .
docker build -f services/nba_publisher/Dockerfile -t registry.innotech.vn/cdp-ai/c720-data-activation/nba-publisher:latest .

docker push registry.innotech.vn/cdp-ai/c720-data-activation/core:latest
docker push registry.innotech.vn/cdp-ai/c720-data-activation/cdc-poller:latest
docker push registry.innotech.vn/cdp-ai/c720-data-activation/scoring-consumer:latest
docker push registry.innotech.vn/cdp-ai/c720-data-activation/nba-publisher:latest
```

---

## 2. Environment Variables

Add to `/build/prod-app/.env`:

```bash
# CDC Pipeline
REALTIME_SCORING_ENABLED=True
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
CDC_REDIS_URL=redis://redis:6379/2
TARGET_SEGMENT=Active in last 3 months
TARGET_TENANT=master
```

Add to `/build/prod-app/.env.cron` (used by cron docker run commands):

```bash
CDC_REDIS_URL=redis://redis:6379/2
TARGET_SEGMENT=Active in last 3 months
TARGET_TENANT=master
```

---

## 3. Docker Compose Configuration

The CDC services are added directly to `docker-compose.prod.yml`. Key configuration:

```yaml
cdc-poller:
  image: registry.innotech.vn/cdp-ai/c720-data-activation/cdc-poller:latest
  container_name: my_cdc_poller
  env_file: .env
  environment:
    - REDIS_URL=redis://redis:6379/2    # Override to use DB 2, not DB 0
  depends_on:
    - redis
    - kafka
  restart: unless-stopped

scoring-consumer:
  image: registry.innotech.vn/cdp-ai/c720-data-activation/scoring-consumer:latest
  container_name: my_scoring_consumer
  env_file: .env
  environment:
    - REDIS_URL=redis://redis:6379/2    # Override to use DB 2, not DB 0
  depends_on:
    - redis
    - kafka
  restart: unless-stopped

nba-publisher:
  image: registry.innotech.vn/cdp-ai/c720-data-activation/nba-publisher:latest
  container_name: my_nba_publisher
  env_file: .env
  environment:
    - REDIS_URL=redis://redis:6379/2    # Override to use DB 2, not DB 0
  depends_on:
    - redis
    - kafka
  restart: unless-stopped
```

**CRITICAL:** The `environment:` block MUST override `REDIS_URL=redis://redis:6379/2` for all 3 CDC services. Without this, they inherit `REDIS_URL=redis://redis:6379/0` from `.env` and write CDC keys to the wrong Redis database.

Kafka and Zookeeper also need persistent volumes:

```yaml
volumes:
  zookeeper_data:
  zookeeper_log:
  kafka_data:
```

---

## 4. Host Crontab Setup

The fingerprint cache and batch reconciliation run as cron jobs on the host (no Celery required). The shell scripts invoke Python inside a one-shot `core:latest` container.

```bash
# Edit crontab
crontab -e

# Add these lines:
*/5 * * * *  cd /build/prod-app && docker run --rm --env-file .env.cron --network prod-app_default registry.innotech.vn/cdp-ai/c720-data-activation/core:latest python -m data_workers.scripts.populate_fingerprint_cache >> /var/log/fp_cache.log 2>&1
0 */6 * * *  cd /build/prod-app && docker run --rm --env-file .env.cron --network prod-app_default registry.innotech.vn/cdp-ai/c720-data-activation/core:latest python -m data_workers.scripts.batch_scoring_reconciliation >> /var/log/batch_reconciliation.log 2>&1
```

Or use the shell script wrappers (if deployed to the server):
```bash
*/5 * * * *  /build/prod-app/shell-scripts/populate_fingerprint_cache.sh >> /var/log/fp_cache.log 2>&1
0 */6 * * *  /build/prod-app/shell-scripts/batch_scoring_reconciliation.sh >> /var/log/batch_reconciliation.log 2>&1
```

---

## 5. Deployment Steps

```bash
ssh cdpsysuser@inno-cdp-data
cd /build/prod-app

# 1. Pull latest images
docker compose pull

# 2. Start/restart services
docker compose up -d

# 3. Verify all containers are running
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "cdc|kafka|zookeeper|scoring|nba"

# 4. Populate fingerprint cache (first time)
docker run --rm --env-file .env.cron --network prod-app_default \
  registry.innotech.vn/cdp-ai/c720-data-activation/core:latest \
  python -m data_workers.scripts.populate_fingerprint_cache

# 5. Verify cache
docker exec prod_redis_cache redis-cli -n 2 DBSIZE
```

---

## 6. Health Checks

### Are CDC containers running?
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "cdc|kafka|zookeeper|scoring|nba"
```

### Is the CDC Poller alive?
```bash
# Leader key in Redis DB 2 (should return positive TTL)
docker exec prod_redis_cache redis-cli -n 2 TTL cdc:poller:leader

# Recent poller logs
docker logs --tail 20 my_cdc_poller
```

### Is the fingerprint cache populated?
```bash
docker exec prod_redis_cache redis-cli -n 2 DBSIZE
```

### Are events flowing through Kafka?
```bash
# List topics
docker exec my_kafka kafka-topics --bootstrap-server localhost:9092 --list

# Watch raw CDC events
docker exec my_kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic cdp.events.raw --max-messages 5

# Watch score updates
docker exec my_kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic leo.score.updates --max-messages 5
```

### Is the Scoring Consumer processing?
```bash
docker logs --tail 20 my_scoring_consumer | grep -i "scored\|DRY\|skip"
```

### Are scores landing in PG?
```bash
docker exec my_scoring_consumer python -c "
from data_utils.settings import DatabaseSettings
conn = DatabaseSettings().get_pg_connection()
with conn.cursor() as cur:
    cur.execute('''
        SELECT profile_id, product_id, interest_score, updated_at
        FROM product_recommendations
        ORDER BY updated_at DESC LIMIT 5
    ''')
    for row in cur.fetchall():
        print(row)
conn.close()
"
```

### Check for errors
```bash
docker logs my_cdc_poller 2>&1 | grep -i "error\|fail" | tail -10
docker logs my_scoring_consumer 2>&1 | grep -i "error\|fail" | tail -10
docker logs my_nba_publisher 2>&1 | grep -i "error\|fail" | tail -10
```

### Check dead-letter queue
```bash
docker exec my_kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic leo.dlq --from-beginning --max-messages 5
```

---

## 7. Rollback

If CDC causes issues, you can disable without removing containers:

**Option A: Dry-run mode** (safest)
```bash
# Set REALTIME_SCORING_ENABLED=False in .env
# Restart CDC services
docker compose restart cdc-poller scoring-consumer nba-publisher
```
Services continue consuming Kafka but skip all PG writes and channel dispatches.

**Option B: Stop CDC services**
```bash
docker compose stop cdc-poller scoring-consumer nba-publisher
```
Kafka and Zookeeper stay running. CDC can be restarted later — it resumes from the last committed offset.

**Option C: Full removal**
```bash
docker compose stop cdc-poller scoring-consumer nba-publisher kafka zookeeper
docker compose rm -f cdc-poller scoring-consumer nba-publisher kafka zookeeper
```
Remove Kafka volumes if you want a clean slate: `docker volume rm prod-app_kafka_data prod-app_zookeeper_data prod-app_zookeeper_log`

---

## 8. Known Production Details

| Item | Value |
|---|---|
| Redis container name | `prod_redis_cache` (service name: `redis`) |
| Redis DB for CDC | 2 (`redis://redis:6379/2`) |
| Redis DB for app | 0 (`redis://redis:6379/0`) |
| CDC Poller container | `my_cdc_poller` |
| Scoring Consumer container | `my_scoring_consumer` |
| NBA Publisher container | `my_nba_publisher` |
| Kafka container | `my_kafka` |
| PG host (from CDC) | `172.60.1.6:5435/leo_activation_db` |
| ArangoDB database | `cdp1invest` |
| Target segment | `Active in last 3 months` |
| Docker network | `prod-app_default` |
| Cron env file | `/build/prod-app/.env.cron` |

---

## 9. Architecture

```
User Action → ArangoDB WAL → CDC Poller → Kafka → Scoring Consumer → PG + Kafka → NBA Publisher → Channel Dispatch

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
                                                 │ push / email /   │
                                                 │ webhook          │
                                                 └──────────────────┘

Cron Jobs (host):
  */5 * * * *  populate_fingerprint_cache.py   → Redis DB 2 (fp:* keys)
  0 */6 * * *  batch_scoring_reconciliation.py → PG (failsafe re-score)
```

---

## 10. CDC Event Filter

Only these 5 `metricName` values trigger the CDC pipeline:

| metricName | Description |
|---|---|
| `ticker-view` | User viewed a stock ticker page |
| `watchlist-add` | User added a stock to watchlist |
| `order-created` | User placed an order |
| `order-preview` | User previewed an order |
| `order-canceled` | User canceled an order |

All other tracking events are ignored by the CDC Poller's filter (`services/cdc_poller/filters.py`).

The batch reconciliation job also filters these same metrics when CDC is healthy (avoids double-counting). When CDC is down, the batch job processes ALL metrics as a failsafe.
