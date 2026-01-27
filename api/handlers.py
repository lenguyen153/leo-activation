"""
API Route Handlers for LEO Activation Agent.

This module defines the FastAPI router that exposes:
1. /chat: Natural language interface (User -> Router -> Tools -> User).
2. /tool_calling: Direct programmatic execution of tools (App -> Tool -> Result).
3. /data/sync-segment: Direct endpoint to trigger profile synchronization (ArangoDB -> PGSQL).
4. /test/zalo-direct: Direct integration testing for Zalo.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

# --- IMPORTS ---
from agentic_models.router import AgentRouter
from agentic_tools.alert_center_tools import get_alert_types
from agentic_tools.customer_data_tools import show_all_segments
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
from data_workers.sync_segment_profiles import run_synch_profiles_async
from main_configs import DATA_SYNC_API_KEY

# Import the worker function from the original script
# Ensure your project structure allows this import
try:
    from data_workers.sync_segment_profiles import run_synch_profiles
except ImportError:
    # Fallback/Mock for development if the worker module isn't in pythonpath
    logging.warning("Could not import 'run_synch_profiles'. Sync features will fail if called.")
    def run_synch_profiles(segment_id: str):
        raise NotImplementedError("Worker module not found.")

import psycopg
from fastapi import Query, Depends
from data_workers.cdp_db_utils import get_users_by_ticker_interest
from data_utils.settings import DatabaseSettings

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
    """Schema for natural language chat requests."""
    prompt: Union[str, List[Dict[str, Any]]] = Field(
        ...,
        description="User query string OR a list of message history objects.",
        json_schema_extra={
            "example": "Sync profiles for the 'VIP Users' segment and send them a Zalo message."
        },
    )

class ToolCallingRequest(BaseModel):
    """Schema for direct tool execution requests."""
    tool_name: str = Field(..., description="The exact function name of the tool to execute.")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Dictionary of arguments to pass to the tool.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "tool_name": "sync_segment_to_db",
                "tool_args": {"segment_id": "seg_vip_users_01"}
            }
        }
    }

class SyncRequest(BaseModel):
    """Schema for direct data synchronization requests."""
    segment_id: str = Field(..., description="The ID of the segment to synchronize from ArangoDB to Postgres.")
    data_sync_api_key: Optional[str] = Field(
        None,
        description="API key for authenticating the sync request."
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
    """Standard response format for Chat and Tool Calling endpoints."""
    answer: str = Field(..., description="The natural language synthesis or direct result.")
    debug: DebugInfo = Field(..., description="Technical details of tool execution.")

class ZaloTestRequest(BaseModel):
    segment_name: str
    message: Optional[str] = None
    kwargs: Optional[Dict[str, Any]] = {}

class InterestedUserResponse(BaseModel):
    profile_id: str = Field(..., description="The Unique ID from CDP Profile")
    score: float = Field(..., description="Normalized Interest Score (0.0 - 1.0)")
    raw_points: float = Field(..., description="Actual accumulated raw points")

# Constants
HELP_DOCUMENTATION_URL = '<a href="https://leocdp.com/documents" target="_blank" rel="noopener noreferrer"> https://leocdp.com/documents </a>'
HELP_MESSAGE = f"Please refer to the documentation at {HELP_DOCUMENTATION_URL} for assistance."


# ============================================================
# New Tool Definition (Wrapper)
# ============================================================

def sync_segment_to_db(segment_id: str) -> str:
    """
    Synchronizes customer profiles from LEO CDP (ArangoDB) to the Activation Database (PostgreSQL).
    
    Use this tool when the user asks to "sync", "update", "refresh", or "import" data for a specific segment.
    
    Args:
        segment_id (str): The unique identifier of the segment to sync.
        
    Returns:
        str: A status message indicating success or failure.
    """
    try:
        logger.info(f"Agent triggering sync for segment: {segment_id}")
        run_synch_profiles(segment_id=segment_id)
        return f"Successfully synchronized profiles for segment '{segment_id}' from LEO CDP to PostgreSQL."
    except Exception as e:
        logger.exception(f"Sync failed for segment {segment_id}")
        return f"Failed to synchronize segment '{segment_id}'. Error: {str(e)}"


# ============================================================
# Router Setup
# ============================================================

def create_api_router(agent_router: AgentRouter) -> APIRouter:
    """
    Create and configure the FastAPI router.

    Args:
        agent_router: An initialized instance of AgentRouter.

    Returns:
        APIRouter: Configured router with chat, tool, and test endpoints.
    """
    router = APIRouter()

    # 1. Define the List of Tools available to the Agent
    # Added 'sync_segment_to_db' to the list so the AI knows about it.
    tools = [
        get_date,
        get_current_weather,
        get_marketing_events,
        get_alert_types,
        manage_cdp_segment,
        activate_channel,
        analyze_segment,
        show_all_segments,
        sync_segment_to_db  # <--- NEW TOOL REGISTERED HERE
    ]
    
    # 2. Map Tool Names to Actual Functions
    tools_map = AVAILABLE_TOOLS.copy()
    
    # Ensure local tools are in the map
    local_tools = {
        "show_all_segments": show_all_segments,
        "analyze_segment": analyze_segment,
        "sync_segment_to_db": sync_segment_to_db,  # <--- NEW TOOL MAPPED HERE
    }
    
    for name, func in local_tools.items():
        if name not in tools_map:
            tools_map[name] = func

    # ========================================================
    # 1. Direct Tool Calling Endpoint
    # ========================================================
    @router.post("/tool_calling", response_model=ChatResponse, summary="Execute a specific tool directly")
    async def tool_calling_endpoint(payload: ToolCallingRequest):
        try:
            logger.info("🔧 Direct Tool Call: %s | Args: %s", payload.tool_name, payload.tool_args)

            if payload.tool_name not in tools_map:
                raise HTTPException(status_code=400, detail=f"Tool '{payload.tool_name}' not found.")

            response = agent_router.handle_tool_calling(
                tool_calling_json={
                    "tool_name": payload.tool_name,
                    "args": payload.tool_args
                },
                tools=tools,
                tools_map=tools_map,
            )

            return ChatResponse(
                answer=response["answer"],
                debug=DebugInfo(
                    calls=[ToolCallDebug(**c) for c in response["debug"]["calls"]],
                    data=[ToolResultDebug(**d) for d in response["debug"]["data"]],
                ),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Tool calling endpoint failed unexpectedly")
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================
    # 2. Chat Endpoint (Agentic)
    # ========================================================
    @router.post("/chat", response_model=ChatResponse, summary="Natural Language Agent Interface")
    async def chat_endpoint(payload: ChatRequest):
        try:
            input_content = payload.prompt
            
            # --- HELP COMMAND SHORTCUT ---
            if isinstance(input_content, str):
                cleaned_prompt = input_content.strip()
                logger.info("Incoming chat prompt: %s", cleaned_prompt)
                
                if cleaned_prompt.lower() == "help":
                    return ChatResponse(
                        answer=HELP_MESSAGE,
                        debug=DebugInfo(calls=[], data=[]),
                    )
                messages = [{"role": "user", "content": cleaned_prompt}]
            
            elif isinstance(input_content, list):
                logger.info("Incoming chat history with %d messages", len(input_content))
                messages = input_content
            else:
                raise HTTPException(status_code=400, detail="Invalid prompt format.")

            # --- AGENT EXECUTION ---
            response = agent_router.handle_message(
                messages,
                tools=tools,
                tools_map=tools_map,
            )

            return ChatResponse(
                answer=response["answer"],
                debug=DebugInfo(
                    calls=[ToolCallDebug(**c) for c in response["debug"]["calls"]],
                    data=[ToolResultDebug(**d) for d in response["debug"]["data"]],
                ),
            )

        except Exception as e:
            logger.exception("Chat endpoint execution failed")
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================
    # 3. Data Synchronization Endpoint (Direct)
    # ========================================================
    @router.post("/data/sync-segment", summary="Trigger Profile Sync (Arango -> PGSQL)")
    async def sync_segment_endpoint(request: SyncRequest):
        """
        Direct endpoint to run the synchronization logic without Agent reasoning.
        Args:
            request (SyncRequest): Request body containing segment_id.
        Returns:
            dict: Status message with number of synced profiles.
        """
        
        """ e.g: Send HTTP POST to URL: http://0.0.0.0:8000/data/sync-segment 
            with body {"segment_id": "seg_vip_users_01","data_sync_api_key":"your_leocdp_api_key_here"} """
        
        try:
            if request.data_sync_api_key != DATA_SYNC_API_KEY:
                logger.warning("Unauthorized sync attempt with invalid API key.")
                raise HTTPException(status_code=401, detail="Invalid API key for data synchronization.")
            
            logger.info("🔄 Manual Sync triggered for segment: %s", request.segment_id)
            
            # Execute the worker function directly
            count = await run_synch_profiles_async(segment_id=request.segment_id)
            return {"status": "success", "synced": count}
            
        except Exception as e:
            logger.exception("Sync endpoint failed")
            raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

    # ========================================================
    # 4. Zalo Direct Test Endpoint
    # ========================================================
    @router.post("/test/zalo-direct", summary="Test Zalo Integration")
    async def test_zalo_direct(request: ZaloTestRequest):
        try:
            logger.info("Testing Zalo Direct for segment: %s", request.segment_name)
            zalo_channel = ZaloOAChannel()
            
            result = zalo_channel.send(
                recipient_segment=request.segment_name,
                message=request.message,
                **request.kwargs,
            )

            return {
                "status": "completed",
                "mode": "direct_test",
                "channel_response": result,
            }

        except Exception as e:
            logger.exception("Zalo direct test failed")
            raise HTTPException(status_code=500, detail=str(e))
        
    
    # ========================================================
    # 4. Audience Interest Endpoint
    # ========================================================
    # ### MODIFICATION: New dual score ###
    
    @router.get("/interested/{ticker}", response_model=List[InterestedUserResponse])
    async def get_interested_users_api(
        ticker: str,
        min_score: float = Query(0.5, description="Minimum normalized interest score (0.0 - 1.0)"),
        conn: psycopg.Connection = Depends(get_db)
    ):
        """
        Get users interested in a stock based on the new asymptotic scoring logic.
        
        - **ticker**: Stock Symbol (e.g., AAPL)
        - **min_score**: 0.0 to 1.0 (Default 0.5)
        """
        try:
            # 1. Clean inputs
            clean_ticker = ticker.upper().strip()
            
            # 2. Call repository
            results = get_users_by_ticker_interest(conn, clean_ticker, min_score)
            
            # 3. Map DB results to Pydantic Model
            response_data = []
            for row in results:
                response_data.append({
                    # ### MODIFIED: Mapping new DB columns to JSON ###
                    "profile_id": row['profile_id'],
                    "score": row['interest_score'], 
                    "raw_points": row['raw_score'],
                    "last_interaction": str(row['last_interaction']) 
                })
                
            return response_data

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


