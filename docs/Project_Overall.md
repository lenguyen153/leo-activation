# LEO Activation - Project Overview

## 1. The Big Picture

**What:** LEO Activation is an agentic backend framework for AI-driven marketing automation. It bridges Customer Data Platforms (CDPs) and marketing execution channels using an LLM-powered agent loop.

**Core design rule:** LLMs decide *what to do*. Graphs decide *what is true*. Tools do the work. LLMs never touch the database directly — all access is mediated through a tool registry.

**Who are the users:**
- Marketing teams at B2B/B2C companies using LEO CDP
- Internal data teams managing customer segments, campaigns, and alerts
- The system itself acts as an autonomous agent — users interact via a `/chat` endpoint or direct `/tool_calling` API

**What it does:**
- Receives natural language queries → routes to the right tool via a small function-calling model → executes deterministic actions → returns synthesized responses
- Syncs customer profiles and behavioral events from ArangoDB (source CDP) into PostgreSQL; backfills event history on demand
- Scores customer interest in real-time via a CDC pipeline (Kafka); reconciles batch scores on schedule
- Activates marketing campaigns across Email, Zalo OA, Facebook, Mobile Push, Web Push
- Runs a rule-based campaign engine on cron schedules with frequency capping, circuit-breaker protection, and immediate-send override
- Provides next-best-action (NBA) recommendations and next-likely-action (NLA) predictions (XGBoost model) per profile
- Polls market snapshots from Redis into PostgreSQL and computes volume analytics for ticker-level affinity scoring
- Builds and maintains PGVector embeddings for semantic (RAG) agent reasoning
- Serves a React dashboard (AudienceHub, Audience360, CampaignEngine, ProfileDetail, TickerProfiles, SegmentProfiles, SearchResults)

---

## 2. Tech Stack

**Language:** Python 3.10+

**Web Framework:** FastAPI (ASGI, served via Uvicorn)

**Databases:**
- PostgreSQL 16+ (primary) — with extensions: Apache AGE (graph), PGVector (embeddings), PostGIS (geo), pgcrypto, citext
- ArangoDB — upstream CDP source (graph + document), synced to PG via Celery
- Redis 7 — caching, Celery broker, ephemeral state

**AI / ML:**
- `google/functiongemma-270m-it` (HuggingFace Transformers + PyTorch) — intent & tool routing only
- Google Gemini (`google-genai` SDK, default model: `gemini-2.5-flash-lite`) — synthesis / natural language responses
- OpenAI SDK — available as alternate LLM provider
- `sentence-transformers` — 1536-dim embeddings for PGVector semantic search

**Task Queue:** Celery with Redis broker (worker + beat for cron jobs); supports `CELERY_CDC_ONLY` mode that disables all non-CDC tasks for isolated scoring pipelines

**Event Streaming:** Confluent Kafka (CDC poller → scoring consumer → NBA publisher)

**Key Libraries:**
- `pydantic` / `pydantic-settings` — data validation & config
- `sqlalchemy` — ORM / schema management
- `psycopg` v3 — async PostgreSQL driver
- `python-arango` — ArangoDB driver
- `structlog` — structured JSON logging
- `prometheus-client` / `prometheus-fastapi-instrumentator` — metrics & observability

**Frontend:** React 18 + Vite SPA (`leo-dashboard/`) — served via Nginx; pages: AudienceHub, Audience360, CampaignEngine, ProfileDetail, TickerProfiles, SegmentProfiles, SearchResults

**Infrastructure:** Docker Compose (API, Redis, Celery worker/beat, Ngrok tunnel, Kafka/Zookeeper, CDC microservices); `docker-compose.prod.cdc.yml` for CDC-only deployments

---

## 3. Architecture & File Structure

### Four-Step Agent Loop
1. **Intent & Tool Selection** (`agentic_models/function_gemma.py`) — FunctionGemma 270M generates schema-bound function calls
2. **Tool Execution** (`agentic_tools/`) — deterministic execution against DBs/APIs, no LLM
3. **Synthesis** (`agentic_models/router.py`) — Gemini explains results in natural language
4. **Response** — returns `{"answer": "...", "debug": {"calls": [...], "data": [...]}}`

