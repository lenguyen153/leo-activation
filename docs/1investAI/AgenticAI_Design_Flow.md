# Agentic AI Design — Flow Diagram

> Agent System: AI Stock & Finance (Leo Activation)

---

## Overview (Simplified)

```mermaid
flowchart TD
    USER(["👤 User"])
    USER -->|"Natural language query"| HOST

    subgraph HOST["🧠 Host Agent — Orchestrator"]
        direction TB
        CLASSIFY["Classify intent\nGemini 2.5-flash"]
        CLASSIFY -->|"Small-talk"| REPLY(["Direct reply"])
        CLASSIFY -->|"Business query"| CACHE

        CACHE{"Semantic cache\nhit?"}
        CACHE -->|"✅ Yes"| CACHED(["Return instantly"])
        CACHE -->|"❌ No"| ROUTE
        ROUTE["Route to specialist agent\nvia A2A"]
    end

    ROUTE --> SA & NA & CS & CA & AA & VA

    SA["📈 Securities\nAdvisor"]
    NA["📰 Analyst\nNews"]
    CS["🏦 Customer\nSupport"]
    CA["📊 Chart\nAgent"]
    AA["⚡ Action\nAgent"]
    VA["👁️ Vision\nAgent"]

    SA & NA & CS & CA & AA & VA -->|"Call MCP tools"| MCP

    subgraph MCP["🔧 MCP Server — Data Tools"]
        direction LR
        T1["Technical\nAnalysis"] 
        T2["Financial\nRatios"]
        T3["Market\nData"]
        T4["News\nRAG"]
        T5["Chart\nKeys"]
    end

    subgraph DB["💾 Data Layer"]
        direction LR
        PG[("PostgreSQL")] 
        MDB[("MongoDB")]
        RD[("Redis")]
        QD[("Qdrant")]
        WV[("Weaviate")]
    end

    T1 & T2 & T3 --> PG
    T4 --> QD & WV
    T5 --> RD
    MDB -.->|"User context\n+ personalization"| SA

    MCP -->|"Tool results\nback to agent LLM"| RESP
    RESP["Agent synthesises\nfinal answer"]
    RESP -->|"Store in cache\nnon-blocking"| QD
    RESP --> USER
```

---

## Full Request Flow

