import logging
import re
from typing import Dict, Any, Type, Optional, List, Literal

from agentic_tools.channels.activation import NotificationChannel
from agentic_tools.channels.facebook import FacebookPageChannel
from agentic_tools.channels.push_notification import MobilePushChannel, WebPushChannel
from agentic_tools.channels.zalo import ZaloOAChannel
from agentic_tools.channels.email import EmailChannel

logger = logging.getLogger("agentic_tools.marketing_tools")

# ============================================================
# Global Channel Registry
# ============================================================

CHANNEL_REGISTRY: Dict[str, Type[NotificationChannel]] = {
    "email": EmailChannel,
    "zalo_oa": ZaloOAChannel,
    "mobile_push": MobilePushChannel,
    "web_push": WebPushChannel,
    "facebook_page": FacebookPageChannel,
}

# Mapping of all possible user inputs to the canonical keys above
CHANNEL_ALIASES = {
    "zalo": "zalo_oa", "zalo_oa": "zalo_oa", "zalo_push": "zalo_oa", "zalooa": "zalo_oa",
    "facebook": "facebook_page", "facebook_page": "facebook_page", "facebookpage": "facebook_page", 
    "fb": "facebook_page", "fb_page": "facebook_page",
    "email": "email", "email_channel": "email",
    "mobile_push": "mobile_push", "mobile_notification": "mobile_push",
    "web_push": "web_push", "web_notification": "web_push",
}

def normalize_channel_key(key: str) -> str:
    """
    Normalizes human/LLM input into a canonical channel key.
    Example: 'Zalo OA' -> 'zalo_oa'
    """
    if not key or not isinstance(key, str):
        return ""
    
    raw = key.lower().strip()
    
    # 1. Direct Alias Check
    if raw in CHANNEL_ALIASES:
        resolved = CHANNEL_ALIASES[raw]
        logger.debug("Channel normalization (alias): '%s' -> '%s'", key, resolved)
        return resolved

    # 2. Pattern Cleaning (Remove spaces/hyphens)
    clean_variants = [
        raw.replace(" ", "_"),
        raw.replace("-", "_"),
        re.sub(r"[^a-z0-9]", "", raw) # Compact form: "zalooa"
    ]

    for v in clean_variants:
        if v in CHANNEL_ALIASES:
            resolved = CHANNEL_ALIASES[v]
            logger.debug("Channel normalization (fuzzy): '%s' -> '%s'", key, resolved)
            return resolved
        if v in CHANNEL_REGISTRY:
            logger.debug("Channel normalization (clean): '%s' -> '%s'", key, v)
            return v

    logger.warning("Channel normalization failed for key: '%s'", key)
    return raw

# ============================================================
# Activation Manager
# ============================================================

class ActivationManager:
    """Factory for dispatching messages to various notification channels."""

    @classmethod
    def list_channels(cls) -> List[str]:
        """Returns list of canonical channel names."""
        return list(CHANNEL_REGISTRY.keys())

    @classmethod
    def execute(
        cls,
        channel_key: str,
        segment: str,
        message: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        # Normalize within execute to ensure internal calls are safe
        resolved = normalize_channel_key(channel_key)

        if resolved not in CHANNEL_REGISTRY:
            error_msg = f"Unknown channel '{channel_key}'. Valid options: {cls.list_channels()}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        channel_cls = CHANNEL_REGISTRY[resolved]

        try:
            logger.debug("Initializing channel class: %s", channel_cls.__name__)
            # Instance and send
            response = channel_cls().send(
                recipient_segment=segment,
                message=message,
                **kwargs,
            )
            logger.info("Channel '%s' execution successful.", resolved)
            return response
        except Exception as exc:
            logger.exception("Execution failed for channel: %s", resolved)
            return {
                "status": "error",
                "channel": resolved,
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            }

# =====================================================
# Tool Definition for Gemma / LLMs
# =====================================================

def activate_channel(
    channel: Literal["email", "zalo_oa", "mobile_push", "web_push", "facebook_page"], 
    recipient_segment: str, 
    message: str, 
    title: str = "Notification", 
    timeout: int = 6, 
    retries: Optional[int] = 3, 
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Activates a specific marketing channel to send a message to a target segment.

    Args:
        channel: The delivery method. Must be one of 'email', 'zalo_oa', 'mobile_push', 'web_push', 'facebook_page'.
        recipient_segment: The name or ID of the customer segment (e.g., 'VIP_Customers').
        message: The actual text content to be sent.
        title: The headline/title (primarily used for push notifications).
        timeout: Maximum seconds to wait for the request to complete. Default is 6.
        retries: Number of times to attempt re-sending if the first attempt fails.
        kwargs: Specific provider settings like 'page_id', 'template_id', or 'image_url'.

    Returns:
        A dictionary containing 'status' (success/error) and execution metadata.
    """
    # 1. Start Logging
    logger.info("Tool 'activate_channel' called. Channel: '%s', Segment: '%s'", channel, recipient_segment)
    logger.debug("Tool 'activate_channel' params: title='%s', timeout=%s, retries=%s, kwargs=%s", title, timeout, retries, kwargs)

    # 2. Validation for LLM-induced errors
    if not channel:
        err = "The 'channel' parameter is required."
        logger.error(err)
        return {"status": "error", "message": err}
    
    # 3. Normalization
    resolved = normalize_channel_key(channel)
    if resolved not in ActivationManager.list_channels():
         # Fail fast if normalization didn't find a registry match
        err = f"Channel '{channel}' resolved to '{resolved}' which is not in registry."
        logger.error(err)
        return {
            "status": "error", 
            "message": f"Invalid channel '{channel}'. Valid options: {ActivationManager.list_channels()}"
        }

    # 4. Execution
    try:
        # Prepare configuration
        config = {
            "title": title,
            "timeout": timeout,
            "retries": retries,
            **kwargs
        }
        
        logger.debug("Dispatching to ActivationManager with resolved channel: %s", resolved)

        result = ActivationManager.execute(
            channel_key=resolved,
            segment=recipient_segment,
            message=message,
            **config
        )
        return result

    except Exception as e:
        logger.exception("Tool 'activate_channel' crashed unexpectedly.")
        return {
            "status": "error", 
            "message": str(e),
            "hint": f"Ensure channel is one of {ActivationManager.list_channels()}"
        }
        

def get_marketing_events(tenant_id: Optional[str] = None) -> Dict[str, str]:
    """
    show all marketing events for the given tenant.

    Args:
        tenant_id: the unique identifier for the tenant. If None, defaults to the current tenant.

    Returns:
        A list of marketing events with their IDs and names.
    """

    logger.info("show all marketing events for the given tenant_id: %s", tenant_id)

    # TODO: Replace with real API call to fetch marketing events
    marketing_events = [{"event_id": "me_001", "name": "Summer Sale 2026"},
                        {"event_id": "me_002", "name": "Black Friday 2026"},
                        {"event_id": "me_003", "name": "New Year Promo 2026"},
                        {"event_id": "me_004", "name": "Back to School 2026"},
                        {"event_id": "me_005", "name": "Holiday Specials 2026"},
                        {"event_id": "me_006", "name": "Flash Deals 2026"}
                ]
    return marketing_events