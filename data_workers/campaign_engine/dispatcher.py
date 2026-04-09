"""
Channel dispatcher — ALL notifications are sent through the internal
POST /notification/send API, which forwards to the external adminnotify hub.

Flow:
  Engine → dispatch_message() → POST /notification/send → adminnotify external

The engine runs as a standalone script (crontab), so it calls the
FastAPI notification endpoint via HTTP.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# The base URL of our own FastAPI server (notification API lives here)
_INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://localhost:8000")


class DeliveryStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    RETRY = "pending_retry"


def resolve_base_account_id(conn, profile_id: str) -> str | None:
    """
    Resolve profile_id → base_account_id via the portfolios table.
    Returns the first base_account_id found, or None.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT base_account_id FROM portfolios WHERE profile_id = %s LIMIT 1",
            (profile_id,),
        )
        row = cur.fetchone()
    return row["base_account_id"] if row else None


def _build_notification_payload(
    base_account_id: str,
    message_config: dict,
    rule_id: str,
) -> dict[str, Any]:
    """
    Build the request body for POST /notification/send.

    Matches the notification hub's expected Push payload format:
    {
      "Push": {
        "Data": {
          "notification_id": "...",
          "user_id": "...",
          "created_at": "...",
          "type": "...",
          "content": {"title": "...", "body": "..."},
          "action": { ... }
        }
      }
    }
    """
    topic_type = message_config.get("topic_type", "ASSISTANT_NOTIFICATION")
    title = message_config.get("title", message_config.get("subject", "Thông báo mới"))
    body = message_config.get("body", "")
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    push_data = {
        "Data": {
            "notification_id": f"CDP-{uuid.uuid4()}",
            "user_id": base_account_id,
            "created_at": now_iso,
            "type": topic_type,
            "content": {
                "title": title,
                "body": body,
            },
        }
    }

    # Include action if provided in message_config
    action = message_config.get("action")
    if action:
        push_data["Data"]["action"] = action

    return {
        "base_account_id": base_account_id,
        "data": push_data,
    }


def _send_via_notification_api(payload: dict) -> dict[str, Any]:
    """
    Call POST /notification/send on our internal FastAPI server.
    This is the single gateway for all campaign notifications.
    """
    url = f"{_INTERNAL_API_URL}/notification/send"

    with httpx.Client(timeout=15) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()

    return resp.json()


def dispatch_message(
    channel: str,
    profile: dict,
    message_config: dict,
    conn=None,
    rule_id: str = "",
    template_row: dict | None = None,
    **kwargs,
) -> tuple[DeliveryStatus, dict[str, Any]]:
    """
    Send a notification through POST /notification/send.
    Returns (status, provider_response).
    All exceptions are caught and mapped to DeliveryStatus.
    """
    # Apply template rendering if a template is provided
    rendered_config = dict(message_config)
    if template_row and template_row.get("body_template"):
        from agentic_tools.channels.helpers import MessageRenderer
        renderer = MessageRenderer()
        rendered_config["body"] = renderer.render(template_row["body_template"], profile=profile)
        if template_row.get("subject_template"):
            rendered_config["title"] = renderer.render(template_row["subject_template"], profile=profile)

    try:
        # Resolve base_account_id from portfolios table
        profile_id = profile.get("profile_id", "")
        base_account_id = None
        if conn:
            base_account_id = resolve_base_account_id(conn, profile_id)

        if not base_account_id:
            logger.warning("[Dispatch] No base_account_id for profile=%s, skipping", profile_id)
            return DeliveryStatus.FAILED, {"error": "no_base_account_id", "profile_id": profile_id}

        payload = _build_notification_payload(base_account_id, rendered_config, rule_id)
        result = _send_via_notification_api(payload)

        if result.get("status") == "success":
            return DeliveryStatus.SENT, result
        return DeliveryStatus.FAILED, result

    except httpx.HTTPStatusError as e:
        logger.error(
            "[Dispatch] HTTP %s from notification API: %s",
            e.response.status_code, e.response.text[:200],
        )
        if e.response.status_code >= 500:
            return DeliveryStatus.RETRY, {"error": str(e), "status_code": e.response.status_code}
        return DeliveryStatus.FAILED, {"error": str(e), "status_code": e.response.status_code}

    except (httpx.RequestError, ConnectionError, TimeoutError) as e:
        logger.error("[Dispatch] Cannot reach notification API: %s", e)
        return DeliveryStatus.RETRY, {"error": str(e)}

    except Exception as e:
        logger.error("[Dispatch] Unexpected error: %s", e)
        return DeliveryStatus.FAILED, {"error": str(e)}


def log_delivery(
    conn,
    tenant_id: str,
    rule_id: str,
    profile_id: str,
    channel: str,
    status: str,
    provider_response: dict,
    today_str: str,
) -> None:
    """Insert a row into delivery_log for audit."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO delivery_log
                (tenant_id, marketing_event_id, profile_id, channel,
                 delivery_status, provider_response, sent_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                f"campaign_rule_{rule_id}_{today_str}",
                profile_id,
                channel,
                status,
                json.dumps(provider_response),
                datetime.now(timezone.utc) if status == "sent" else None,
            ),
        )
    conn.commit()
