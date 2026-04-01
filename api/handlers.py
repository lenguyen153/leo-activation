"""
API Route Handlers for LEO Activation Agent.
"""

import logging
from typing import Any, Dict, List, Optional, Union

import psycopg
from fastapi import APIRouter, HTTPException, Body, Path, Query, Depends
from pydantic import BaseModel, Field

# --- IMPORTS ---
from agentic_models.router import AgentRouter
from agentic_tools.alert_center_tools import get_alert_types
from agentic_tools.customer_data_tools import show_all_segments, sync_segment_to_db
from agentic_tools.data_enrichment_tools import analyze_segment
from agentic_tools.marketing_tools import get_marketing_events
from agentic_tools.tools import (
    AVAILABLE_TOOLS,
    activate_channel,
    get_current_weather,
    get_date,
    manage_cdp_segment,
)
from agentic_tools.channels.zalo import ZaloOAChannel
from data_workers.sync.sync_segment_profiles import run_synch_profiles_async
from data_workers.sync.sync_segment_profiles import run_synch_profiles
from main_configs import DATA_SYNC_API_KEY

from api.recommendation_system import router as rec_router
from api.portfolio import router as portfolio_router
from api.notification import router as notification_router
from api.user_events import router as user_events_router
from fastapi.responses import FileResponse

# --- DB UTILS ---
# We need these for the /interested endpoint
# from data_workers.repositories.pg_profile_repository import get_users_by_ticker_interest
from data_utils.settings import DatabaseSettings

# Import the worker function for sync
try:
    from data_workers.sync.sync_segment_profiles import run_synch_profiles
except ImportError:
    logging.warning("Could not import 'run_synch_profiles'. Sync features will fail if called.")
    def run_synch_profiles(segment_id: str):
        raise NotImplementedError("Worker module not found.")

logger = logging.getLogger("LEO Activation API")

# --- Database Dependency ---
def get_db():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    try:
        yield conn
    finally:
        conn.close()


# ============================================================
# Data Models (Schemas)
# ============================================================

class ChatRequest(BaseModel):
    prompt: Union[str, List[Dict[str, Any]]] = Field(..., description="User query or history")

class ToolCallingRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any] = {}

class SyncRequest(BaseModel):
    segment_id: str
    data_sync_api_key: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    debug: Any

class ZaloTestRequest(BaseModel):
    segment_name: str
    message: Optional[str] = None
    kwargs: Optional[Dict[str, Any]] = {}

class InterestedUserResponse(BaseModel):
    profile_id: str
    score: float
    raw_points: float
    last_interaction: Optional[str] = None

class UserProfileInterestResponse(BaseModel):
    """Schema for the 360-view profile endpoint"""
    profile_id: Optional[str] = None
    identities: List[str] = Field(default_factory=list)
    primary_email: Optional[str] = None
    raw_scores: Dict[str, float]
    interest_scores: Dict[str, float]
    segments: List[str]

# Constants
HELP_DOCUMENTATION_URL = '<a href="https://leocdp.com/documents" target="_blank"> https://leocdp.com/documents </a>'
HELP_MESSAGE = f"Please refer to the documentation at {HELP_DOCUMENTATION_URL}"


# ============================================================
# New Tool Definition
# ============================================================

def sync_segment_to_db(segment_id: str) -> str:
    try:
        logger.info(f"Agent triggering sync for segment: {segment_id}")
        run_synch_profiles(segment_id=segment_id)
        return f"Successfully synchronized profiles for segment '{segment_id}'."
    except Exception as e:
        logger.exception(f"Sync failed for segment {segment_id}")
        return f"Failed to synchronize segment '{segment_id}'. Error: {str(e)}"


# ============================================================
# Router Setup
# ============================================================

def create_api_router(agent_router: AgentRouter) -> APIRouter:
    router = APIRouter()

    # 1. Tools Setup
    tools = [
        get_date, get_current_weather, get_marketing_events, get_alert_types,
        manage_cdp_segment, activate_channel, analyze_segment, show_all_segments,
        sync_segment_to_db
    ]
    
    tools_map = AVAILABLE_TOOLS.copy()
    local_tools = {
        "show_all_segments": show_all_segments,
        "analyze_segment": analyze_segment,
        "sync_segment_to_db": sync_segment_to_db,
    }
    for name, func in local_tools.items():
        if name not in tools_map:
            tools_map[name] = func
    
    router.include_router(rec_router)
    router.include_router(portfolio_router)
    router.include_router(notification_router)
    router.include_router(user_events_router)

    # --------------------------------------------------------
    # 1. Tool Calling
    # --------------------------------------------------------
    @router.post("/tool_calling", response_model=ChatResponse)
    async def tool_calling_endpoint(payload: ToolCallingRequest):
        try:
            if payload.tool_name not in tools_map:
                raise HTTPException(status_code=400, detail=f"Tool '{payload.tool_name}' not found.")
            
            response = agent_router.handle_tool_calling(
                tool_calling_json={"tool_name": payload.tool_name, "args": payload.tool_args},
                tools=tools, tools_map=tools_map
            )
            return ChatResponse(answer=response["answer"], debug=response["debug"])
        except Exception as e:
            logger.exception("Tool calling failed")
            raise HTTPException(status_code=500, detail=str(e))

    # --------------------------------------------------------
    # 2. Chat
    # --------------------------------------------------------
    @router.post("/chat", response_model=ChatResponse)
    async def chat_endpoint(payload: ChatRequest):
        try:
            input_content = payload.prompt
            if isinstance(input_content, str):
                if input_content.strip().lower() == "help":
                    return ChatResponse(answer=HELP_MESSAGE, debug={})
                messages = [{"role": "user", "content": input_content.strip()}]
            else:
                messages = input_content

            response = agent_router.handle_message(messages, tools=tools, tools_map=tools_map)
            return ChatResponse(answer=response["answer"], debug=response["debug"])
        except Exception as e:
            logger.exception("Chat failed")
            raise HTTPException(status_code=500, detail=str(e))

    # --------------------------------------------------------
    # 3. Sync
    # --------------------------------------------------------
    @router.post("/data/sync-segment")
    async def sync_segment_endpoint(request: SyncRequest):
        if request.data_sync_api_key != DATA_SYNC_API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")
        count = await run_synch_profiles_async(segment_id=request.segment_id)
        return {"status": "success", "synced": count}

    # --------------------------------------------------------
    # 4. Zalo Test
    # --------------------------------------------------------
    @router.post("/test/zalo-direct")
    async def test_zalo_direct(request: ZaloTestRequest):
        zalo = ZaloOAChannel()
        res = zalo.send(request.segment_name, request.message, **request.kwargs)
        return {"status": "completed", "channel_response": res}
    
    # ==========================================
    # 🛑 ZALO DOMAIN VERIFICATION HACK
    # Replace the route and the return string below 
    # with the EXACT filename and code Zalo gave you!
    # ==========================================
    # @router.get("/zalo_verifierRuMR1OMoCovmZODmYxaHH7Mfe4wPtt4OE3ao.html")
    # async def verify_zalo_domain():
    #     # This is the secret string Zalo expects to see inside the file!
    #     # (If you opened the file they gave you and the text inside is different, replace it here)
    #     return FileResponse("zalo_verifierRuMR1OMoCovmZODmYxaHH7Mfe4wPtt4OE3ao.html")
        
    return router


