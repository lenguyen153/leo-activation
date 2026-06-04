# Project Overall — AI Agent System (Leo Activation)

**Project Name:** AI Stock & Finance Agent System  
**Codename:** Leo Activation  
**Owner:** Innotech / AIPower  
**Branch:** deploy_ver3  
**Last Updated:** 2026-05-14  

---

## 1. Executive Summary

Leo Activation is a production-grade, multi-agent AI platform for the Vietnamese stock market. It provides a conversational API where users can ask natural-language questions in Vietnamese and receive intelligent, data-grounded responses about stocks, financial reports, market movements, news, and trade actions.

The platform is built around **Agentic AI** design principles: an orchestrating Host Agent interprets user intent, routes structured tasks to domain-specialist sub-agents, and each sub-agent autonomously calls financial data tools (via MCP) to ground its responses in live market data. The result is a system that reasons, retrieves, synthesises, and acts — without requiring manual query-routing or hand-coded logic per query type.

**Target domain:** Vietnamese retail investors and financial advisors interacting via a mobile/web chat interface, covering all three national exchanges (HOSE, HNX, UPCOM).

---

## 2. High-Level Architecture

```
Client / Frontend
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│                 Main App Server (FastAPI :5678)                   │
│  - API gateway, authentication                                    │
│  - Report generation & file serving (PDF/HTML)                   │
│  - Image proxy (MinIO)                                            │
│  - Training data management API                                   │
└──────────────────────┬────────────────────────────────────────────┘
                       │ spawns
                       ▼
┌───────────────────────────────────────────────────────────────────┐
│                 Host Agent  (Orchestrator)                        │
│  Framework: Google ADK  |  LLM: Gemini 2.5-flash via LiteLLM    │
│                                                                   │
│  Responsibilities:                                                │
│   1. Classify intent (business vs. small-talk)                   │
│   2. Build StructuredTaskPayload (intent + params + context)     │
│   3. Check Qdrant semantic task cache (score ≥ 0.80 = HIT)       │
│   4. Route to the correct sub-agent via A2A                      │
│   5. Store result in cache (background)                          │
│   6. Post-process & return structured response                   │
└──────┬────┬────┬────┬────┬─────────────────────────────────────┘
       │    │    │    │    │   A2A (HTTP JSON) per agent
       ▼    ▼    ▼    ▼    ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │                    Sub-Agent Layer                               │
 │                                                                  │
 │  Securities Advisor :10001   │  Analyst News    :10004          │
 │  Customer Support   :10002   │  Render Chart    :10005          │
 │  Vision             :10003   │  Action          :10006          │
 │                                                                  │
 │  Each agent: Google ADK LlmAgent + MCP tools + Redis sessions   │
 └────────────────────────────┬─────────────────────────────────────┘
                              │ MCP / SSE tool calls
                              ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │                   MCP Server  (:8889)                            │
 │  FastMCP + Starlette + SSE transport                             │
 │                                                                  │
 │  Domain modules:                                                 │
 │   financial_ratios/   → 6 ratio groups (banking, profitability…) │
 │   technical_indicators/ → 9 TA indicators (MA, RSI, MACD…)      │
 │   statistic_agent/    → query engine, metric registry           │
 │   realtime_market/    → live price & volume                     │
 │   final_chart/        → chart key generation                    │
 │   services/           → company, market, ranking, recommend      │
 │   services/news/      → Qdrant news retrieval                   │
 │   services/portfolio/ → portfolio analytics                     │
 └────────────────────────────┬─────────────────────────────────────┘
                              │  queries
           ┌──────────────────┼────────────────────────────────┐
           ▼                  ▼                                ▼
     PostgreSQL            MongoDB                   Vector Databases
     (market history,      (conversations,           Qdrant  :6333
      financials,          training, market          Weaviate :8082
      symbols, TA)         messages, notif)
           │                                                    │
           └──── Redis :6379  (sessions, cache) ───────────────┘
                 MinIO  :9000  (images, reports)
```

---

## 3. Service Inventory

| Service | Port | Role | LLM Model |
|---------|------|------|-----------|
| Main App Server | 5678 | API gateway, reports | — |
| Securities Advisor Agent | 10001 | Stock & financial analysis | gemini-2.0-flash |
| Customer Support Agent | 10002 | ACBS FAQ & service info | gemini-2.0-flash |
| Vision Agent | 10003 | Image / screenshot analysis | gemini-2.0-flash |
| Analyst News Agent | 10004 | News retrieval & macro analysis | gemini-2.0-flash |
| Render Chart Agent | 10005 | Chart key generation & rendering | gemini-2.0-flash |
| Action Agent | 10006 | UI workflow execution | gemini-2.0-flash |
| MCP Server | 8889 | Financial data tools (MCP/SSE) | — |
| Redis | 6379 | Session store, chart key cache | — |
| MinIO | 9000/9001 | Object store (images, reports) | — |
| Qdrant | 6333 | Semantic task cache + news vectors | — |
| Weaviate | 8082 | Hybrid search knowledge base | — |

---

## 4. Technology Stack

### Runtime & Framework
| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Package manager | `uv` (ultraviolet) |
| ASGI server | uvicorn |
| Web framework | FastAPI (main app, sub-agents), Starlette (MCP server) |
| Data validation | Pydantic v2 |
| Async I/O | asyncio, asyncpg, motor (async MongoDB) |

