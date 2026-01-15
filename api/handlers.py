"""API route handlers for chat and testing endpoints."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agentic_models.router import AgentRouter, build_messages
from agentic_tools.tools import (
    AVAILABLE_TOOLS,
    activate_channel,
    get_current_weather,
    get_date,
    manage_leo_segment,
)
from agentic_tools.channels.zalo import ZaloOAChannel

logger = logging.getLogger("LEO Activation API")


# ============================================================
# Schemas
# ============================================================
class ChatRequest(BaseModel):
    prompt: str = Field(
        ...,
        description="User natural language query",
        json_schema_extra={
            "example": "Send a Zalo message to users active last week"
        },
    )


class ToolCallDebug(BaseModel):
    name: str
    arguments: Dict[str, Any]


class ToolResultDebug(BaseModel):
    name: str
    response: Any


class DebugInfo(BaseModel):
    calls: list[ToolCallDebug]
    data: list[ToolResultDebug]


class ChatResponse(BaseModel):
    answer: str
    debug: DebugInfo


class ZaloTestRequest(BaseModel):
    segment_name: str
    message: Optional[str] = None
    kwargs: Optional[Dict[str, Any]] = {}


# ============================================================
# Router Setup
# ============================================================
def create_api_router(agent_router: AgentRouter) -> APIRouter:
    """
    Create and configure API router with all endpoints.

    Args:
        agent_router: Configured AgentRouter instance

    Returns:
        APIRouter with all chat and test endpoints
    """
    router = APIRouter()

    # Tool configuration
    tools = [
        get_date,
        get_current_weather,
        manage_leo_segment,
        activate_channel,
    ]
    tools_map = AVAILABLE_TOOLS

    # ========================================================
    # Chat Endpoint
    # ========================================================
    @router.post("/chat", response_model=ChatResponse)
    async def chat_endpoint(payload: ChatRequest):
        """
        Main chat endpoint for agent interactions.

        Accepts a natural language prompt and returns an agent response
        with tool execution details.
        """
        try:
            logger.info("Incoming prompt: %s", payload.prompt)

            messages = build_messages(payload.prompt)
            response = agent_router.handle_message(
                messages,
                tools=tools,
                tools_map=tools_map,
            )

            return ChatResponse(
                answer=response["answer"],
                debug=DebugInfo(
                    calls=[ToolCallDebug(**c)
                           for c in response["debug"]["calls"]],
                    data=[ToolResultDebug(**d)
                          for d in response["debug"]["data"]],
                ),
            )

        except Exception as e:
            logger.exception("Chat endpoint failed")
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================
    # Zalo Direct Test Endpoint
    # ========================================================
    @router.post("/test/zalo-direct")
    async def test_zalo_direct(request: ZaloTestRequest):
        """
        Directly calls the Zalo channel with full parameter support.

        Useful for testing Zalo integration without agent routing.
        """
        try:
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
            raise HTTPException(status_code=500, detail=str(e))

    return router
