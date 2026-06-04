# Mock User Story — End-to-End Call Trace

**Query:** `"ACB hôm nay thế nào? Cho tôi xem biểu đồ RSI và MACD"`
**User:** Nguyen Van A — `user_id="user-0042"`, intermediate investor
**Session:** `session_id="sess-9f3a1b2c"`
**Timestamp:** 2026-05-14 10:23:07 ICT (Wednesday, market open)

---

## Phase 1 — HTTP Ingress

`POST /api/training/send_message` received by **`main.py`** FastAPI gateway.

→ Route handler calls `host_agent_service.SendMessage(query, user_id, session_id)`.

---

## Phase 2 — Host Agent Invoked

**`HostAgent.invoke(query="ACB hôm nay thế nào?...", user_id="user-0042", session_id="sess-9f3a1b2c")`**

→ ADK `Runner` retrieves or creates session `sess-9f3a1b2c`.

---

## Phase 3 — before_model_callback (Host)

**`HostAgent.before_model_callback(callback_context, llm_request)`**

→ `settings.get_random_gemini_key(is_host=True)` → `"AIzaSyDWKSbzo3..."` (rotated key set to env)

→ `get_relative_dates(datetime.now(vietnam_tz))` → `{"today": "2026-05-14", "weekday_name": "Thứ Tư", "last_trading_day": "2026-05-13", "current_quarter": "Q2/2026"}`

→ Dates stored to `callback_context.state["realtime_dates"]`.

---

## Phase 4 — System Prompt Construction

**`HostAgent.root_instruction(context)`** → calls:

**`get_all_trading_holidays_in_year(2026)`** → list of VN public holidays

**`is_holiday(date(2026, 5, 14), holidays)`** → `(False, None)`

**`system_prompt_host(_dates, is_holiday=False, holiday_info=None, agents=self.agents)`** → full system prompt string (intent routing table + agent registry + VN date injected)

---

## Phase 5 — LLM Intent Classification

**Gemini 2.5-flash** via LiteLLM proxy receives query + system prompt.

→ LLM calls tool: **`send_task(agent_name="Securities_Advisor_Agent", intent="analyze_stock_technical", parameters={"symbol": "ACB", "timeframe": "1D", "chart_indicators": ["RSI", "MACD"]}, original_query="ACB hôm nay thế nào?...")`**

---

## Phase 6 — Build StructuredTaskPayload

**`HostAgent.send_task(agent_name, intent, parameters, original_query, tool_context)`**

→ `StructuredTaskPayload(metadata={request_id, source_agent, target_agent, user_id, session_id}, task=TaskIntent(intent, parameters, original_nlp_query), context=TaskContext(...))` constructed

→ **`payload.to_cache_key()`** → `"analyze_stock_technical: chart_indicators=['RSI', 'MACD'] symbol=ACB timeframe=1D"`

→ **`payload.to_cache_key_hash()`** → `"a3f8c1d2e5b07641f9e3a2c4d8f01b5e"`

---

## Phase 7 — Semantic Cache Lookup

**`TaskCacheService.search_cache(payload, target_agent="Securities_Advisor_Agent")`**

→ Embeds `cache_key` via Jina v5 API → 1024-dim vector

→ Queries Qdrant collection `agent_task_cache_jina` with agent filter

→ Top result score = `0.61` — below threshold `0.80`

→ Returns `(None, None)` → **CACHE MISS**, proceed to sub-agent call.

---

## Phase 8 — A2A Dispatch

**`HostAgent.send_task()`** continued:

→ **`payload.to_message_text()`** → JSON string of `StructuredTaskPayload`

→ `TaskSendParams` built with `id="task-4a8b3c2d"`, message wrapping the JSON text

→ **`RemoteAgentConnections.send_task(request, task_callback)`** → opens SSE stream to `http://securities-advisor-agent:10001/`

---

## Phase 9 — Sub-Agent Receives Task

**`AgentTaskManager.on_send_task_subscribe(request)`**

→ `utils.are_modalities_compatible(["text", "image/png"], SUPPORTED_CONTENT_TYPES)` → `True`

→ `self.upsert_task(request.params)` → task `"task-4a8b3c2d"` stored in memory

→ Returns `self._stream_generator(request)` (async generator)

**`AgentTaskManager._stream_generator(request)`**

→ `self._get_user_query(task_send_params)` → JSON string of `StructuredTaskPayload`