### AI / LLM Layer
| Component | Technology |
|-----------|-----------|
| Agent framework | **Google ADK** (`google-adk`) — lifecycle, sessions, runners |
| LLM (sub-agents) | Google Gemini 2.0-flash |
| LLM (orchestrator) | Google Gemini 2.5-flash |
| LLM proxy | **LiteLLM** (`localhost:4000`) — decouples model routing from agent code |
| Tool protocol | **MCP** (Model Context Protocol) over SSE |
| Agent protocol | **A2A** (Agent-to-Agent) — HTTP JSON RPC for inter-agent calls |
| API key strategy | Pool rotation — random key per request across `AGENT_API_KEY_LIST` / `HOST_API_KEY_LIST` |

### Embedding & Vector Search
| Component | Technology |
|-----------|-----------|
| Dense embeddings | Jina Embeddings v5 Text Small (1024-dim), served locally at `118.69.83.26:7997` |
| Dense embeddings (news) | ZeroEntropy zembed-1 (2560-dim), same local endpoint |
| Sparse embeddings | BM25 via `fastembed` (`Qdrant/bm25`) |
| Matryoshka (fast path) | MRL-256 (first 256 dims of dense vector) |
| Vector DB | Qdrant (task cache + news), Weaviate (ACBS knowledge base) |
| Search strategy | Hybrid: dense cosine + BM25 sparse, fused via RRF |

### Data Stores
| DB | Purpose |
|----|---------|
| **PostgreSQL** | Historical quotes (`aip_symbol_historical_quotes`), financial statements, industry data, technical pre-computed (`aip_stock_watchlist_tcbs`), recommendations |
| **MongoDB** | Conversations, training prompts, notification payload, user personalization (`ai_personalization`), market messages |
| **Redis** | MCP session state, ADK session bridging across workers, chart key cache, real-time market cache |
| **MinIO** | Generated report PDFs, chart PNGs, user-uploaded images |
| **Qdrant** | Semantic task result cache (`agent_task_cache_jina`), news embeddings (`news_v2`) |
| **Weaviate** | ACBS company knowledge base (hybrid vector search) |

### Infrastructure
- **Docker Compose** — all services containerized, shared bridge networks
- Single monorepo `Dockerfile` builds all agents from the same image
- MCP server has a dedicated `Dockerfile` under `agent-data-api/`

---

## 5. Repository Structure

```
agent-system/
├── main.py                            # FastAPI gateway (API entry point)
├── docker-compose.yml
├── Dockerfile                         # Shared image for all agents
│
├── config/
│   ├── settings.py                    # Global settings + API key pool
│   └── logging_config.py
│
├── agents/                            # All AI agent implementations
│   ├── hosts_agent_adk/
│   │   └── multiagent/
│   │       ├── host_agent.py          # Orchestrator (routes, caches, dispatches)
│   │       ├── remote_agent_connection.py  # A2A client
│   │       ├── template_prompt.py     # Dynamic system prompt (intent table, date)
│   │       └── formatter_subagent.py  # Sub-agent for post-formatting
│   ├── securities_advisor_agent_adk/  # Core stock analysis agent
│   ├── customer_support_agent_adk/    # ACBS FAQ agent
│   ├── vision_agent_adk/              # Image understanding agent
│   ├── analyst_news_agent_adk/        # News & macro agent
│   ├── render_chart_agent/            # Chart rendering agent
│   └── action_agent/                  # UI action agent
│
├── agent-data-api/                    # MCP Server (standalone microservice)
│   ├── main.py                        # FastMCP + tool registration
│   ├── financial_ratios/              # 6 ratio domain modules
│   │   ├── banking/                   # NIM, NPL, LDR, CIR (bank-specific)
│   │   ├── profitability/             # ROE, ROA, DuPont decomposition
│   │   ├── efficiency/                # Turnover ratios, CCC
│   │   ├── valuation/                 # P/E, P/B, EV/EBITDA
│   │   ├── cash_flow/                 # CFO, CFI, CFF, FCF quality
│   │   └── fundamental_health/        # Solvency, liquidity, interest coverage
│   ├── technical_indicators/          # 9 TA indicators + funnel logic
│   │   ├── indicator_calculator.py    # Core TA engine (pandas/numpy)
│   │   ├── tech_scoring_service.py    # Non-linear scoring (sigmoid, tanh, log)
│   │   ├── ma/, rsi/, macd/, bb/      # Per-indicator MD knowledge files
│   │   ├── stoch/, atr/, obv/, adx/
│   │   └── funnel_logic.md            # Use-case → indicator mapping guide
│   ├── statistic_agent/               # Structured query engine
│   │   ├── analyze_stock_comparison.py
│   │   ├── build_query/               # SQL query builder + Redis realtime path
│   │   ├── metrics/                   # Metric registry, dataset registry
│   │   └── schema/                    # analysisInput Pydantic schema
│   ├── realtime_market/               # Live market data
│   │   └── get_realtime_market.py
│   ├── final_chart/                   # Chart key generation
│   │   ├── chart_logic_key.md         # Chart parameter reference
│   │   └── key_mapping.py
│   ├── services/
│   │   ├── company_service.py         # Company profile, dividends
│   │   ├── financial_service.py       # Financial statements, ratio comparison
│   │   ├── market_service.py          # Market summary (symbol/index/industry)
│   │   ├── technical_service.py       # Pre-computed TA from PostgreSQL
│   │   ├── ranking_service.py         # Screener / market ranking
│   │   ├── recommend_service.py       # Stock recommendations
│   │   ├── vectordb_query.py          # Weaviate hybrid search (ACBS KB)
│   │   ├── news/
│   │   │   ├── emdedding_news.py      # Qdrant news upsert + multi-vector
│   │   │   └── retrivel_news.py       # News retrieval
│   │   └── portfolio/                 # Portfolio analytics
│   ├── database/
│   │   ├── initPostgres.py            # asyncpg pool manager
│   │   ├── initMongo.py               # Motor (async) MongoDB manager
│   │   └── initRedis.py               # Redis cache manager
│   └── session_manager.py             # Redis-backed MCP session manager
│
├── common/
│   ├── task_cache_service.py          # Qdrant semantic cache (TaskCacheService)
│   ├── structured_task_models.py      # StructuredTaskPayload, intent constants, TTL rules
│   └── types.py                       # A2A protocol types
│
├── app/
│   ├── state/host_agent_service.py    # Global host agent singleton
│   └── service/server/               # ADK runner management, Redis session cache
│
├── ai_stock_and_finace/               # Report generation + training API
│   └── app/
│       ├── routes/reports.py          # Report endpoints
│       ├── routes/training.py         # Training data endpoints
│       └── services/mongodb_service.py
│
├── utils/
│   └── util.py                        # VN date utils, holiday calendar, trading session check
│
└── base/
    └── singleton.py                   # BaseSingleton (thread-safe, shared state)
```

