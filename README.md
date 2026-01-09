# LEO Activation Engine for AI-driven Marketing Automation (AMA)

LEO Activation is an intelligent backend service designed to bridge the gap between complex Customer Data Platforms (CDP) and marketing teams. By leveraging **Google's FunctionGemma-270M**, it provides a conversational AI interface for the [LEO CDP Framework](https://github.com/trieu/leo-cdp-framework), allowing users to manage segments and trigger omnichannel marketing activations through natural language.

![Screenshot: LEO Activation Framework](leo-activation-framework.png)

## 🚀 Overview

LEO Activation combines a function-calling-first LLM (FunctionGemma) with a semantic fallback (Gemini) to create a robust, production-oriented agent for the LEO CDP. The runtime implements a guarded four-step flow:

1. **Intent & Tool Selection (FunctionGemma)** — FunctionGemma is used for high-accuracy structured function calls; it emits special function call tags that are parsed and executed by the backend.
2. **Execute Tools (Developer Turn)** — Registered tools (e.g., segment management, activations, weather lookup) are executed and their results appended back into the conversation.
3. **Synthesis (Gemini/Router)** — The `LLMRouter` prefers FunctionGemma for tool-heavy requests and uses Gemini for higher-level semantic synthesis.
4. **Final Response** — The platform returns a human-friendly confirmation along with debug information about tool calls and results.

> Note: FunctionGemma requires the developer/system prompt "You are a model that can do function calling with the following functions" to reliably produce tool calls. The `FunctionGemmaEngine` contains robust parsing and casting helpers to convert the model's function-format into Python calls.

## ✨ Key Features

* **Structured Function Calling** 🔁 — Uses `google/functiongemma-270m-it` for deterministic, high-accuracy tool invocation. The repo includes specialized parsing and casting logic to map calls into Python functions.
* **Hybrid LLM Routing** 🔀 — `LLMRouter` auto-selects FunctionGemma for structured, tool-oriented turns and Gemini for semantic or long-form synthesis.
* **Conversational Segmentation** 🧾 — `manage_leo_segment` lets you create/update/delete segments via natural language tooling.
* **Omnichannel Activation (Strategy Layer)** 📣 — `ActivationManager` supports `email`, `zalo_oa`, `mobile_push`, `web_push`, and `facebook_page` channels through an OOP strategy pattern (`marketing_tools.py`).
* **Weather-aware Personalization** ☀️🌧️ — `get_current_weather` integrates with Open‑Meteo to resolve city names and fetch current weather for conditional campaign logic.
* **Background Workers & Embeddings** 🧠 — `data-workers/embedding_worker.py` processes embedding jobs and updates DB rows (with a placeholder embedding generator ready for replacement by real providers).
* **Extensible Tools Registry** 🧩 — Tools are registered in `agentic_tools/AVAILABLE_TOOLS`; each tool follows a docstring-constrained schema for predictability.
* **Dev & Infra Scripts** ⚙️ — `shell-scripts/` and `sql-scripts/` provide convenience helpers (`start-dev.sh`, `start-pgsql.sh`, `schema.sql`) and test data in `test-api/`.

---

These updates reflect current behavior in `main.py`, `agentic_models/`, `agentic_tools/`, and `data-workers/`.

---

## 🔁 AgentRouter — core orchestration

**AgentRouter** is the centralized runtime that handles incoming chat, decides whether to call tools, executes them, and synthesizes a final reply.

How it works (summary):

1. **Intent & Tool Selection** — `FunctionGemma` is used to detect actionable intent and to emit structured function calls (the FunctionGemma tag format is parsed by the engine).
2. **Execute Tools** — The router executes tools using a `tools_map` (string → callable). Each callable is invoked with keyword arguments parsed from the model output.
3. **Synthesize Final Reply** — `Gemini` is used to generate the human-facing response that incorporates tool outputs and diagnostics.

Type expectations:

* `messages: List[Dict[str, Any]]` — the chat history; each message contains `role` and `content`.
* `tools: Optional[List[Any]]` — model-facing tool declarations (used by FunctionGemma for function-call generation).
* `tools_map: Dict[str, Callable[..., Any]]` — execution mapping; keys are tool names (strings) and values are callables that accept the expected kwargs.
* Return value: `Dict[str, Any]` with `{"answer": str, "debug": {"calls": [...], "data": [...]}}`.

Quick example:

```python
from agentic_models.router import AgentRouter
from agentic_tools.tools import AVAILABLE_TOOLS

agent = AgentRouter(mode="auto")

messages = [
  {"role": "system", "content": "You are LEO, a model that can call tools."},
  {"role": "user", "content": "Send a Zalo message to High Value users: 'Exclusive offer!'"},
]

# Tools declarations (passed to the model for function generation)
tools = []

# Execution mapping: name -> callable (e.g., 'activate_channel')
tools_map = AVAILABLE_TOOLS

result = agent.handle_message(messages, tools=tools, tools_map=tools_map)
print(result["answer"])
print(result["debug"])  # calls & results
```

> Tip: Unit tests patch `AgentRouter.gemma` and `AgentRouter.gemini` to avoid external model/API calls — this makes it easy to assert behavior and tool interactions.

## 🛠️ Installation & Setup

### 1. Prerequisites