→ calls `self.agent.stream(query, user_id="user-0042", session_id="sess-9f3a1b2c")`

---

## Phase 10 — Context Enrichment

**`SecuritiesAdvisorAgentADK.stream(query, user_id, session_id)`**

→ `self.initialize()` → MCP tools connected, ADK runner ready (no-op if already done)

→ `self._ensure_session("sess-9f3a1b2c")` → ADK session retrieved

→ **`self.get_contexts_from_mongo(session_id="sess-9f3a1b2c", user_id="user-0042")`**

&emsp;→ **`get_contexts_notif_from_mongo("sess-9f3a1b2c")`** → `[]` (no system alerts)

&emsp;→ **`get_contexts_personalization_from_mongo("user-0042")`** → `[{expertise_level: "intermediate", jargon_allowed: true, tracking_watchlist: ["ACB","VCB","TCB"], tone_style: "professional"}]`

→ Context string prepended to query → enriched query passed to ADK runner.

---

## Phase 11 — Knowledge Files in System Prompt

**`SecuritiesAdvisorAgentADK._build_agent()`** (called once at startup)

→ Reads `funnel_logic.md`, `financial_logic.md`, `market_logic.md`, `chart_logic_key.md`, `statistic_logic.md` → concatenated into agent instruction

→ `LlmAgent` built with model `"Securities_Advisor_Agent"` via LiteLLM, 5 MCP tools + `grounded_web_search`.

---

## Phase 12 — before_model_callback (Sub-Agent)

**`SecuritiesAdvisorAgentADK.before_model_callback(callback_context, llm_request)`**

→ `settings.get_random_gemini_key(is_host=False)` → `"AIzaSyDO4Tjz..."` (rotated key set to env)

---

## Phase 13 — LLM Reasoning (Sub-Agent)

**Gemini 2.0-flash** via LiteLLM receives enriched query + system prompt (with `funnel_logic.md`).

→ LLM plans 3 tool calls: `get_market_info` → `get_indicator_info` → `get_chart_key`

→ First tool call emitted.

---

## Phase 14 — MCP Tool Call 1: get_market_info

**`get_market_info(symbol="ACB", mode="now", target_type="symbol")`** — MCP tool on `agent-data-api`

→ Queries PostgreSQL for ACB latest price & foreign trading data

→ Returns: `{symbol: "ACB", close: 22400, change_pct: +1.36%, volume: 4_820_000, foreign_net_buy: +4.3B VND}`

SSE progress event yielded to client: `{"is_task_complete": false, "updates": "Đang xử lý công cụ get_market_info..."}`

---

## Phase 15 — MCP Tool Call 2: get_indicator_info

**`get_indicator_info(symbol="ACB")`** — MCP tool on `agent-data-api`

→ **`TechnicalAnalyzer.technical_analyze("ACB")`** → queries `basement.aip_stock_watchlist_tcbs`

→ Returns:
```
{
  trend:   { direction: "uptrend", price_vs_sma200: "+5.9%", price_vs_ema50: "+1.9%" },
  momentum: { rsi_14: 58.3, macd_histogram: +43.5, price_vs_bb: "middle_band" },
  volume:  { obv_trend: "rising", vol_vs_ma20: 1.42 },
  system_signals: { tcbs_signal: "ACCUMULATE", composite_score: 72 }
}
```

SSE progress event yielded to client.

---

## Phase 16 — MCP Tool Call 3: get_chart_key

**`get_chart_key(ticket=["ACB"], chart_type="technical", indicators=["RSI","MACD"], mode="symbol", limit=60)`** — MCP tool on `agent-data-api`

→ Computes deterministic hash of chart config

→ Stores config in Redis with 30-min TTL

→ Returns: `{keyHash: "7f3e9a1b4c2d0e5f", status: "ready"}`

**`self.redis_manager.push_json_data(app_name="get_chart_key", session_id="sess-9f3a1b2c", hashkey="7f3e9a1b4c2d0e5f", data={...})`** → chart data persisted for frontend polling.

---

## Phase 17 — LLM Synthesises Final Response

**Gemini 2.0-flash** receives all three tool results.

→ Composes Vietnamese analysis response: trend commentary, RSI/MACD interpretation, volume signal, TCBS recommendation, chart reference `[chart_key: 7f3e9a1b4c2d0e5f]`

→ `is_final_response()` event fires.

---

## Phase 18 — A2A Result Streaming Back

**`AgentTaskManager._stream_generator()`**