---

## 6. Agentic AI Design

This is the core of the system. The platform is built using **multi-agent orchestration** — a set of collaborating AI agents, each with a defined scope, connected via standardised protocols.

### 6.1 Agentic Patterns in Use

| Pattern | Where Used | What It Does |
|---------|-----------|--------------|
| **Orchestrator / Planner** | Host Agent | Classifies intent, builds structured task, routes to sub-agents |
| **Tool Use / Function Calling** | All sub-agents | Call MCP tools to ground responses in live data |
| **Retrieval-Augmented Generation (RAG)** | Analyst News, Customer Support | Pull news from Qdrant or ACBS docs from Weaviate before generating |
| **Structured Output** | Host Agent → sub-agents | JSON `StructuredTaskPayload` instead of raw NLP for robust parsing |
| **Semantic Caching** | Host Agent | Skip LLM + tool calls when a semantically similar query was answered recently |
| **Context Injection** | Securities Advisor | Inject notification context + user persona before every LLM call |
| **Callback Hooks** | All agents | `before_model_callback` / `after_model_callback` for key rotation, grounding metadata post-processing |
| **Streaming** | Securities Advisor | SSE event streaming with per-tool progress updates to client |
| **Parallel Task Dispatch** | Host Agent (`multi_send_task`) | `asyncio.gather` to fan-out to multiple agents simultaneously |

---

### 6.2 Host Agent — Orchestrator in Detail

The Host Agent is an **intent router and coordinator**. It does not do domain work itself — it reasons about *who* should handle the query.

**System prompt structure:**
- Current VN date + trading calendar (injected dynamically per request)
- Holiday detection (VN public holiday + weekend awareness)
- Intent routing table: maps user intent codes to target agents and required parameters
- 7 intent categories × 6 agents, with examples for few-shot guidance

**Intent taxonomy (from `template_prompt.py` + `structured_task_models.py`):**

| Agent | Intent | Parameters |
|-------|--------|-----------|
| Securities Advisor | `analyze_stock_technical` | `symbol`, `timeframe?` |
| Securities Advisor | `analyze_financial_report` | `symbol`, `quarter?`, `year?` |
| Securities Advisor | `get_market_index_evaluation` | `symbol` |
| Securities Advisor | `analyze_stock_general` | `symbol` |
| Securities Advisor | `get_stock_price` | `symbol` |
| Securities Advisor | `compare_stocks` | `symbols` (list) |
| Analyst News | `analyze_macro_news` | `topic?`, `region?` |
| Analyst News | `analyze_sector_news` | `sector?`, `symbol?` |
| Analyst News | `get_market_overview_news` | `date?` |
| Customer Support | `get_company_info` | `topic` |
| Customer Support | `get_service_info` | `service_name` |
| Render Chart | `render_chart` | `symbol`, `chart_type?`, `timeframe?` |
| Action | `execute_ui_action` | `action_type`, `symbol?` |
| Vision | `analyze_image` | `image_description?` |

**Dispatch pipeline per request:**
```
1. before_model_callback()
   ├── Pick random key from HOST_API_KEY_LIST
   └── Inject realtime VN date into session state

2. LLM call (Gemini 2.5-flash via LiteLLM)
   → Outputs: agent_name, intent, parameters, original_query

3. send_task() tool
   ├── Build StructuredTaskPayload (Pydantic model)
   ├── to_cache_key() → "intent: param1=v1 param2=v2"
   ├── Qdrant cosine search (score ≥ 0.80 → CACHE HIT → return)
   ├── [MISS] Serialize payload to JSON → send via A2A HTTP
   ├── Receive A2A TaskResult (text + optional artifacts)
   └── store_cache() → asyncio.create_task() (non-blocking background)
```

---

### 6.3 Sub-Agent Pattern

