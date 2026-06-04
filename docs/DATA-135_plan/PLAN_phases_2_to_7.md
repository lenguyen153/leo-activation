# Real-Time Recommendation Engine — Phases 2–7

**Prerequisite:** Phase 1 (CDC Poller → Kafka → Scoring Consumer → NBA Publisher) is implemented and running.

---

## Phase 2: Hardening, Observability & Celery Reconciliation (1 week)

**Goal:** Make the Phase 1 pipeline production-ready with monitoring, batch fallback, and operational tooling.

### Step 2.1: Celery Batch Reconciliation
- **File:** `data_workers/celery_app.py` — add beat schedule entry:
  ```python
  "batch-scoring-reconciliation": {
      "task": "data_workers.tasks.batch_scoring_reconciliation",
      "schedule": crontab(minute="0", hour="*/6"),  # Every 6 hours
  },
  ```
- **File:** `data_workers/tasks.py` — add new task:
  ```python
  @shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={"max_retries": 2})
  def batch_scoring_reconciliation(self):
      """6h reconciliation: catches any events the CDC pipeline missed."""
      settings = DatabaseSettings()
      now = datetime.now(timezone.utc)
      window_end = now.replace(minute=0, second=0, microsecond=0)
      window_start = window_end - timedelta(hours=6)
      run_batch_scoring_job(settings, window_start.isoformat(), window_end.isoformat())
      run_batch_nba_update(settings)
  ```

### Step 2.2: Prometheus Scrape Config + Grafana Dashboard
- **New file:** `monitoring/prometheus.yml`
  - Scrape targets: `cdc-poller:8080`, `scoring-consumer:8081`, `nba-publisher:8082`
- **New file:** `monitoring/grafana/dashboards/cdc_pipeline.json`
  - Panels: events/sec throughput, p99 latency per service, DLQ depth, tick lag, throttle rate
- **docker-compose.yml** — add `prometheus` and `grafana` services (internal only, no external ports)
- Metrics already exposed by Phase 1 services:
  - Poller: `cdc_events_published_total`, `cdc_poll_latency_seconds`, `cdc_tick_lag`
  - Scoring: `scoring_events_processed_total`, `scoring_latency_seconds`, `scoring_errors_total`
  - NBA: `nba_dispatches_total{channel}`, `nba_throttled_total`, `nba_latency_seconds`

### Step 2.3: DLQ Consumer & Alerting
- **New file:** `services/dlq_consumer/consumer.py`
  - Consumes `leo.dlq` topic
  - Writes failed messages to PG table `cdc_dead_letters` (new table) for manual triage
  - Exposes `dlq_messages_total` Prometheus counter
- **Schema addition:** `sql-scripts/schema.sql`
  ```sql
  CREATE TABLE IF NOT EXISTS cdc_dead_letters (
      id BIGSERIAL PRIMARY KEY,
      original_topic TEXT NOT NULL,
      original_value TEXT,
      error_message TEXT,
      retries INTEGER DEFAULT 0,
      resolved BOOLEAN DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  ```

### Step 2.4: WAL Tick Lag Alerting
- In `services/cdc_poller/poller.py`: query `/_api/replication/logger-state` every 60s, compute `(head_tick - processed_tick)`, update `cdc_tick_lag` gauge
- Alert rule in Prometheus: `cdc_tick_lag > 100000` for > 5 minutes → PagerDuty/Slack

### Step 2.5: Load Test
- **New file:** `tests/load_test_cdc.py`
  - Bulk-insert 10k `cdp_trackingevent` documents into ArangoDB
  - Poll `cdc_tick_lag` metric, assert lag < 30s
  - Verify all 10k events appear in PG `product_recommendations` within 60s

### Exit Criteria
- Grafana dashboard shows live metrics for all 3 services
- DLQ consumer processes malformed messages and persists them
- 10k load test passes with tick lag < 30s
- Celery 6h reconciliation runs and fills any scoring gaps

---

## Phase 3: Behavioral Events Feedback Loop (2 weeks)

**Goal:** Close the loop — real-time user actions (from the app) feed back into scoring via the same Kafka pipeline, enabling self-reinforcing recommendations.

### Step 3.1: Behavioral Event Ingestion API
- **New file:** `api/behavioral_events.py` — FastAPI router
  - `POST /events/track` — accepts `{profile_id, event_metric_name, entity_type, entity_id, sentiment_val, metadata}`
  - Writes to PG `behavioral_events` table (already exists in schema)
  - Publishes to Kafka `cdp.events.behavioral` topic
  - Rate-limited: max 100 events/profile/minute (Redis counter)