```mermaid
flowchart TD
    USER(["👤 User / Frontend"])
    USER -->|"HTTP Request"| MAIN

    MAIN["🖥️ Main App Server\nFastAPI  :5678\nAPI gateway · Report serving · MinIO proxy"]
    MAIN --> HA

    %% ─── ORCHESTRATOR ────────────────────────────────────────────
    subgraph ORCH["🧠  HOST AGENT — Orchestrator"]
        direction TB

        HA["Host Agent\nModel: Gemini 2.5-flash via LiteLLM proxy"]
        HA --> CB

        CB["before_model_callback\n① Pick random key from HOST_API_KEY_LIST\n② Inject real-time VN date + trading calendar\n③ Holiday detection — market open / closed\n④ Inject registered agent registry into prompt"]
        CB --> CLASSIFY

        CLASSIFY{"🤔 Classify intent"}
        CLASSIFY -->|"Small-talk\ngreeting / capability"| DIRECT
        CLASSIFY -->|"Business query\nstock · finance · action"| PAYLOAD

        DIRECT(["💬 Direct reply\nNo agent call"])

        PAYLOAD["📦 Build StructuredTaskPayload\n• intent  e.g. analyze_stock_technical\n• parameters  e.g. symbol=ACB timeframe=1D\n• user_persona  language · expertise_level\n• conversation_summary  context window\n• metadata  request_id · timestamp · user_id"]

        PAYLOAD --> CKEY
        CKEY["🔑 Build deterministic cache key\ncache_key = intent + sorted_params\npoint_id = SHA-256 hash of cache_key"]
        CKEY --> QSEARCH

        QSEARCH{"🔍 Qdrant Semantic Search\nJina 1024-dim Cosine\nfilter: target_agent\ncosine score ≥ 0.80?"}
        QSEARCH -->|"✅  CACHE HIT\nUpdate hit_count async"| CACHED
        QSEARCH -->|"❌  CACHE MISS"| A2ASEND

        CACHED(["⚡ Return cached response\nskip LLM + all tool calls"])

        A2ASEND["📤 A2A HTTP POST\nStructuredTaskPayload as JSON\n→ target sub-agent endpoint"]
    end

    A2ASEND --> ROUTER

    %% ─── SUB-AGENTS ──────────────────────────────────────────────
    subgraph SUBS["🤖  SUB-AGENT LAYER — Domain Specialists  (Gemini 2.0-flash · Google ADK)"]
        direction TB

        ROUTER{"🔀 Route by agent_name"}

        ROUTER --> SA["📈 Securities Advisor  :10001\nStock · Technical · Financial · Chart · Screener"]
        ROUTER --> CS["🏦 Customer Support  :10002\nACBS FAQ · Services · Account"]
        ROUTER --> VA["👁️  Vision Agent  :10003\nImage · Screenshot Understanding"]
        ROUTER --> NA["📰 Analyst News  :10004\nMacro · Sector News · Market Outlook"]
        ROUTER --> CA["📊 Chart Agent  :10005\nChart Config · Hash Key Generation"]
        ROUTER --> AA["⚡ Action Agent  :10006\nBuy · Sell · UI Workflow Execution"]

        SA --> CTXFETCH
        CTXFETCH["🗂️  Context Enrichment  before LLM call\n① notification_payload  MongoDB  keyed by session_id\n   MANDATORY — agent must not contradict this\n② ai_personalization  MongoDB  keyed by user_id\n   expertise_level · jargon_allowed · tone_style\n   tracking_watchlist · verbosity · teaching_style"]

        CTXFETCH --> AGENTLLM
        AGENTLLM["🧠 LLM Reasoning Loop\nGemini 2.0-flash · Google ADK LlmAgent\nKnowledge files injected into system prompt:\n  funnel_logic.md  financial_logic.md\n  market_logic.md  chart_logic_key.md\n  statistic_logic.md"]

        AGENTLLM -->|"Function calls\n sequential — ADK framework\n logs: name · args · duration"| MCPTOOLS
    end

    %% ─── MCP SERVER ──────────────────────────────────────────────
    subgraph MCPSVR["🔧  MCP SERVER  :8889 — FastMCP + Starlette + SSE"]
        direction TB

        MCPTOOLS{"Tool dispatch\nOne persistent SSE connection per agent"}

        MCPTOOLS --> T1["technical_analyze symbol\nReads pre-computed TA from PostgreSQL\nReturns 6 signal groups:\ntrend · momentum · volume\nbreakout · short_term_growth · system_signals"]

        MCPTOOLS --> T2["get_financial_info symbol year quarter\n6 domain groups:\nbanking  NPL NIM LDR CIR\nprofitability  ROE ROA DuPont\nefficiency  Turnover CCC\nvaluation  PE PB EV-EBITDA\ncash_flow  CFO CFI CFF FCF quality\nfundamental_health  Liquidity Solvency ICR"]

        MCPTOOLS --> T3["get_market_summary\nPrice · Volume · Foreign trade\n7-day window or 36-month macro\nby symbol · index · industry · all"]

        MCPTOOLS --> T4["summary_change  Market screener\nTop N by price volume revenue profit\nPeriod ranking over any date range\nFilter by exchange or industry"]

        MCPTOOLS --> T5["get_financial_statistic\nTyped query schema:\noperation  snapshot or period_ranking\nsubject  ticker or industry\nmetric  roe roa pe pb price volume\nperiod  grain or from-to date range\nRealtime path: Redis during trading hours"]

        MCPTOOLS --> T6["get_chart_key  ticket chart_type metrics\nCompute chart config hash\nPush full data to Redis\nReturn keyHash to frontend"]

        MCPTOOLS --> T7["get_acbs_info  collection query\nWeaviate hybrid search:\nDense Google genai embeddings\n+ BM25 fastembed sparse\nFused with RRF"]

        MCPTOOLS --> T8["recommend_symbols_today\nPre-computed recommendations\nFilter by exchange · industry · top_n"]
    end

    %% ─── DATA LAYER ──────────────────────────────────────────────
    subgraph DATA["💾  DATA LAYER"]
        direction LR
        PG[("PostgreSQL\nHistorical quotes\nFinancial statements\nTA pre-computed\naip_stock_watchlist_tcbs\nRecommendations")]
        MONGO[("MongoDB\nConversations\nUser personalization\nNotification payload\nTraining prompts\nMarket messages")]
        REDIS[("Redis\nMCP sessions\nChart key cache\nADK session state\nRT market cache\n  during trading hours")]
        QDVEC[("Qdrant\nagent_task_cache_jina\n  Jina 1024d + MRL-256 + BM25\nnews_v2\n  zembed 2560d + MRL-256 + BM25")]
        WEAV[("Weaviate\nACBS knowledge base\nHybrid vector search")]
    end

    %% DB connections
    T1 & T2 & T3 & T4 & T5 --> PG
    CTXFETCH --> MONGO
    T6 --> REDIS
    T7 --> WEAV
    NA -.->|"RAG: news retrieval"| QDVEC

    %% ─── RETURN PATH ─────────────────────────────────────────────
    MCPTOOLS -->|"Tool results → LLM continues"| AGENTLLM
    AGENTLLM -->|"Final answer\nA2A TaskResult"| RECV

    subgraph POST["📤  POST-PROCESSING — Host Agent"]
        direction TB
        RECV["📥 Receive A2A TaskResult\ntext parts + optional image artifacts"]
        RECV --> BGCACHE
        BGCACHE["🗄️  asyncio.create_task  — non-blocking background\nEmbed with Jina v5 → Qdrant upsert\nStore: response_data · response_parts · TTL\nTTL by intent:\n  market data  10 min\n  news         2 h\n  company info 12 h\n  actions      never cached"]
        RECV --> FINAL
        FINAL(["✅ Structured JSON Response\nreturned to client"])
    end

    FINAL --> USER

    %% ─── STREAMING PATH ──────────────────────────────────────────
    AGENTLLM -.->|"SSE stream\nper-tool progress updates\nis_task_complete: false"| STREAM
    STREAM(["📡 Streaming to client\nDang xu ly cong cu technical_analyze ...\nDang xu ly cong cu get_financial_info ..."])
```

