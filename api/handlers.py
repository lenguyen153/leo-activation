"""
API Route Handlers for LEO Activation Agent.

This module defines the FastAPI router that exposes:
1. /chat: Natural language interface (User -> Router -> Tools -> User).
2. /tool_calling: Direct programmatic execution of tools (App -> Tool -> Result).
3. /test/zalo-direct: Direct integration testing for Zalo.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

# --- IMPORTS ---
# Ensure these imports point to your actual project structure
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

logger = logging.getLogger("LEO Activation API")


# ============================================================
# Data Models (Schemas)
# ============================================================

class ChatRequest(BaseModel):
    """Schema for natural language chat requests."""
    prompt: Union[str, List[Dict[str, Any]]] = Field(
        ...,
        description="User query string OR a list of message history objects.",
        json_schema_extra={
            "example": "Send a Zalo message to users active last week"
        },
    )

class ToolCallingRequest(BaseModel):
    """Schema for direct tool execution requests."""
    tool_name: str = Field(..., description="The exact function name of the tool to execute.")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Dictionary of arguments to pass to the tool.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "tool_name": "analyze_segment",
                "tool_args": {"segment_identifier": "New Users"}
            }
        }
    }

class ToolCallDebug(BaseModel):
    """Debug info: What tool did the AI try to call?"""
    name: str
    arguments: Dict[str, Any]

class ToolResultDebug(BaseModel):
    """Debug info: What did the tool return?"""
    name: str
    response: Any

class DebugInfo(BaseModel):
    calls: List[ToolCallDebug]
    data: List[ToolResultDebug]

class ChatResponse(BaseModel):
    """Standard response format for both Chat and Tool Calling endpoints."""
    answer: str = Field(..., description="The natural language synthesis or direct result.")
    debug: DebugInfo = Field(..., description="Technical details of tool execution.")

class ZaloTestRequest(BaseModel):
    segment_name: str
    message: Optional[str] = None
    kwargs: Optional[Dict[str, Any]] = {}

# Constants
HELP_DOCUMENTATION_URL = '<a href="https://leocdp.com/documents" target="_blank" rel="noopener noreferrer"> https://leocdp.com/documents </a>'
HELP_MESSAGE = f"Please refer to the documentation at {HELP_DOCUMENTATION_URL} for assistance."


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
    # NOTE: FunctionGemma needs these functions to generate the schema.
    # Ensure all these functions have proper docstrings.
    tools = [
        get_date,
        get_current_weather,
        get_marketing_events,
        get_alert_types,
        manage_cdp_segment,
        activate_channel,
        analyze_segment,
        show_all_segments
    ]
    
    # 2. Map Tool Names to Actual Functions
    # We update the base AVAILABLE_TOOLS with any local imports to ensure coverage
    tools_map = AVAILABLE_TOOLS.copy()
    
    # Verify imports that might not be in AVAILABLE_TOOLS yet
    if "show_all_segments" not in tools_map:
        tools_map["show_all_segments"] = show_all_segments
    if "analyze_segment" not in tools_map:
        tools_map["analyze_segment"] = analyze_segment

    # ========================================================
    # 1. Direct Tool Calling Endpoint
    # ========================================================
    @router.post("/tool_calling", response_model=ChatResponse, summary="Execute a specific tool directly")
    async def tool_calling_endpoint(payload: ToolCallingRequest):
        """
        Bypasses the Intent Detection (Router) layer and directly executes a specific tool.
        
        Useful for:
        - UI buttons that trigger specific actions.
        - Testing specific tools without relying on LLM interpretation.
        """
        try:
            logger.info("🔧 Direct Tool Call: %s | Args: %s", payload.tool_name, payload.tool_args)

            # Validate tool existence before calling router to save overhead
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
        """
        Main entry point for the LEO Agent.
        
        Process:
        1. User Input -> 2. Router (FunctionGemma) -> 3. Tool Execution -> 4. Synthesis (Gemini)
        """
        try:
            # Handle list inputs (Message History) vs String inputs
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
                
                # Standardize to Message Format
                messages = [{"role": "user", "content": cleaned_prompt}]
            
            elif isinstance(input_content, list):
                logger.info("Incoming chat history with %d messages", len(input_content))
                messages = input_content
            else:
                raise HTTPException(status_code=400, detail="Invalid prompt format. Must be string or list of messages.")

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
    # 3. Zalo Direct Test Endpoint
    # ========================================================
    @router.post("/test/zalo-direct", summary="Test Zalo Integration")
    async def test_zalo_direct(request: ZaloTestRequest):
        """
        Directly calls the Zalo channel driver.
        Bypasses Agent, Router, and Tool wrappers. Pure connectivity test.
        """
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

    return router