### Step 3.2: Behavioral Event Scoring Consumer
- **New file:** `services/behavioral_consumer/consumer.py`
  - Consumes `cdp.events.behavioral`
  - Scoring logic:
    - Positive sentiment (+1) → adds metric score to interest
    - Negative sentiment (-1) → applies penalty (configurable via `NEGATIVE_SENTIMENT_WEIGHT`, default `-0.5`)
    - Neutral (0) → standard metric score
  - Reuses `compute_incremental_score()` from Phase 1
  - Publishes to `leo.score.updates` (same topic as CDC scoring consumer)
  - NBA Publisher processes score updates identically regardless of source

### Step 3.3: Engagement Attribution
- **Modified:** `services/nba_publisher/publisher.py`
  - After channel dispatch, record `{profile_id, ticker, action, channel, dispatched_at}` in PG `delivery_log`
  - When a behavioral event arrives for a profile that was recently NBA-dispatched (within 1h), tag it as `attributed=true` in `behavioral_events.meta_data`
  - This enables measuring "did the push notification actually drive engagement?"

### Step 3.4: Interest Decay Daemon
- **New file:** `services/decay_daemon/daemon.py`
  - Runs every 4 hours (via Celery beat or standalone cron)
  - Applies time-decay to all `product_recommendations` where `last_interaction_at` > 7 days ago
  - Uses same `HALF_LIFE_DAYS=7.0` constant
  - Prevents stale scores from lingering when a user stops engaging

### New Kafka Topics
| Topic | Producer | Consumer |
|---|---|---|
| `cdp.events.behavioral` | FastAPI endpoint | Behavioral Consumer |

### Exit Criteria
- App sends behavioral event → score updates within 5s → NBA re-evaluates
- Negative sentiment on a ticker visibly drops interest_score
- Decay daemon reduces stale scores on schedule
- Attribution tracking links NBA dispatches to follow-up actions

---

## Phase 4: ML-Powered Scoring & Embeddings (3 weeks)

**Goal:** Replace rule-based scoring tiers with a trained model. Use PGVector embeddings for semantic similarity recommendations ("users who liked VNM also liked HPG").

### Step 4.1: Feature Store
- **New table:** `ml_feature_store`
  ```sql
  CREATE TABLE IF NOT EXISTS ml_feature_store (
      tenant_id UUID NOT NULL,
      profile_id TEXT NOT NULL,
      feature_vector JSONB NOT NULL,  -- {event_count_7d, unique_tickers_7d, avg_session_duration, ...}
      computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (tenant_id, profile_id)
  );
  ```
- **New service:** `services/feature_builder/`
  - Runs every 2 hours (Celery beat)
  - Aggregates from `behavioral_events` + `product_recommendations` + `cdp_profiles`
  - Outputs feature vectors: `event_count_7d`, `unique_tickers_viewed`, `avg_session_duration`, `portfolio_diversity_score`, `days_since_last_trade`

### Step 4.2: Interest Score Model Training Pipeline
- **New directory:** `ml/training/`
  - `train_interest_model.py` — trains a LightGBM/XGBoost model on historical `(feature_vector, actual_conversion)` pairs
  - Conversion = user executed `order-created` event within 7 days of score
  - Outputs: `ml/models/interest_model_v1.joblib`
  - Scheduled as monthly offline job (not real-time)

### Step 4.3: ML Scoring Consumer (replaces rule-based)
- **Modified:** `services/scoring_consumer/consumer.py`
  - Add `SCORING_MODEL` env var: `"rule_v1"` (current) or `"ml_v1"` (new)
  - When `ml_v1`: load model from disk, compute features on-the-fly, predict `interest_score` directly
  - When `rule_v1`: existing `compute_incremental_score()` logic
  - A/B test: write `recommendation_model` column as `"rule_v1"` or `"ml_v1"` — enables comparison queries

### Step 4.4: Ticker Embeddings for "Similar Tickers"
- **New table column:** `product_recommendations.ticker_embedding vector(384)`
  - Generated via `sentence-transformers` from ticker news + analyst reports
- **New endpoint:** `GET /recommendation/similar/{ticker}`
  - PGVector cosine similarity query: `ORDER BY ticker_embedding <=> query_embedding LIMIT 10`
  - Returns tickers with similar behavioral patterns