---

## Agentic Patterns Legend

```mermaid
flowchart LR
    P1["🎭 Orchestrator / Planner\nHost Agent routes and coordinates\nwithout doing domain work itself"]
    P2["🔧 Tool Use / Function Calling\nAll sub-agents call MCP tools\nto ground responses in live data"]
    P3["📚 RAG — Retrieval-Augmented Generation\nNews Agent pulls from Qdrant\nSupport Agent pulls from Weaviate\nbefore generating"]
    P4["📦 Structured Output\nHost → Sub-agent communication\nvia StructuredTaskPayload JSON\nnot raw NLP text"]
    P5["⚡ Semantic Caching\nQdrant cosine similarity on\nintent + params not raw query\nskips LLM + tools on hit"]
    P6["🗂️ Context Injection\nMongoDB notification context\nuser persona profile\ninjected before every LLM call"]
    P7["🔄 Callback Hooks\nbefore_model_callback\n  key rotation + date inject\nafter_model_callback\n  grounding citation append"]
    P8["📡 Streaming\nSSE event stream with\nper-tool progress messages\nto client during long calls"]

    P1 --- P2 --- P3 --- P4
    P5 --- P6 --- P7 --- P8
```

---

## Cache Decision Detail

```mermaid
flowchart TD
    Q["User query: 'ACB dạo này sao?'"]
    Q --> NLP["NLP → LLM classifies"]
    NLP --> INTENT["intent = analyze_stock_technical\nparameters = symbol:ACB"]
    INTENT --> KEY["cache_key = analyze_stock_technical: symbol=ACB\n← same key regardless of query phrasing"]
    KEY --> EMBED["Jina v5 embed cache_key → 1024-dim vector"]
    EMBED --> SEARCH["Qdrant query\nfilter: target_agent = Securities_Advisor_Agent\nlimit: 1\nusing: jina_full"]
    SEARCH --> SCORE{"cosine score ≥ 0.80?"}
    SCORE -->|"YES  e.g. 0.94"| TTL{"Check TTL\ncreated_at + ttl_seconds > now?"}
    TTL -->|"Not expired"| HIT["CACHE HIT\nReturn stored response_parts\nUpdate hit_count async"]
    TTL -->|"Expired"| DELETE["Delete point from Qdrant\nCACHE MISS → call agent"]
    SCORE -->|"NO  e.g. 0.61"| MISS["CACHE MISS\nCall sub-agent\nStore result after  non-blocking"]
```