→ Yields `SendTaskStreamingResponse` with `TaskStatusUpdateEvent(state=COMPLETED, message=<response text>)`

→ Yields `SendTaskStreamingResponse` with `TaskArtifactUpdateEvent(artifact=<response text>)`

→ Yields `SendTaskStreamingResponse` with `TaskStatusUpdateEvent(final=True)`

Total sub-agent time: **~4.1s**

---

## Phase 19 — Host Agent Processes Result

**`HostAgent.send_task()`** — A2A streaming loop completes

→ `convert_parts(task.status.message.parts, tool_context)` → `["**ACB — 2026-05-14...<full text>**"]`

→ `full_text` assembled, stored to `state["agent_output"]`

---

## Phase 20 — Background Cache Store

**`HostAgent.send_task()`** — after result assembled

→ `asyncio.create_task(store_in_background())` — non-blocking

→ **`TaskCacheService.store_cache(payload, target_agent="Securities_Advisor_Agent", response_data=full_text)`**

&emsp;→ `get_ttl_for_intent("analyze_stock_technical")` → `600` seconds

&emsp;→ Embeds `cache_key` via Jina v5 → 1024-dim dense + 256-dim MRL slice + BM25 sparse vectors

&emsp;→ `qdrant_client.upsert(collection="agent_task_cache_jina", points=[...], wait=False)` → cache entry stored with TTL=600s

---

## Phase 21 — Final Response Delivered

**`main.py`** returns HTTP response to client:

```json
{
  "status": "success",
  "session_id": "sess-9f3a1b2c",
  "response": "**ACB — 2026-05-14 (Thứ Tư)**\n\nGiá: 22,400 VND (+1.36%)...",
  "chart_key": "7f3e9a1b4c2d0e5f",
  "metadata": { "agent": "Securities_Advisor_Agent", "intent": "analyze_stock_technical", "cache_hit": false, "duration_ms": 4370 }
}
```

Frontend uses `chart_key` to poll Redis → renders RSI + MACD chart widget.

**Total end-to-end: ~4.4s**

---

## Timeline Summary

```
10:23:07.000  POST /send_message received
10:23:07.010  HostAgent.invoke() called
10:23:07.011  before_model_callback: key rotated, VN dates injected
10:23:07.012  Gemini 2.5-flash LLM call starts
10:23:07.480  LLM → send_task(Securities_Advisor_Agent, analyze_stock_technical)
10:23:07.481  StructuredTaskPayload built, cache_key computed
10:23:07.523  Qdrant search → score=0.61 → CACHE MISS
10:23:07.524  A2A HTTP stream → securities-advisor-agent:10001
10:23:07.531  AgentTaskManager._stream_generator() starts
10:23:07.532  get_contexts_notif_from_mongo() → [] (empty)
10:23:07.545  get_contexts_personalization_from_mongo() → user profile
10:23:07.546  before_model_callback: sub-agent key rotated
10:23:07.547  Gemini 2.0-flash LLM call starts
10:23:08.120  LLM → get_market_info("ACB")
10:23:08.298  PostgreSQL returns: close=22400, vol=4.82M, foreign_net=+4.3B
10:23:08.720  LLM → get_indicator_info("ACB")
10:23:08.949  TechnicalAnalyzer.technical_analyze() returns RSI=58.3, MACD_hist=+43.5
10:23:09.310  LLM → get_chart_key(["ACB"], "technical", ["RSI","MACD"])
10:23:09.399  keyHash="7f3e9a1b4c2d0e5f" stored in Redis
10:23:09.401  redis_manager.push_json_data() called
10:23:11.200  LLM synthesises final Vietnamese response
10:23:11.700  A2A TaskResult (COMPLETED) arrives at Host Agent
10:23:11.701  asyncio.create_task(store_cache) scheduled
10:23:11.710  HTTP response returned to client
10:23:11.820  (background) Qdrant upsert completed, TTL=600s
```

---

## Next Request: Cache Hit Scenario

Same user asks `"Phân tích kỹ thuật ACB 1 ngày"` within 10 minutes:

- **`HostAgent.send_task()`** → `payload.to_cache_key()` → same `cache_key`
- **`TaskCacheService.search_cache()`** → Qdrant score = `0.94` ≥ `0.80`, TTL not expired
- Returns cached `response_parts` immediately — **no LLM, no MCP, no DB calls**
- **Total time: ~80ms**
