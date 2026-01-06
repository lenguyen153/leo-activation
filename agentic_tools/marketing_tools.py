
import logging


from typing import Dict, Any, Type, Optional, List

from agentic_tools.channels.activation import NotificationChannel
from agentic_tools.channels.facebook import FacebookPageChannel
from agentic_tools.channels.push_notification import MobilePushChannel, WebPushChannel
from agentic_tools.channels.zalo import ZaloOAChannel
from agentic_tools.channels.email import EmailChannel

# =====================================================
#  ACTIVATION CHANNELS
# =====================================================

logger = logging.getLogger("agentic_tools.marketing")


# ============================================================
# Global Channel Registry (single source of truth)
# ============================================================

CHANNEL_REGISTRY: Dict[str, Type[NotificationChannel]] = {
    "email": EmailChannel,
    "zalo_oa": ZaloOAChannel,
    "mobile_push": MobilePushChannel,
    "web_push": WebPushChannel,
    "facebook_page": FacebookPageChannel,
}

# Channel alias map to support short names and common variants
CHANNEL_ALIASES = {
    # Zalo variants
    "zalo": "zalo_oa",
    "zalo_oa": "zalo_oa",
    "zalo_push": "zalo_oa",
    "zalooa": "zalo_oa",

    # Facebook variants
    "facebook": "facebook_page",
    "facebook_page": "facebook_page",
    "facebookpage": "facebook_page",
    "facebook_push": "facebook_page",
    "fb": "facebook_page",
    "fb_page": "facebook_page",

    # Email variants
    "email": "email",
    "email_channel": "email",
    
    # Push Notification variants
    "mobile_push": "mobile_push",
    "mobile_notification": "mobile_push",
    "web_push": "web_push",
    "web_notification": "web_push",
}

def normalize_channel_key(key: str) -> str:
    """Normalize incoming channel names to canonical keys.

    Handles common variants with spaces, hyphens, and compact forms (e.g. "Zalo OA", "zalo-oa", "ZaloOA").
    Returns either a canonical channel key (e.g. "zalo_oa"), or a normalized string the caller can use to look up mappings.
    """
    if not key or not isinstance(key, str):
        return ""
    raw = key.lower().strip()

    # Direct alias mapping if present
    mapped = CHANNEL_ALIASES.get(raw)
    if mapped:
        return mapped

    # Try common variants
    variants = {
        raw.replace(" ", "_"),
        raw.replace(" ", ""),
        raw.replace("-", "_"),
        raw.replace("-", ""),
        raw.replace(" ", "_").replace("-", "_"),
    }

    for v in variants:
        mapped = CHANNEL_ALIASES.get(v)
        if mapped:
            return mapped
        # If variant is itself a canonical channel key (e.g. "zalo_oa"), return it
        if v in ActivationManager.list_channels():
            return v

    # Fallback: strip non-alphanumeric to compact form ("zalooa", "facebookpage")
    import re
    compact = re.sub(r"[^a-z0-9]", "", raw)
    mapped = CHANNEL_ALIASES.get(compact)
    if mapped:
        return mapped

    # Nothing matched — return the lowercased raw to let callers apply additional heuristics
    return raw

# ============================================================
# Activation Manager
# ============================================================

class ActivationManager:
    """
    Factory + dispatcher for activation channels.

    CHANNEL_REGISTRY is the canonical source.
    This class provides orchestration, normalization, and execution.
    """

    @classmethod
    def register_channel(cls, key: str, channel_cls: Type[NotificationChannel]) -> None:
        """
        Register or override a channel handler by key.
        Safe for tests and runtime extensions.
        """
        normalized = key.lower().strip()
        CHANNEL_REGISTRY[normalized] = channel_cls
        logger.debug("Registered channel '%s' -> %s", normalized, channel_cls)

    @classmethod
    def list_channels(cls) -> Dict[str, Type[NotificationChannel]]:
        """Return a shallow copy of registered channels."""
        return dict(CHANNEL_REGISTRY)

    @classmethod
    def execute(
        cls,
        channel_key: str,
        segment: str,
        message: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raw = (channel_key or "").lower().strip()

        # 1️⃣ Normalize canonical key
        resolved = normalize_channel_key(raw)

        # 2️⃣ Alias fallback
        if resolved not in CHANNEL_REGISTRY:
            resolved = CHANNEL_ALIASES.get(raw, raw)

        # 3️⃣ Heuristic suffix stripping
        if resolved not in CHANNEL_REGISTRY:
            for suffix in ("_push", "-push", " push", "_page", "-page", " page"):
                if raw.endswith(suffix):
                    candidate = raw[: -len(suffix)]
                    resolved = CHANNEL_ALIASES.get(candidate, candidate)
                    if resolved in CHANNEL_REGISTRY:
                        break

        # 4️⃣ Extra shorthand
        if resolved not in CHANNEL_REGISTRY and raw == "fb":
            resolved = CHANNEL_ALIASES.get("fb", "facebook_page")

        if resolved not in CHANNEL_REGISTRY:
            raise ValueError(f"Unsupported channel: {channel_key}")

        channel_cls = CHANNEL_REGISTRY[resolved]

        try:
            return channel_cls().send(
                recipient_segment=segment,
                message=message,
                **kwargs,
            )
        except Exception as exc:
            logger.exception("Channel '%s' execution failed", resolved)
            return {
                "status": "error",
                "channel": resolved,
                "message": str(exc),
            }
            
# =====================================================

def activate_channel(channel: str, recipient_segment: str, message: str, title: str = "Notification", timeout: Optional[int] = 6, retries: Optional[int] = None, **kwargs: Any) -> Dict[str, Any]:
    """
    LEO CDP activation tool for sending messages.

    Args:
        channel: Channel type (email, zalo, mobile_push, or web_push).
        recipient_segment: The target segment name or the ID for activation.
        message: The content message to send.
        title: Optional title for push notifications.
        timeout: Optional timeout for network requests (in seconds).
        retries: Optional number of retry attempts for network channels.
        kwargs: Additional provider-specific keyword arguments forwarded to channel implementations (e.g. `provider`, `page_id`, `retries`).

    Returns:
        A dict with at least a `status` key indicating success or failure, generated message, and other info.
    """
    if not channel or not isinstance(channel, str):
        return {"status": "error", "message": "`channel` must be a non-empty string"}

    if not recipient_segment or not isinstance(recipient_segment, str):
        return {"status": "error", "message": "`recipient_segment` must be a non-empty string"}

    if not message or not isinstance(message, str):
        return {"status": "error", "message": "`message` must be a non-empty string"}

    # normalize channel (support alias and variants)
    resolved = normalize_channel_key(channel)

    # Verify supported channel
    channels = ActivationManager.list_channels()
    if resolved not in channels:
        return {"status": "error", "message": f"Unsupported channel: {channel}", "available": list(channels.keys())}

    logger.info("Activating channel '%s' (resolved '%s') for segment '%s'", channel, resolved, recipient_segment)

    try:
        # Forward retries and any other provider-specific kwargs to the channel implementation
        merged_kwargs = dict(kwargs)
        merged_kwargs.setdefault("timeout", timeout)
        if retries is not None:
            merged_kwargs.setdefault("retries", retries)
        merged_kwargs.setdefault("title", title)

        return ActivationManager.execute(
            channel_key=resolved,
            segment=recipient_segment,
            message=message,
            **merged_kwargs,
        )
    except Exception as exc:
        logger.exception("activate_channel failed")
        return {"status": "error", "message": str(exc)}
