import time
import json
import logging
from typing import Any, Dict, List

from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ============================================================
# Domain Imports
# ============================================================
from agentic_models.router import LLMRouter
from agentic_models.function_gemma import FunctionGemmaEngine

from agentic_tools.tools import (
    AVAILABLE_TOOLS,
    get_date,
    get_current_weather,
    manage_leo_segment,
    activate_channel,
)

# ============================================================
# Logging Configuration
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LeoCDPAgent")

# ============================================================
# App Initialization
# ============================================================
app = FastAPI(
    title="Resynap720 – LEO CDP API",
    description="High-accuracy Agentic Interface for LEO CDP (Gemma + Gemini)",
    version="1.2.0",
)

# ============================================================
# CORS Configuration
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Static & Template Setup ===
# --- File Paths ---
BASE_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = BASE_DIR / "agentic_resources"
TEMPLATES_DIR = RESOURCES_DIR / "templates"

app.mount("/resources", StaticFiles(directory=RESOURCES_DIR), name="resources")
app.state.templates = Jinja2Templates(directory=TEMPLATES_DIR)

# === Core UI Routes ===
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Root index page for the chatbot demo.
    Loads from Jinja2 template (index.html).
    """
    ts = int(time.time())
    data = {"request": request, "timestamp": ts}
    templates = request.app.state.templates
    return templates.TemplateResponse("test.html", data)

# ============================================================
# Engine Initialization
# ============================================================

# Router decides which model to use
llm_router = LLMRouter(mode="auto")

# We still need Gemma directly for tool-call extraction
tool_engine = FunctionGemmaEngine()

TOOLS = [
    get_date,
    get_current_weather,
    manage_leo_segment,
    activate_channel,
]

# ============================================================
# Request / Response Models
# ============================================================

class ChatRequest(BaseModel):
    prompt: str = Field(
        ...,
        description="User natural language query",
        example="Send a Zalo message to users active last week"
    )

class ToolCallDebug(BaseModel):
    name: str
    arguments: Dict[str, Any]

class ToolResultDebug(BaseModel):
    name: str
    response: Any

class DebugInfo(BaseModel):
    calls: List[ToolCallDebug]
    data: List[ToolResultDebug]

class ChatResponse(BaseModel):
    answer: str
    debug: DebugInfo



# ============================================================
# Chat Endpoint
# ============================================================

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Agentic execution pipeline:

    1. Gemma → intent + tool selection
    2. Execute tools
    3. Gemini → semantic synthesis
    """

    messages = [
        {
            "role": "system",
            "content": (
                "You are LEO, a smart model that can do function calling with tools."
                "Use tools immediately when applicable. "
                "Do not ask for confirmation if parameters are clear. "
                "Explain errors plainly."
            ),
        },
        {
            "role": "user",
            "content": request.prompt,
        },
    ]

    try:
        logger.info(f"Incoming prompt: {request.prompt}")

        # ====================================================
        # 1. TOOL INTENT DETECTION (Gemma only)
        # ====================================================
        raw_output = llm_router.generate(messages, TOOLS)
        tool_calls = llm_router.extract_tool_calls(raw_output) or []
        debug_calls: List[ToolCallDebug] = []
        debug_results: List[ToolResultDebug] = []

      
        # ====================================================
        # 2. EXECUTE TOOLS
        # ====================================================
        logger.info(f"Executing {len(tool_calls)} tool(s)")

        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"type": "function", "function": call}
                for call in tool_calls
            ],
        })

        tool_outputs_for_llm = []

        for call in tool_calls:
            name = call["name"]
            args = call.get("arguments", {})
            
            debug_calls.append(ToolCallDebug(name=name, arguments=args))

            if name not in AVAILABLE_TOOLS:
                result = {"error": f"Tool '{name}' not registered"}
            else:
                try:
                    result = AVAILABLE_TOOLS[name](**args)
                except Exception as exc:
                    logger.error(f"Tool {name} failed: {exc}")
                    result = {"error": str(exc)}

            debug_results.append(
                ToolResultDebug(name=name, response=result)
            )

            tool_outputs_for_llm.append({
                "role": "tool",
                "name": name,
                "content": json.dumps(result, default=str),
            })

        messages.extend(tool_outputs_for_llm)

        # ====================================================
        # 3. FINAL SYNTHESIS (Gemini preferred)
        # ====================================================
        final_answer = llm_router.generate(messages, TOOLS)

        return ChatResponse(
            answer=final_answer,
            debug=DebugInfo(
                calls=debug_calls,
                data=debug_results,
            ),
        )

    except Exception as e:
        logger.exception("Fatal error in chat endpoint")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Local Dev Entry
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