Every sub-agent follows an identical structural pattern built on Google ADK:

```
agent.py        — LlmAgent definition, MCP tool loading, session lifecycle
app.py          — FastAPI/Starlette A2A endpoint (receives StructuredTaskPayload)
task_manager.py — Parses A2A request, calls agent.invoke() or agent.stream()
template_prompt.py — Domain-specific system prompt
custom_tool.py  — Agent-specific helper tools (non-MCP)
__main__.py     — Direct runnable entry point
```

**Session management:** ADK `InMemorySessionService` per agent process. Cross-worker session state (chart keys, user context) is bridged through Redis via the `RedisManager`.

**Model lifecycle:**
```python
LiteLlm(
    model="<agent_name>",       # logical name registered in LiteLLM proxy
    api_base="http://localhost:4000",
    api_key="sk-master-123456"  # internal proxy auth
)
```
LiteLLM routes the logical name to the actual Gemini model + API key. This allows model swapping without changing any agent code.

**MCP tool loading at startup:**
```python
toolset = MCPToolset(connection_params=SseServerParams(url=MCP_BASE_URL))
self._mcp_tools = await toolset.get_tools()
```
The agent holds a persistent SSE connection to the MCP server and discovers all tools dynamically.

---

### 6.4 Securities Advisor Agent — Deepest Agent

This is the most complex sub-agent. It handles stock analysis end-to-end.

**Capabilities:**
- Technical analysis (via MCP `technical_analyze` tool)
- Financial ratio deep-dive (6 domain groups, 30+ sub-metrics)
- Market summary (symbol / index / industry, short-term or macro)
- Stock ranking / screener (price, volume, revenue, profit changes)
- Company profile, dividends, industry peers
- Stock recommendations (pre-computed, filtered by exchange/industry)
- Chart key generation (fundamental or technical chart config)
- Grounded web search (`google_search` tool with `after_model_callback` for citation injection)

**Context enrichment (before each LLM call):**
1. `get_contexts_notif_from_mongo(session_id)` — system notification context (forced priority, agent must not contradict)
2. `get_contexts_personalization_from_mongo(user_id)` — user persona profile:
   - `expertise_level`: adjusts depth (beginner/intermediate/expert)
   - `jargon_allowed`: controls terminology density
   - `tracking_watchlist`: preferred tickers to prioritise
   - `tone_style`, `verbosity`, `teaching_style`

**Knowledge files loaded at startup** (injected directly into system prompt):
- `funnel_logic.md` — use-case → TA indicator mapping
- `financial_logic.md` — data_group + sub_group decision rules
- `market_logic.md` — `get_market_info` parameter decision tree
- `chart_logic_key.md` — chart metric key reference
- `statistic_logic.md` — `get_financial_statistic` query schema

**Streaming:** SSE event stream with tool-level progress messages:
```
"Đang xử lý công cụ technical_analyze..."
"Phát hiện 3 công cụ phân tích, đang xử lý tuần tự..."
[final] {"is_task_complete": true, "content": "..."}
```

---

### 6.5 MCP Server — The Intelligence Backbone

The MCP Server is a **FastMCP** application (`agent-data-api/main.py`). It is the central data and intelligence layer that all agents call. It exposes domain tools as async Python functions registered with `@mcp.tool()`.

#### Tool Categories

**Company & Market Tools:**
| Tool | What it does |
|------|-------------|
| `get_company_profile` | Company info, sector, leadership, shareholders |
| `get_dividend_info` | Dividend history, payout ratios, ex-dates |
| `get_market_summary` | Price/volume/foreign trade data for symbol/index/industry (7-day default) |
| `get_market_summary_macro` | 36-month macro view (long-term trend) |
| `get_max_price_index` | All-time high price for symbol/index/industry |
| `summary_change` | Market screener — top N by price/volume/revenue/profit change over any period |

**Financial Ratio Tools** (via `get_financial_info`, `compare_ratio`, `get_indicator_info`):
| Domain Group | Sub-metrics | Scope |
|-------------|------------|-------|
| `fundamental_health` | liquidity, solvency, interest_coverage | symbol / industry |
| `profitability` | ROE, ROA, DuPont 3-factor decomposition | symbol / industry |
| `efficiency` | turnover_ratios, CCC (DIO, DSO, DPO) | symbol / industry |
| `valuation` | P/E, P/B, P/S, EV/EBITDA, EPS, dividend_yield | symbol / industry |
| `cash_flow` | cashflow_structure, earnings_quality, balance_sheet_risks | symbol only |
| `banking` | asset_quality (NPL, LLR), efficiency (NIM, CIR), liquidity (LDR) | symbol only |

**Technical Analysis Tool** (`technical_analyze`):
- Reads pre-computed TA from `basement.aip_stock_watchlist_tcbs` (PostgreSQL)
- Returns a structured dict with 6 signal groups:

| Group | Indicators |
|-------|-----------|
| `trend` | SMA(200), EMA(50), uptrend/downtrend flag |
| `momentum` | RSI, MACD (histogram + signal), Bollinger Bands, DMI |
| `volume` | OBV, volume vs MA20 ratio |
| `breakout` | 52-week high proximity, heating_up flag |
| `short_term_growth` | 1W / 1M price % change |
| `system_signals` | Composite signals from TCBS data |