* Python 3.10+
* Hugging Face account with access to [google/functiongemma-270m-it](https://huggingface.co/google/functiongemma-270m-it).
* A valid Hugging Face Access Token.

### 2. Create Virtual Environment

```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate

```

### 3. Install Dependencies

```bash
pip install -r requirements.txt

```

*Note: Ensure `torch` and `transformers` are installed as required for the FunctionGemma model.*

## ⚙️ Configuration

Create a `.env` file in the root directory:

```text
HUGGINGFACE_TOKEN=your_huggingface_token
ZALO_OA_TOKEN=your_zalo_token
LEO_CDP_API_URL=http://your-leo-cdp-instance:8080

```

### main_configs.py & sample configuration

This project centralizes environment-based configuration in `main_configs.py` (a thin wrapper that reads environment variables). Add the following environment variables to control LLM models and marketing integrations. Copy the sample below to a `.env` file or set them in your environment.

```text
# Model configuration
GEMINI_MODEL_ID=gemini-2.5-flash-lite
GEMINI_API_KEY=your_gemini_api_key

# SendGrid / SMTP (Email)
EMAIL_PROVIDER=smtp            # or 'sendgrid'
SENDGRID_API_KEY=your_sendgrid_api_key
SENDGRID_FROM=no-reply@yourdomain.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@yourdomain.com
SMTP_PASSWORD=your_smtp_password_or_app_password
SMTP_USE_TLS=1

# Zalo OA
ZALO_OA_TOKEN=your_zalo_token
ZALO_OA_API_URL=https://openapi.zalo.me/v3.0/oa/message/cs
ZALO_OA_MAX_RETRIES=2

# Facebook Page
FB_PAGE_ACCESS_TOKEN=your_facebook_page_token
FB_PAGE_ID=your_facebook_page_id

# Optional helpers
HUGGINGFACE_TOKEN=your_huggingface_token
LEO_CDP_API_URL=http://your-leo-cdp-instance:8080

```

Notes:
- `main_configs.py` reads these variables at import time and exposes them as constants/classes used across the app.
- The env var `GEMINI_MODEL_ID` is read into the code as `GEMINI_MODEL_ID` in `main_configs.py` (used by the Gemini engine).
- Some tests under `test-api/` (e.g. `test-api/simple_test.py`) perform live HTTP requests and may fail when external endpoints are unavailable; consider mocking these in CI or skipping network-dependent tests.
- For Gmail SMTP, prefer an app-specific password or OAuth; do not commit secrets to the repository.
- You can override provider-specific options at runtime by passing kwargs to `activate_channel` (e.g. `activate_channel("email", "user@example.com", "Hello", provider="sendgrid", retries=1)`).

## 🚀 Running the Platform

Launch the FastAPI server:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000

```

## 💬 Usage Example

![Screenshot: LEO Activation UI](screenshot.png)

*Screenshot: chat demo and activation flow.*

The platform expects an **Essential System Prompt** to activate the model's function-calling logic:
*`"You are a model that can do function calling with the following functions"`*.

**Endpoint**: `POST /chat`
**Payload**:

```json
{
  "prompt": "Create a segment for 'High Value' users and send them a Zalo message saying 'Exclusive offer just for you!'"
}

```

## 📁 Project Structure

Below is the current repository layout with brief descriptions of the primary files and folders:

* **Top-level files**
  * `main.py` — FastAPI orchestrator implementing the FunctionGemma cycle and HTTP endpoints.
  * `main_configs.py` — centralized, environment-driven configuration used across the app.
  * `README.md` — This documentation.
  * `requirements.txt` — Python dependencies.

* **Directories**
  * `agentic_models/` 🔧 — Model wrappers, routers and engines used to load FunctionGemma/Gemma models and handle function-calling behavior (e.g., `base.py`, `function_gemma.py`, `gemini.py`, `model_engine.py`, `router.py`).
  * `agentic_resources/` 🗂️ — Static resources and frontend templates (contains `js/` and `templates/`).
  * `agentic_tools/` 🛠️ — LEO CDP tools and activation strategies (e.g., `customer_data_tools.py`, `marketing_tools.py`, `weather_tools.py`, `datetime_tools.py`, `tools.py`).
  * `data-workers/` 🧰 — Background and asynchronous workers (e.g., `embedding_worker.py`) for tasks like embeddings and batch processing.
  * `sql-scripts/` 💾 — Database schema and SQL helper scripts (e.g., `schema.sql`).
  * `shell-scripts/` 📜 — Convenience scripts to start services and local infra (e.g., `start-dev.sh`, `start-pgsql.sh`).
  * `test-api/` 🧪 — Test assets and simple test scripts (e.g., `sample_data.sql`, `sample_multilingual.sql`, `simple_test.py`).

* **Ignored / generated**
  * `__pycache__/` — Python bytecode cache (auto-generated).

---

*For more information on the underlying technology, refer to the [Fine-tuning with FunctionGemma](https://ai.google.dev/gemma/docs/functiongemma/finetuning-with-functiongemma) documentation.*

## Ref Notebooks 


* https://ai.google.dev/gemma/docs/functiongemma
* [FunctionGemma_(270M).ipynb](https://colab.research.google.com/drive/1_ZGgidJ6mDv_TUsVLhHW6o1cymlyKU3q?usp=sharing)
* [Finetune_FunctionGemma_270M_for_Mobile_Actions_with_Hugging_Face.ipynb](https://colab.research.google.com/drive/1gTfKRvdvgx7HbsjOpPgVrIiSX0ANp8XR?usp=sharing)
* [Full-function-calling-sequence-with-functiongemma.ipynb](https://colab.research.google.com/drive/17IaGL-KuB3XKuVaJGf5OXVy8dJQPSk74?usp=sharing)
* https://ollama.com/library/functiongemma