### Four-Step Agent Loop

1. **Intent & Tool Selection (FunctionGemma 270M)** — `agentic_models/` — Small model (`google/functiongemma-270m-it`) generates strict, schema-bound function calls. Used only for tool routing, never for synthesis.
2. **Tool Execution (Backend Turn)** — `agentic_tools/` — Deterministic execution against databases and external APIs. No LLM involvement.
3. **Synthesis (Gemini)** — `agentic_models/router.py` — Gemini explains results in natural language. It has no authority over data.
4. **Response** — Returns `{"answer": "...", "debug": {"calls": [...], "data": [...]}}`.

The `AgentRouter` in `agentic_models/router.py` orchestrates this loop. It is the runtime nucleus for all `/chat` and `/tool_calling` API calls.

### Background Workers (`data_workers/`)

Celery tasks:
- **Profile sync**: Incremental checkpoint-based sync from ArangoDB (default cron: `*/5 * * * *`)
- **Embeddings**: Generate `sentence-transformers` vectors (1536 dims) stored in PGVector
- **Recommendation engine**: Interest scoring, next-best-action, product recommendations
- **Campaign engine** (`data_workers/campaign_engine/`): Rule-based campaign runner — evaluates cron-scheduled rules against audience segments and dispatches via channels with circuit-breaker and frequency-cap guards

Sub-packages:
- `repositories/` — `arango_profile_repository.py` + `pg_profile_repository.py` (data-access layer)
- `campaign_engine/` — `engine.py`, `condition_evaluator.py`, `dispatcher.py`, `circuit_breaker.py`, `frequency_cap.py`
- `scripts/` — one-off maintenance scripts (backfill, batch scoring, abandoned cart, market snapshot, etc.)
- `sync/` — profile & portfolio sync services

### API Layer (`api/`, `main_app.py`)

Routes are split across dedicated router files (all included in `handlers.py::create_api_router`):

| File | Prefix | Key endpoints |
|---|---|---|
| `handlers.py` | — | `POST /chat`, `POST /tool_calling`, `POST /data/sync-segment` |
| `recommendation_system.py` | `/recommendation` | `interested/{ticker}`, `interested-prod/{ticker}`, `interested-uat/{ticker}`, `profile_affinity/{id}`, `nba/{id}`, `nla/{id}`, `segment-profiles`, `webhook/zalo` |
| `audience.py` | `/audience` | `high-affinity`, `churn-risk`, `new-investors`, `active-traders` |
| `campaign_rules.py` | `/campaigns` | `rules` CRUD, `rules/{id}/status`, `rules/{id}/runs`, `rules/{id}/preview` |
| `user_events.py` | `/user-events` | `top`, `top-range`, `metric-timestamps` |
| `portfolio.py` | `/portfolio` | `user`, `accounts` |
| `notification.py` | `/notification` | `send` |

### Frontend Dashboard (`leo-dashboard/`)

React 18 + Vite SPA served via Nginx. Pages:
- **AudienceHub / Audience360** — segment browser and 360° profile view (affinity chart, event timeline, NBA list)
- **CampaignEngine** — rule builder with channel selector and preview results
- **ProfileDetail / TickerProfiles / SegmentProfiles / SearchResults** — drill-down views

API clients in `src/api/` call the FastAPI backend; `src/data/` holds mock data for dev.

### NLA Model (`nla_model/`)

Offline XGBoost training pipeline for Next-Likely-Action prediction:
- `scripts/build_df_train.py` — feature engineering from behavioral events
- `scripts/train_nla.py` — XGBoost model training → `output/nla_model.json`
- `scripts/eda_propensity.py` — EDA and class-imbalance analysis
- See `nla_model/docs/EDA_XGBoost_Report.md` for current model status and pre-training checklist