### Three-Database Architecture
| System | Tech | Purpose |
|---|---|---|
| System of Truth | PostgreSQL + Apache AGE | Customer graph, segments, behavioral edges (Cypher over PG) |
| System of Meaning | PostgreSQL + PGVector | Semantic embeddings for RAG agent reasoning |
| Source CDP | ArangoDB | Upstream customer data; synced to PG via Celery |

### Directory Structure
```
leo-activation/
├── main.py / main_app.py        # Uvicorn entry points
├── main_configs.py              # All env-based configuration
├── api/                         # FastAPI app factory + route handlers
│   ├── app_factory.py
│   ├── handlers.py              # Core endpoints (/chat, /tool_calling, /data/sync-segment, /test/zalo-direct)
│   ├── recommendation_system.py # /recommendation/* routes
│   ├── audience.py              # /audience/* segment routes
│   ├── campaign_rules.py        # /campaigns/rules CRUD + preview + runs + affected + send
│   ├── notification.py          # /notification/send
│   ├── portfolio.py             # /portfolio/user + /portfolio/accounts
│   └── user_events.py           # /user-events/* routes
├── agentic_models/              # LLM integration layer
│   ├── function_gemma.py        # FunctionGemma 270M (tool routing)
│   ├── gemini.py                # Gemini SDK wrapper
│   └── router.py                # AgentRouter — orchestrates the 4-step loop
├── agentic_tools/               # Tool registry & execution
│   ├── tools.py                 # Registered tools (explicit, no hidden prompts)
│   ├── channels/                # Strategy pattern: email, zalo, facebook, push
│   │   └── templates/           # Per-channel message templates (email/stock_picks, zalo/stock_picks, zalo/suggested_stock)
│   ├── recommendation_system/   # Interest scoring, predictive/prescriptive engines
│   ├── recommendation_orchestrator.py  # Orchestrates NBA/NLA/interest-score pipelines
│   └── *.py                     # Domain tools (customer, marketing, alerts, weather, data_enrichment)
├── data_models/                 # SQLAlchemy ORM models & Pydantic schemas
├── data_utils/                  # DB connection factory & settings
├── agentic_resources/           # Static files and Jinja2 web templates (served at /resources)
├── data_services/               # Business logic services (alerts)
├── data_workers/                # Celery tasks and background workers
│   ├── tasks.py                 # All registered Celery tasks
│   ├── campaign_engine/         # Rule-based campaign engine (circuit breaker, condition evaluator, dispatcher, frequency cap)
│   ├── repositories/            # Data-access layer (arango_profile_repository, pg_profile_repository)
│   ├── scripts/                 # One-off / maintenance scripts (backfill, batch scoring, abandoned cart, embedding, market snapshot, behavioral events, etc.)
│   └── sync/                    # Profile & portfolio sync services (arango-to-PG, segment, active-user portfolios)
├── services/                    # CDC microservices (independent containers)
│   ├── cdc_poller/              # Polls ArangoDB for changes → Kafka
│   ├── scoring_consumer/        # Consumes Kafka → computes scores → PG
│   ├── nba_publisher/           # Next-Best-Action publisher
│   ├── ws_forwarder/            # WebSocket forwarder — streams CDC events to external services
│   └── shared/                  # Shared Kafka utils & schemas
├── leo-dashboard/               # React 18 + Vite frontend SPA (served via Nginx)
│   └── src/
│       ├── pages/               # AudienceHub, Audience360, CampaignEngine, ProfileDetail, TickerProfiles, SegmentProfiles, SearchResults
│       ├── components/          # audience/, campaign/, chatbot/, layout/, ui/ components
│       └── api/                 # API client modules (campaign, chat, profile, pulse)
├── nla_model/                   # Next-Likely-Action XGBoost model pipeline
│   ├── scripts/                 # build_df_train.py, train_nla.py, eda_propensity.py
│   ├── output/                  # Trained model artifact (nla_model.json) + EDA charts
│   └── docs/                    # EDA reports (EDA_XGBoost_Report.md)
├── sql-scripts/                 # DDL schema, test data, use cases
├── shell-scripts/               # Dev/prod startup scripts
├── tests/                       # Pytest test suites
├── docs/                        # Architecture, DB, tools reference docs
├── docker-compose.yml           # Full stack: API, Redis, Celery, Kafka, CDC services
└── docker-compose.prod.cdc.yml  # CDC-only production compose
```