**Statistical Query Tool** (`get_financial_statistic`):
- Structured schema: `operation` × `subject` × `metric` × `period` × `ranking` × `grouping`
- The LLM generates this JSON directly from user NLP — it is a **typed query compiler**
- Two operation modes:
  - `snapshot` — current ratio value (quarterly/yearly grain)
  - `period_ranking` — top N by change over a date range
- Real-time path: during trading hours (Mon–Fri 9:00–12:00, 13:00–15:00 VN time), price queries are served from Redis market cache instead of PostgreSQL

**Chart Tool** (`get_chart_key`):
- Accepts a configuration object: `ticket[]`, `chart_type`, `metrics[]`/`indicators[]`, `mode`, `limit`
- Returns a `keyHash` stored in Redis; the frontend polls this hash to render the chart
- Supports 80+ financial metrics across 7 categories (valuation, profitability, health, efficiency, banking, cash flow, balance sheet)
- Supports all 9 TA indicators with full parameterisation

**Knowledge Base Tool** (`get_acbs_info`):
- Hybrid search on Weaviate ACBS collection
- Dense (Google genai embedding) + sparse (BM25 via fastembed) → RRF fusion
- Used by Customer Support Agent for grounded FAQ responses

---

## 7. Technical Analysis Pipeline

The technical indicator system (`technical_indicators/`) is a fully self-contained pipeline.

### Indicators Implemented

| Indicator | Params | Use Case |
|-----------|--------|----------|
| SMA / EMA | `period` (10/20/50/200) | Trend direction, support |
| MACD | `fast`, `slow`, `signal` (12/26/9 default) | Momentum, crossover signals |
| RSI | `period` (7/14/21) | Overbought/oversold, divergence |
| Bollinger Bands | `period`, `std_factor` (20, 2.0 default) | Volatility squeeze, mean reversion |
| Stochastic | `k_period`, `d_period` (14, 3 default) | Sideway trading trigger |
| ATR | `period` (14/21) | Stoploss calculation |
| OBV | — (cumulative) | Smart money detection (Breakout) |
| ADX / DMI | — | Trend strength quantification |
| +DI / -DI | — | Directional movement |

### Funnel Logic (Use-Case → Indicator Mapping)

The `funnel_logic.md` file is injected into the Securities Advisor prompt as a **reasoning guide**. It maps user trading intent to the optimal indicator combo, preventing the LLM from selecting irrelevant tools:

| User Intent | Optimal Combo |
|------------|--------------|
| Trend identification | SMA(200) + EMA(50) + MACD + ADX |
| Reversal / swing | RSI + Bollinger Bands + Stochastic |
| Breakout detection | Bollinger Bands + OBV |
| Sideway trading | Bollinger Bands + Stochastic (NOT MACD) |
| Stoploss calculation | ATR only |

### ScoringEngine — Non-Linear Signal Normalisation

`tech_scoring_service.py` implements a scoring engine that normalises raw indicator values into [0, 1] signals using non-linear maths:

| Transform | Formula | Used For |
|-----------|---------|----------|
| Reverse Sigmoid | `S = 1/(1+exp(k·(x−x₀)))` | RSI (high RSI → low score) |
| Tanh Scaled | `S = 0.5 + 0.5·tanh(α·x)` | Trend strength (price vs MA50) |
| Log Growth | `S = min(1, β·ln(1+r))` | Volume spike (OBV ratio) |
| Exp Decay | `S = exp(−λ·w)` | BB Squeeze (tighter band = higher score) |
| Sigmoid | `S = 1/(1+exp(−k·(h−x₀)))` | MACD histogram direction |

This prevents extreme indicator values from dominating composite scores.

---

## 8. Financial Analysis Pipeline

The `financial_ratios/` module organises every financial metric into **6 domain groups**, each with Markdown knowledge files that are loaded into agent prompts. This gives the LLM both the data and the reasoning framework for each metric.

### Domain Groups

**`fundamental_health`** — Solvency & Liquidity
- Liquidity: Current Ratio, Quick Ratio, Cash Ratio
- Solvency: D/E, Debt-to-Asset
- Interest Coverage: ICR

**`profitability`** — Earnings Quality & Returns
- Profitability ratios: Gross/Net Margin, ROE, ROA, ROIC
- DuPont decomposition: Net Margin × Asset Turnover × Equity Multiplier (3-factor)

**`efficiency`** — Capital Velocity
- Turnover ratios: Inventory, Receivable, Asset Turnover
- Cash Conversion Cycle: DIO + DSO − DPO

**`valuation`** — Market Pricing
- Relative: P/E, P/B, P/S, EV/EBITDA
- Absolute: EPS, FCF yield, dividend yield

**`banking`** — Bank-Specific KPIs (mandatory for VCB, TCB, ACB, etc.)
- Asset quality: NPL ratio, LLR coverage, accrued interest risk
- Efficiency: NIM, CIR, provision/PPOP
- Liquidity & capital: LDR, credit growth, leverage ratio

**`cash_flow`** — Earnings Verification
- Structure: CFO / CFI / CFF / FCF
- Quality: CFO / Net Income ratio (< 1 sustained → earnings quality risk)
- Balance sheet risk: Receivables / Inventory growth (capital trap detection)

### Industry-Aware Routing

The `financial_logic.md` knowledge file contains a **decision table** that the Securities Advisor agent uses to choose `data_group` + `sub_group` from user language cues:
- Keywords about "nợ, thanh khoản" → `fundamental_health`
- Keywords about "ROE, lợi nhuận" → `profitability`
- Ticker in banking sector → **mandatory** `banking` (overrides all other rules)

