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
from agentic_models.router import AgentRouter

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

# Agent router decides how to process messages (intent detection, execution, synthesis)
agent_router = AgentRouter(mode="auto")

# Available tools (name -> callable mapping) used during execution
TOOLS = [
    get_date,
    get_current_weather,
    manage_leo_segment,
    activate_channel,
]

TOOLS_MAP = AVAILABLE_TOOLS  # mapping of tool name to callable used by the router

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

        # Delegate to AgentRouter to orchestrate detection, execution and synthesis
        response = agent_router.handle_message(messages, tools=TOOLS, tools_map=TOOLS_MAP)

        # Build ChatResponse from AgentRouter result
        debug_calls = [ToolCallDebug(**c) for c in response["debug"]["calls"]]
        debug_data = [ToolResultDebug(**d) for d in response["debug"]["data"]]

        return ChatResponse(
            answer=response["answer"],
            debug=DebugInfo(calls=debug_calls, data=debug_data),
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