### Step 4.5: User Interest Embeddings
- **Modified:** `cdp_profiles.interest_embedding` (already exists as `vector(1536)` in schema)
  - Populate via batch job: aggregate user's behavioral events + viewed tickers → embedding
  - Enable: `GET /recommendation/discover/{profile_id}` — semantic search for tickers the user hasn't seen but would likely engage with

### Exit Criteria
- ML model outperforms rule-based scoring on conversion prediction (AUC > 0.72)
- A/B test shows measurable improvement in NBA precision
- Similar-ticker endpoint returns relevant results
- Interest embeddings populated for >80% of active profiles

---

## Phase 5: Multi-Channel Orchestration & A/B Testing (2 weeks)

**Goal:** Intelligent channel selection per user, frequency capping across channels, and built-in experimentation framework.

### Step 5.1: Channel Preference Model
- **New table:** `channel_preferences`
  ```sql
  CREATE TABLE IF NOT EXISTS channel_preferences (
      tenant_id UUID NOT NULL,
      profile_id TEXT NOT NULL,
      channel TEXT NOT NULL,
      open_rate NUMERIC(5,4) DEFAULT 0,
      click_rate NUMERIC(5,4) DEFAULT 0,
      opt_out BOOLEAN DEFAULT FALSE,
      last_engaged_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ DEFAULT NOW(),
      PRIMARY KEY (tenant_id, profile_id, channel)
  );
  ```
- **Populated by:** Feedback from `delivery_log` + behavioral events
  - Email opened → increment `open_rate` for email channel
  - Push clicked → increment `click_rate` for push channel
  - User unsubscribes → set `opt_out = TRUE`

### Step 5.2: Smart Channel Router
- **Modified:** `services/nba_publisher/publisher.py`
  - Replace static `_CHANNEL_MAP` with dynamic routing:
    1. Query `channel_preferences` for the profile
    2. Filter out `opt_out=TRUE` channels
    3. Rank remaining channels by `click_rate` (highest first)
    4. If prescriptive engine says `PUSH_NOTIFICATION` but user's push `click_rate < 0.05`, fall back to `EMAIL_DIGEST`
  - Log the routing decision for analysis

### Step 5.3: Cross-Channel Frequency Cap
- **New Redis structure:** `freq_cap:{profile_id}:{date}` → HASH of `{channel: count}`
  - Rules (configurable via env):
    - Max 1 push per day per profile
    - Max 2 emails per day per profile
    - Max 3 total across all channels per day
  - Checked in NBA Publisher before dispatch