### Key API Endpoints
- `GET /ping` — Health check
- `POST /chat` — Main agentic interface (natural language → tool → response)
- `POST /tool_calling` — Direct tool invocation (bypasses agent)
- `POST /data/sync-segment` — Trigger profile sync from ArangoDB
- `POST /test/zalo-direct` — Test Zalo OA direct message send (dev/debug)
- `GET /recommendation/interested/{ticker}` — Users interested in a ticker (default env)
- `GET /recommendation/interested-prod/{ticker}` — Users interested in a ticker (prod env)
- `GET /recommendation/interested-uat/{ticker}` — Users interested in a ticker (UAT env)
- `GET /recommendation/profile_affinity/{profile_id}` — 360° profile interest view
- `GET /recommendation/nba/{profile_id}` — Next-best-action recommendations
- `GET /recommendation/nla/{profile_id}` — Next-likely-action predictions
- `GET /recommendation/segment-profiles` — Profiles for a given segment
- `POST /recommendation/webhook/zalo` — Zalo OA webhook receiver
- `GET /audience/high-affinity` — High-affinity customer profiles
- `GET /audience/churn-risk` — Profiles with churn-risk signals
- `GET /audience/new-investors` — New investor profiles
- `GET /audience/active-traders` — Active trader profiles
- `GET /portfolio/user` — User portfolio data
- `GET /portfolio/accounts` — Account-level portfolio data
- `POST /notification/send` — Send a notification via configured channel
- `GET /user-events/top` — Top-K events for a profile
- `GET /user-events/top-range` — Top-K events within a date range
- `GET /user-events/metric-timestamps` — Event metric timestamps (with optional `instrument_id` filter)
- `POST /campaigns/rules` — Create campaign rule
- `GET /campaigns/rules` / `GET /campaigns/rules/{rule_id}` — List / fetch rules
- `PUT /campaigns/rules/{rule_id}` — Update rule
- `PATCH /campaigns/rules/{rule_id}/status` — Enable / disable rule
- `GET /campaigns/rules/{rule_id}/runs` — Execution history for a rule
- `GET /campaigns/runs` — List all campaign run history (across all rules)
- `POST /campaigns/rules/{rule_id}/preview` — Dry-run a rule against audience
- `GET /campaigns/rules/{rule_id}/affected` — List profiles that will be targeted by a rule
- `POST /campaigns/rules/{rule_id}/send` — Trigger immediate send for a rule (bypasses schedule)

---

## 4. Hard Rules & Conventions

### Architecture Rules
- **SLON principles:** Simplicity, Lean, One thing, No over-engineering
- LLMs NEVER touch the database directly — all DB access through the tool registry
- FunctionGemma (`google/functiongemma-270m-it`) is ONLY for tool routing, never for synthesis
- Gemini handles synthesis only — it has NO authority over data
- All tools must be explicitly registered in `agentic_tools/tools.py` — no hidden prompt magic
- Tool execution must be deterministic against databases/APIs (no LLM involvement)
- Channel implementations (`agentic_tools/channels/`) follow the strategy pattern

### Coding Standards
- Python 3.10+, type hints encouraged
- Pydantic for all data validation and settings
- Environment variables loaded via `python-dotenv`, centralized in `main_configs.py`
- Fail-fast on invalid config (RuntimeError on bad env parsing)
- Row-Level Security (RLS) on PostgreSQL tables for multi-tenancy
- Structured logging via `structlog` (JSON format for observability)

### Testing
- Framework: `pytest` (config in `pytest.ini`)
- Run: `pytest tests/ -v --log-cli-level=DEBUG`
- Tests live in `tests/` and `data_models/tests/`

### Running the Project
- Dev: `bash shell-scripts/start-dev.sh`
- Production: `bash shell-scripts/start-production.sh`
- Celery worker: `celery -A data_workers.celery_app worker --loglevel=info`
- Full stack: `docker compose up`