---

## 9. Statistic Agent — Structured Query Engine

The `statistic_agent/` module is an embedded **query compiler** inside the MCP server. It converts a structured JSON analysis object into optimised PostgreSQL queries at runtime.

**Schema** (`analysisInput`):
```
operation : "snapshot" | "period_ranking"
subject   : "ticker" | "industry"
metric    : roe | roa | pe | pb | eps | netsale | profitaftertax | price | volume
period    : { grain: "quarter"|"year" }   [snapshot]
          | { from: "YYYY-MM-DD", to: "YYYY-MM-DD" }   [period_ranking]
ranking   : { top_n: int, order: "desc"|"asc" }
grouping  : { within_industry: bool, industry_name: str }
ticker    : str
```

The LLM produces this JSON directly from NLP. This schema acts as a **typed query language** — the LLM never writes raw SQL.

**Real-time path:** If `operation=period_ranking`, `metric=price`, `subject=ticker`, `from_date=today`, and the current time is within VN trading hours → query Redis market cache instead of PostgreSQL for sub-second latency.

---

## 10. Semantic Task Cache

The `TaskCacheService` (Qdrant-backed) short-circuits redundant LLM + tool calls by caching agent task results.

### Collection Design (`agent_task_cache_jina`)

| Vector | Dimensions | Purpose |
|--------|-----------|---------|
| `jina_full` | 1024 (Cosine) | Accurate semantic search |
| `mrl_256` | 256 (Cosine) | Fast search path (Matryoshka Representation Learning) |
| `bm25` | Sparse (on-disk) | Keyword fallback |

Payload fields: `cache_key`, `intent`, `parameters`, `target_agent`, `original_query`, `response_data`, `response_parts`, `created_at`, `ttl_seconds`, `hit_count`

### Cache Key Design

```python
cache_key = f"{intent}: {sorted_params}"
# Example: "analyze_stock_technical: symbol=ACB timeframe=1D"
```

Two paraphrased user queries (`"ACB dạo này sao?"` vs `"Phân tích kỹ thuật ACB"`) produce the same cache key because the Host Agent normalises them to `intent + params` before caching.

### TTL Policy

| Intent Category | TTL |
|----------------|-----|
| Market/stock data (`analyze_stock_*`, `get_market_*`) | 10 minutes |
| Stock comparison | 10 minutes |
| Chart rendering | 30 minutes |
| News / macro (`analyze_macro_*`, `analyze_sector_*`) | 2 hours |
| Company info / service (`get_company_*`, `get_service_*`) | 12 hours |
| `execute_ui_action`, `analyze_image` | 0 (never cached) |

### Cache Lookup Flow

```
1. Build cache_key from intent + sorted params
2. Embed cache_key with Jina v5 → 1024-dim query vector
3. Qdrant cosine search with target_agent filter
4. If score ≥ 0.80 AND not expired → CACHE HIT
5. Update hit_count (async)
6. Return stored response_parts
```

Cache store runs as `asyncio.create_task()` — never blocks the response path.

---

## 11. News & RAG Pipeline

The `services/news/` module provides a full news indexing and retrieval pipeline.

### Indexing (`emdedding_news.py`)

News articles are embedded and stored in Qdrant collection `news_v2`:

| Vector | Model | Dims |
|--------|-------|------|
| `zembed_full` | ZeroEntropy zembed-1 | 2560 |
| `mrl_256` | First 256 dims | 256 |
| `bm25` | fastembed BM25 | sparse |

### Retrieval

The `QdrantService.query_hybrid()` method performs:
1. Dense search on `zembed_full` or `mrl_256` (alpha-weighted)
2. BM25 sparse keyword search
3. RRF (Reciprocal Rank Fusion) for result merging

The Analyst News Agent calls this retrieval, then synthesises the results with the LLM — a classic **RAG pattern**.

### Knowledge Base (Weaviate)

`services/vectordb_query.py` implements hybrid search on Weaviate for the ACBS company knowledge base:
- Google genai dense embeddings
- BM25 via fastembed sparse
- RRF fusion
- Used by Customer Support Agent for grounded, citation-backed FAQ responses

---

## 12. Personalization & Context Injection

Before every Securities Advisor invocation, the agent fetches two context layers from MongoDB:

### Layer 1: System Context (`contexts_notif`)
Source: `conversations_uat.notification_payload` collection, keyed by `notification_id = session_id`

This contains pre-computed market state, system alerts, or analyst signals. The agent is instructed:
- Treat this as the **mandatory reasoning foundation**
- Do not contradict this context
- If user query diverges, explain from this baseline

### Layer 2: User Personalization (`contexts_personalization`)
Source: `conversations_uat.ai_personalization` collection, keyed by `user_info.id`

| Field | Values | Agent Behaviour |
|-------|--------|----------------|
| `expertise_level` | beginner / intermediate / expert | Adjust analytical depth; suppress basics for experts |
| `jargon_allowed` | bool | Enable/disable technical terminology |
| `tracking_watchlist` | list of symbols | Prioritise these in analysis |
| `tone_style` | formal / casual | Adjust response register |
| `verbosity` | concise / detailed | Response length |
| `teaching_style` | descriptive / Socratic | Explanation method |