### Step 5.4: A/B Testing Framework
- **New table:** `experiments`
  ```sql
  CREATE TABLE IF NOT EXISTS experiments (
      experiment_id TEXT PRIMARY KEY,
      tenant_id UUID NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',  -- active, paused, completed
      variant_config JSONB NOT NULL,  -- {"control": {weight: 50, ...}, "treatment": {weight: 50, ...}}
      start_at TIMESTAMPTZ NOT NULL,
      end_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- **New file:** `services/shared/experiment.py`
  - `get_variant(profile_id, experiment_id)` → deterministic hash assignment (no randomness per request)
  - NBA Publisher checks active experiments before dispatch:
    - Control group: existing behavior
    - Treatment group: modified behavior (different threshold, channel, or message)
- **New endpoint:** `GET /experiments/{experiment_id}/results`
  - Compares conversion rates between control/treatment from `delivery_log` + `behavioral_events`

### Step 5.5: Quiet Hours
- NBA Publisher checks profile timezone (from `cdp_profiles.living_city` or explicit setting)
- If current time is 22:00–08:00 in user's timezone → delay dispatch to next morning
- Delayed messages queued via Kafka with scheduled delivery (Kafka timestamp or Redis sorted set)

### Exit Criteria
- Channel routing adapts based on historical engagement
- Frequency cap prevents over-messaging
- A/B test runs with measurable variant assignment
- Quiet hours respected for push/email channels

---

## Phase 6: Graph-Enhanced Recommendations (2 weeks)

**Goal:** Leverage ArangoDB's graph and PostgreSQL AGE (Apache Graph Extension, already installed) for social-signal and relationship-aware recommendations.

### Step 6.1: Social Influence Graph
- **Apache AGE graph:** `leo_social_graph`
  ```sql
  SELECT create_graph('leo_social_graph');
  -- Nodes: profiles
  -- Edges: FOLLOWS, COPIES_TRADES, SAME_SEGMENT
  ```
- **Populated by:**
  - `cdp_profiles.segments` → `SAME_SEGMENT` edges between profiles sharing segments
  - Behavioral events: if profile A and B both trade the same tickers within 24h → `SIMILAR_BEHAVIOR` edge with weight
  - Explicit social data from CDP (if available): `FOLLOWS` edges

### Step 6.2: Social Signal Scoring
- **New function:** `compute_social_score(profile_id, ticker)`
  - Cypher query via AGE:
    ```sql
    SELECT * FROM cypher('leo_social_graph', $$
      MATCH (me:Profile {id: $profile_id})-[:SIMILAR_BEHAVIOR|SAME_SEGMENT*1..2]-(peer:Profile)
      WITH peer
      MATCH (peer)-[:INTERESTED_IN]->(t:Ticker {symbol: $ticker})
      RETURN count(peer) as peer_count, avg(peer.interest_score) as avg_peer_score
    $$) as (peer_count agtype, avg_peer_score agtype);
    ```
  - Social score = `peer_count * avg_peer_score * SOCIAL_WEIGHT` (configurable, default 0.15)
- **Modified:** Scoring Consumer adds social score as a boost factor:
  - `final_score = interest_score * (1 + social_score)` (capped at 1.0)

### Step 6.3: "Trending in Your Network" Endpoint
- **New endpoint:** `GET /recommendation/network-trending/{profile_id}`
  - Returns top 10 tickers that the user's 2-hop network is engaging with
  - Excludes tickers the user already has high interest in (avoid redundancy)
  - Powered by AGE graph traversal

### Step 6.4: Graph-Aware NBA
- **Modified:** NBA Publisher
  - New NBA action: `SOCIAL_PROOF_NUDGE`
  - Trigger: when >3 peers in user's network engage with a ticker the user viewed once (score 0.1-0.5)
  - Message: "5 investors in your network are watching VNM this week"
  - Channel: IN_APP_BANNER or PUSH_NOTIFICATION

### Step 6.5: Graph Maintenance
- **New Celery task:** `rebuild_social_graph` — runs daily
  - Rebuilds edges from latest segment memberships and behavioral co-occurrences
  - Prunes edges older than 30 days
  - Updates edge weights based on recency

### Exit Criteria
- Social graph populated with >1000 edges for test tenant
- Social score visibly boosts recommendations for connected users
- Network-trending endpoint returns meaningful results
- SOCIAL_PROOF_NUDGE dispatches for qualifying users

---

## Phase 7: Portfolio-Aware Intelligence & Advisory (3 weeks)

**Goal:** Integrate portfolio data (already in `cdp_profiles.portfolio_snapshot`) into the recommendation engine for context-aware advice — not just "what are they interested in" but "what should they actually do given their portfolio."

### Step 7.1: Portfolio Risk Scoring
- **New file:** `agentic_tools/recommendation_system/portfolio_engine.py`
  - `compute_portfolio_risk(portfolio_snapshot)` → `portfolio_risk_score` (0.0-1.0)
    - Factors: concentration risk (single stock >30%), sector overlap, cash ratio, unrealized P&L
  - **Celery task:** runs daily, updates `cdp_profiles.portfolio_risk_score` and `portfolio_last_evaluated_at`

### Step 7.2: Context-Aware Prescriptive Engine
- **Modified:** `prescriptive_engine.py`
  - Add portfolio context to `recommend_system_action()`:
    ```python
    def recommend_system_action(score, predicted_event, portfolio_context=None):
    ```
  - New rules:
    - If user has `interest_score > 0.7` for VNM **and already holds VNM** → `TAKE_PROFIT_ALERT` instead of `STRONG_BUY_ALERT`
    - If user has high interest in a stock **but portfolio_risk_score > 0.8** → `RISK_WARNING` instead of buy nudge
    - If user has `cash_available > threshold` and high interest → `OPPORTUNITY_ALERT` (more aggressive)

### Step 7.3: Portfolio-Ticker Conflict Detection
- **New file:** `agentic_tools/recommendation_system/conflict_detector.py`
  - `detect_conflicts(profile_id, ticker, action)` → list of conflicts
  - Conflicts:
    - Already holding same ticker at a loss → don't push "BUY MORE"
    - Sector over-concentration → add risk disclaimer
    - Conflicting recommendations (buy ticker A + sell sector that includes A)
  - NBA Publisher checks conflicts before dispatch, adds disclaimer or suppresses

### Step 7.4: Personalized Advisory Digest
- **New Celery task:** `weekly_advisory_digest`
  - Runs weekly (Sunday 10:00 VN time)
  - For each active user with portfolio data:
    1. Top 3 tickers by interest_score that they DON'T hold → "Opportunities"
    2. Held positions with declining interest across the network → "Watch List"
    3. Portfolio risk assessment summary
  - Dispatched via email (using existing `EmailChannel`)
  - Template stored in `agentic_tools/channels/templates/email/advisory_digest.html`

### Step 7.5: Real-Time Position Change Detection
- **New CDC filter** in `services/cdc_poller/filters.py`:
  - Also watch for `cdp_profile` updates where `portfolio_snapshot` changed
  - Publish to new topic `cdp.portfolio.changes`
- **New consumer:** `services/portfolio_consumer/consumer.py`
  - When user's position changes (bought/sold):
    - Recalculate portfolio risk score
    - If user just bought a ticker they had high interest in → mark as "converted", update NBA columns
    - If user just sold → adjust interest score downward (configurable decay)
    - Publish to `leo.score.updates` to trigger NBA re-evaluation

### Step 7.6: Advisory API Endpoints
- **New endpoints in** `api/recommendation_system.py`:
  - `GET /recommendation/advisory/{profile_id}` — returns portfolio-aware recommendations
    - Combines: interest scores + portfolio positions + risk assessment + conflicts
  - `GET /recommendation/portfolio-risk/{profile_id}` — returns risk score breakdown

### New Kafka Topics
| Topic | Producer | Consumer |
|---|---|---|
| `cdp.portfolio.changes` | CDC Poller | Portfolio Consumer |

### Exit Criteria
- Portfolio risk scores computed for all profiles with portfolio data
- Prescriptive engine outputs different actions based on portfolio context
- Conflict detector prevents contradictory recommendations
- Weekly advisory digest sent with portfolio-aware content
- Position changes trigger real-time score adjustments

---

## Timeline Summary

| Phase | Name | Duration | Dependencies |
|---|---|---|---|
| **Phase 1** | CDC Pipeline (DONE) | 4 weeks | — |
| **Phase 2** | Hardening & Observability | 1 week | Phase 1 |
| **Phase 3** | Behavioral Feedback Loop | 2 weeks | Phase 2 |
| **Phase 4** | ML Scoring & Embeddings | 3 weeks | Phase 3 |
| **Phase 5** | Multi-Channel & A/B Testing | 2 weeks | Phase 2 |
| **Phase 6** | Graph Recommendations | 2 weeks | Phase 3, Phase 5 |
| **Phase 7** | Portfolio Intelligence | 3 weeks | Phase 4, Phase 6 |

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 7
                  │                                  ▲
                  └──► Phase 5 ──► Phase 6 ──────────┘
```

