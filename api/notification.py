"""
Omnichannel Notification API — routes for sending notifications
via the external adminnotify service.
"""

import logging
from typing import Any, Dict

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from main_configs import MarketingConfigs

logger = logging.getLogger(__name__)

# ============================================================
# Topic mapping
# ============================================================

TOPIC_MAPPING: Dict[str, int] = {
    "RISK_MANAGEMENT": 300,
    "INVESTMENT_ADVICE": 301,
    "MARKET_INFO": 302,
    "ASSISTANT_NOTIFICATION": 400,
}

# ============================================================
# Pydantic Schemas
# ============================================================


class NotificationRequest(BaseModel):
    """
    Caller sends user_id + data dict.
    data follows the structure:
    {
      "Data": {
        "type": "ASSISTANT_NOTIFICATION",
        "content": { "title": "...", "body": "..." }
      }
    }
    """
    user_id: str = Field(..., description="Username của người nhận", example="inno01")
    data: Dict[str, Any] = Field(..., description="Push data payload")


# ============================================================
# Shared HTTPX client (created lazily, closed on shutdown)
# ============================================================

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=MarketingConfigs.ADMINNOTIFY_BASE_URL)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ============================================================
# Router
# ============================================================

router = APIRouter(prefix="/notification", tags=["notification"])


@router.post("/send", status_code=200)
async def send_notification(request: NotificationRequest):
    """
    Nhận request nội bộ và chuyển tiếp sang adminnotify external.
    Caller chỉ cần truyền user_id + data dict.
    Subject, Content, TopicCode được tự động extract từ data.
    """
    data = request.data
    data_inner = data.get("Data", {})
    content_obj = data_inner.get("content", {})

    topic_code = TOPIC_MAPPING.get(data_inner.get("type"), 302)
    subject = content_obj.get("title", "Thông báo mới")
    content = content_obj.get("body", "")

    message: Dict[str, Any] = {
        "NotifyType": [3],
        "SendTo": request.user_id,
        "TopicCode": topic_code,
        "Subject": subject,
        "Content": content,
        "Language": 1,
        "Push": data,
    }

    request_body = {
        "RType": "SendNotification",
        "Messages": [message],
    }

    client = _get_client()

    try:
        response = await client.post(
            MarketingConfigs.ADMINNOTIFY_ENDPOINT,
            json=request_body,
        )
        response.raise_for_status()

        logger.info(
            "[ADMINNOTIFY] Sent | user=%s | topic=%s | status=%s",
            request.user_id,
            topic_code,
            response.status_code,
        )
        return {"status": "success", "message": "Notification sent successfully"}

    except httpx.HTTPStatusError as e:
        logger.error(
            "[ADMINNOTIFY] HTTP error | user=%s | topic=%s | status=%s | body=%s",
            request.user_id,
            topic_code,
            e.response.status_code,
            e.response.text[:300],
        )
        raise HTTPException(status_code=502, detail="External notification server error")

    except httpx.RequestError as e:
        logger.error("[ADMINNOTIFY] Request error | user=%s | error=%s", request.user_id, e)
        raise HTTPException(status_code=503, detail="Unable to connect to external notification server")