---

## 13. Chart System

Chart rendering follows a **key-based indirection pattern**:

```
Agent calls get_chart_key(ticket, chart_type, metrics/indicators, mode, limit)
   ↓
MCP server computes a config hash → stores config in Redis with keyHash
   ↓
Agent returns keyHash to client
   ↓
Frontend polls Redis with keyHash → retrieves chart config → renders chart
```

**Chart types:**
- `"fundamental"` — financial ratio trends (80+ metrics across 7 categories)
- `"technical"` — TA indicator charts (all 9 indicators with full parameter control)

**Modes:** `symbol` (single ticker), `compare` (two tickers side-by-side), `industry`

After `get_chart_key` returns, the Securities Advisor agent also pushes the full response data to Redis via `redis_manager.push_json_data()` so the frontend can hydrate immediately.

---

## 14. Report Generation Pipeline

The main app includes an automated PDF/HTML report pipeline.

**Routes:**
- `POST /api/reports/...` — triggers AI-generated market/stock reports
- `GET /report_files/{file_name}` — serves generated PDF/HTML files
- `GET /report_files/charts/{file_name}` — serves chart PNGs
- `GET /img/{path}` — proxies images from MinIO

**Templates** (Jinja2 → PDF):
- `report_market.html` / `report_market_v2.html` — daily market overview
- `report_symbol.html` — single stock deep-dive (non-banking companies)
- `report_symbol_no_banking.html` — single stock (banking companies, different metrics)
- `analyst_symbol.html` — analyst report format

**Chart pipeline:** Charts are generated as PNG by `final_chart/` modules using `matplotlib`, saved to `./report_files/charts/`, and embedded in the HTML before PDF conversion.

---

## 15. Training Data Feedback Loop

The `training.py` router provides a feedback loop for continuous prompt improvement:

1. Conversations are stored in MongoDB with quality scores
2. Low-rated responses are flagged with admin correction suggestions
3. The Host Agent's `get_suggest_prompts()` tool retrieves flagged prompts from `training_prompt` collection
4. These examples are injected into the system context, giving the LLM in-context corrections without retraining

---

## 16. Data Flow: Full Request Lifecycle

```
User: "Phân tích kỹ thuật ACB"
           │
           ▼
POST /api/... (Main App :5678)
           │
           ▼
HostAgent.invoke(query, user_id, session_id)
           │
   before_model_callback()
   ├── random key from HOST_API_KEY_LIST
   └── inject VN date + trading calendar into state
           │
   LLM: Gemini 2.5-flash via LiteLLM
   → intent="analyze_stock_technical", agent="Securities_Advisor_Agent", params={"symbol":"ACB"}
           │
   send_task()
   ├── StructuredTaskPayload built (Pydantic)
   ├── cache_key = "analyze_stock_technical: symbol=ACB"
   ├── Jina embed → Qdrant search
   │    score=0.94 ≥ 0.80 → CACHE HIT ──────────────────────► return cached
   │    (or score < 0.80 → CACHE MISS → continue)
           │
   A2A HTTP POST → Securities Advisor :10001
   {"metadata":…, "context":{"user_persona":…}, "task":{"intent":"analyze_stock_technical","parameters":{"symbol":"ACB"}}}
           │
           ▼
SecuritiesAdvisorAgentADK.invoke(query, user_id, session_id)
   ├── get_contexts_from_mongo(session_id, user_id)
   │    ├── contexts_notif from MongoDB (market alerts)
   │    └── contexts_personalization from MongoDB (user profile)
   ├── Inject context layers into final_query
           │
   LLM: Gemini 2.0-flash via LiteLLM
   → calls MCP tools via SSE:
      technical_analyze("ACB") → trend + momentum + volume + breakout + signals
      get_market_summary(symbol="ACB", days=30) → price history
      get_indicator_info(symbol="ACB", data_group="profitability") → ROE, margins
      get_chart_key(ticket=["ACB"], chart_type="technical", indicators=["RSI","MACD"])
           │
   _log_function_parts() → logs each tool call + duration
   redis_manager.push_json_data(keyHash) → stores chart data for frontend
           │
   A2A TaskResult → text response + optional image artifact
           │
           ▼
HostAgent receives result
   ├── asyncio.create_task(store_cache()) → Qdrant upsert (background)
   └── return formatted JSON response to client
```

---

## 17. Infrastructure & Networking

### Docker Networks

| Network | Type | Members |
|---------|------|---------|
| `agent-network` | bridge (internal) | All agents, MCP, Redis, MinIO |
| `shared-agent-network` | external | Shared with other compose stacks |
| `shared-net` | external | External services |

### Service Startup Order

```
redis (healthy)
mcp-server (healthy)    ← waits for redis
minio
  └─► customer-support-agent
  └─► securities-advisor-agent  ← waits for mcp-server
  └─► vision-agent
  └─► analyst-news-agent
  └─► render-chart-agent
  └─► action-agent
  └─► agent-server (main)       ← waits for all of the above
```

### Key Volumes

| Volume | Mount Point | Purpose |
|--------|-------------|---------|
| `minio_data` | MinIO `/data` | Persistent blob storage |
| `redis_session_data` | Redis `/data` | Persistent session store |
| `./report_files` | `/app/report` | Generated reports + charts |

---

## 18. Security Design