**Phases 3+5 can run in parallel** after Phase 2 is complete.
**Phase 7 is the capstone** — requires ML scoring + graph signals + portfolio data.

---

## Cumulative New Infrastructure

| Component | Introduced In | Purpose |
|---|---|---|
| Kafka + Zookeeper | Phase 1 | Event streaming backbone |
| CDC Poller | Phase 1 | ArangoDB WAL → Kafka |
| Scoring Consumer | Phase 1 | Real-time interest scoring |
| NBA Publisher | Phase 1 | Channel dispatch orchestration |
| Prometheus + Grafana | Phase 2 | Observability |
| DLQ Consumer | Phase 2 | Error recovery |
| Behavioral Event API | Phase 3 | App feedback ingestion |
| Behavioral Consumer | Phase 3 | Feedback → scoring |
| Decay Daemon | Phase 3 | Stale score cleanup |
| Feature Builder | Phase 4 | ML feature aggregation |
| ML Training Pipeline | Phase 4 | Offline model training |
| A/B Framework | Phase 5 | Experimentation |
| Apache AGE Graph | Phase 6 | Social signals |
| Portfolio Consumer | Phase 7 | Position-aware scoring |

---

## Cumulative Kafka Topics

| Topic | Phase | Partition Key |
|---|---|---|
| `cdp.events.raw` | 1 | ticker |
| `leo.score.updates` | 1 | `{profile_id}:{ticker}` |
| `leo.nba.actions` | 1 | `{profile_id}:{ticker}` |
| `leo.dlq` | 1 | — |
| `cdp.events.behavioral` | 3 | `{profile_id}` |
| `cdp.portfolio.changes` | 7 | `{profile_id}` |