---

## Detailed Sequence Diagram

> Shows every decision point in order, with exact timing of what triggers what.
> Example query: **"Phân tích kỹ thuật ACB"** routed to Securities Advisor Agent.

```mermaid
sequenceDiagram
    autonumber

    participant U  as 👤 User
    participant APP as 🖥️ Main App :5678
    participant HOST as 🧠 Host Agent
    participant QD  as 🗄️ Qdrant Cache
    participant SA  as 📈 Securities Advisor :10001
    participant MDB as 🍃 MongoDB
    participant MCP as 🔧 MCP Server :8889
    participant PG  as 🐘 PostgreSQL
    participant RD  as ⚡ Redis

    U->>+APP: HTTP POST query="Phân tích kỹ thuật ACB"
    APP->>+HOST: invoke(query, user_id, session_id)

    Note over HOST: ① before_model_callback
    HOST->>HOST: Pick random key from HOST_API_KEY_LIST
    HOST->>HOST: Inject VN date + trading calendar into session state
    HOST->>HOST: Detect holiday / market open status

    Note over HOST: ② LLM Intent Classification — Gemini 2.5-flash
    HOST->>HOST: Prompt = system_prompt_host(dates, holiday, agents)

    alt Small-talk or greeting (e.g. "Xin chào", "Bạn làm được gì?")
        HOST-->>APP: Direct reply — no send_task called
        APP-->>U: 💬 Text response
    else Business query detected
        Note over HOST: ③ Build StructuredTaskPayload
        HOST->>HOST: intent = analyze_stock_technical
        HOST->>HOST: parameters = {symbol: ACB, timeframe: 1D}
        HOST->>HOST: cache_key = "analyze_stock_technical: symbol=ACB timeframe=1D"
        HOST->>HOST: point_id = SHA-256(cache_key)[:32]

        Note over HOST,QD: ④ Semantic Cache Lookup
        HOST->>HOST: Jina v5 embed cache_key → 1024-dim vector
        HOST->>+QD: query(vector, filter=target_agent, limit=1)
        QD-->>-HOST: {score: 0.xx, payload: {...}, created_at, ttl_seconds}

        alt CACHE HIT — score ≥ 0.80
            alt TTL not expired
                HOST->>QD: set_payload(hit_count + 1) [async, non-blocking]
                HOST-->>APP: Cached response_parts
                APP-->>U: ⚡ Response (no LLM or tool calls made)
            else TTL expired
                HOST->>QD: delete(point_id) [cleanup stale entry]
                Note over HOST: Treat as CACHE MISS → continue
            end
        else CACHE MISS — score < 0.80
            Note over HOST,SA: ⑤ A2A Dispatch
            HOST->>+SA: HTTP POST /tasks/send (StructuredTaskPayload JSON)
            Note over SA: Receives: intent, parameters, user_persona,<br/>conversation_summary, metadata

            Note over SA,MDB: ⑥ Context Enrichment (before LLM call)
            SA->>+MDB: find(notification_payload, {notification_id: session_id})
            MDB-->>-SA: System context — market alerts, analyst signals
            SA->>+MDB: find(ai_personalization, {user_info.id: user_id})
            MDB-->>-SA: User profile — expertise_level, tone_style, watchlist

            alt Notification context found
                SA->>SA: Prepend MANDATORY system context to query
                Note right of SA: Agent must NOT contradict this context
            end
            alt Personalization found
                SA->>SA: Inject user profile into prompt
                Note right of SA: Adjust depth, terminology,<br/>tone based on expertise_level
            end

            Note over SA: ⑦ Inject knowledge files into system prompt
            SA->>SA: Load funnel_logic.md → TA indicator mapping
            SA->>SA: Load financial_logic.md → data_group decision rules
            SA->>SA: Load market_logic.md → market tool parameters
            SA->>SA: Load chart_logic_key.md → chart metric reference
            SA->>SA: Load statistic_logic.md → query engine schema

            Note over SA: ⑧ LLM Reasoning Loop — Gemini 2.0-flash
            SA->>SA: Plan which MCP tools to call

            SA->>+MCP: [SSE] technical_analyze("ACB")
            Note right of SA: Streaming update to client:<br/>"Đang xử lý công cụ technical_analyze..."
            MCP->>+PG: SELECT * FROM basement.aip_stock_watchlist_tcbs WHERE ticker='ACB'
            PG-->>-MCP: MA, RSI, MACD, BB, ATR, OBV, ADX, DMI raw values
            MCP->>MCP: Group into trend · momentum · volume · breakout · system_signals
            MCP-->>-SA: Structured TA result dict

            SA->>+MCP: [SSE] get_financial_info("ACB", data_group="profitability")
            Note right of SA: Streaming update:<br/>"Đang xử lý công cụ get_financial_info..."
            MCP->>+PG: SELECT financial statements WHERE ticker='ACB'
            PG-->>-MCP: Income statement, balance sheet, ratios
            MCP->>MCP: Compute ROE · ROA · DuPont 3-factor decomposition
            MCP-->>-SA: Profitability ratios

            opt User also asked for market trend
                SA->>+MCP: [SSE] get_market_summary(symbol="ACB", days=30)
                MCP->>+PG: SELECT historical_quotes WHERE ticker='ACB' LIMIT 30
                PG-->>-MCP: Price · volume · foreign trade series
                MCP-->>-SA: Market summary
            end

            opt User requested a chart
                SA->>+MCP: [SSE] get_chart_key(ticket=["ACB"], chart_type="technical", indicators=[...])
                MCP->>MCP: Compute chart config → keyHash
                MCP->>RD: SET keyHash → chart_config [TTL 30 min]
                RD-->>MCP: OK
                MCP-->>-SA: {keyHash: "abc123..."}
                SA->>RD: push_json_data(keyHash, full_response_data)
            end

            Note over SA: ⑨ LLM synthesises final response
            SA->>SA: Combine all tool results into Vietnamese narrative
            SA->>SA: after_model_callback — append grounding citations if web search used

            SA-->>-HOST: A2A TaskResult {status: COMPLETED, message: {parts: [text]}}

            Note over HOST,QD: ⑩ Background Cache Store (non-blocking)
            par asyncio.create_task — does not block response
                HOST->>HOST: Jina v5 embed cache_key → dense vector
                HOST->>HOST: BM25 embed cache_key → sparse vector
                HOST->>QD: upsert(point_id, {jina_full, mrl_256, bm25}, payload)
                Note right of QD: TTL = 10 min for market/stock intents<br/>Payload stores response_data + response_parts
            and
                HOST-->>APP: Structured JSON response
                APP-->>-U: ✅ Final response
            end
        end
    end
```

---

## TTL Policy

| Intent Category | Examples | TTL |
|----------------|---------|-----|
| Real-time market & stock | `analyze_stock_*`, `get_stock_price`, `get_market_*` | **10 min** |
| Stock comparison | `compare_stocks` | **10 min** |
| Chart rendering | `render_chart` | **30 min** |
| News & macro | `analyze_macro_*`, `analyze_sector_*`, `get_market_overview_news` | **2 h** |
| Company & service info | `get_company_*`, `get_service_*` | **12 h** |
| UI actions & images | `execute_ui_action`, `analyze_image` | **Never cached** |