| Concern | Approach |
|---------|---------|
| Authentication | JWT (`HS256`, `JWT_SECRET` env) for internal API calls |
| MCP session validation | Redis-backed middleware validates `X-MCP-Session-ID` on every request (except `/health`, `/sse`) |
| API key leakage prevention | Keys never appear in logs; rotation happens in `before_model_callback` via `os.environ` per-request |
| CORS | Currently `allow_origins=["*"]` — should be restricted for production |
| Secrets management | All credentials in `.env` (gitignored) |
| Database isolation | Databases not exposed externally; all access via MCP Server or internal service layers |

---

## 19. Observability

| Signal | Implementation |
|--------|---------------|
| Structured logging | `setup_service_logging(service_name)` with service-scoped loggers |
| uvicorn access logs | `config/uvicorn_logging.ini` |
| Tool call tracing | `_log_function_parts()` logs every tool name, args (truncated), duration |
| Cache analytics | `CACHE_ANALYSIS` log: score, threshold, strategy, latency per lookup |
| A2A task logging | `MongoLogger` records task inputs/outputs for analysis |
| Health checks | MCP `/health` → checks Redis + PostgreSQL; Docker healthcheck polls this |

---

## 20. Configuration Reference

### Key Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `AGENT_LLM_USE` | Model for sub-agents | `gemini-2.0-flash` |
| `HOST_MODEL_USE` | Model for host orchestrator | `gemini-2.5-flash` |
| `AGENT_API_KEY_LIST` | Comma-sep Gemini keys for sub-agents | `key1,key2,…` |
| `HOST_API_KEY_LIST` | Comma-sep Gemini keys for host | `key1,key2,…` |
| `ENABLE_AGENT_TASK_CACHE` | Toggle semantic cache | `True` / `False` |
| `APP_PORT` | Main app port | `5678` |
| `MCP_SERVER_PORT` | MCP server port | `8889` |
| `URL_MCP` | MCP SSE endpoint (agents connect here) | `http://mcp-server:8889/sse` |
| `REDIS_HOST` / `REDIS_PASSWORD` | Redis connection | — |
| `MONGO_URI` / `MONGO_DATABASE` | MongoDB connection | — |
| `HOST_VecDB` / `PORT_VecDB` | Weaviate host | `172.60.1.4:8082` |

---

## 21. Known Constraints & Design Decisions

| Decision | Reason |
|----------|--------|
| MCP tools execute sequentially | ADK framework handles tool calls sequentially to avoid MCP SSE scope conflicts when calling multiple tools in parallel |
| MCP server: single worker only | asyncpg connection pool does not survive across multiple uvicorn processes; single worker avoids pool corruption |
| LiteLLM as model proxy | Decouples agent code from model identity; enables model swapping without code changes; centralises key management |
| Qdrant cache key = `intent + sorted params` (not raw NLP) | Same logical query in different phrasings maps to the same cache key, dramatically increasing hit rate |
| Knowledge files injected into prompt (not retrieved) | Financial indicator logic is small (< 8K tokens total); injection is faster and more reliable than RAG for this structured reference content |
| Vietnamese-first prompts | All system prompts, MCP tool docstrings, and knowledge files are in Vietnamese — the LLM performs better on domain-specific financial terminology in the language it will be used in |
| API key pool rotation | Distributes Gemini rate limits across ~10 keys per tier; `before_model_callback` makes the selection per-request |
| `NO_CACHE_INTENTS` for actions/images | UI actions and image analysis have side effects or are inherently unique — caching would return stale or incorrect results |
| Background cache store | `asyncio.create_task()` for Qdrant upsert means cache storage never adds latency to the user-facing response |

---

## 22. Glossary

| Term | Definition |
|------|-----------|
| **A2A** | Agent-to-Agent protocol — HTTP JSON RPC used for inter-agent task delegation |
| **MCP** | Model Context Protocol — SSE-based protocol for exposing tools to LLM agents |
| **ADK** | Google Agent Development Kit — framework for agent lifecycle, sessions, runners |
| **LiteLLM** | Open-source proxy normalising LLM API calls across providers |
| **StructuredTaskPayload** | Pydantic model encoding intent + parameters + context sent from Host to sub-agents |
| **TaskCacheService** | Qdrant-backed semantic cache for agent task results |
| **ScoringEngine** | Non-linear math transforms (sigmoid, tanh, log, exp-decay) for TA signal normalisation |
| **Funnel Logic** | Intent-to-indicator mapping guide injected into Securities Advisor prompt |
| **DuPont Decomposition** | 3-factor ROE breakdown: Net Margin × Asset Turnover × Equity Multiplier |
| **RRF** | Reciprocal Rank Fusion — score merging strategy for hybrid dense+sparse search |
| **MRL** | Matryoshka Representation Learning — embeddings where shorter prefixes are still meaningful |
| **keyHash** | Redis key returned by `get_chart_key` that frontend uses to retrieve chart config |
| **HOSE / HNX / UPCOM** | Vietnam's three stock exchanges |
| **VN-Index / HNX-Index** | Benchmark indices for HOSE and HNX exchanges |
| **NIM / NPL / LDR / CIR** | Banking KPIs: Net Interest Margin / Non-Performing Loan ratio / Loan-to-Deposit Ratio / Cost-to-Income Ratio |
| **CCC** | Cash Conversion Cycle = DIO + DSO − DPO (measures capital velocity) |
