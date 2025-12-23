
import logging


from typing import Dict, Any, Type, Optional, List

from agentic_tools.channels.activation import CHANNEL_ALIASES, NotificationChannel, normalize_channel_key
from agentic_tools.channels.facebook import FacebookPageChannel
from agentic_tools.channels.push_notification import MobilePushChannel, WebPushChannel
from agentic_tools.channels.zalo import ZaloOAChannel
from agentic_tools.channels.email import EmailChannel

# =====================================================
#  ACTIVATION CHANNELS
# =====================================================

logger = logging.getLogger("agentic_tools.marketing")



class ActivationManager:
    """Factory + registry for activation channels.

    Use `register_channel` to add new channels dynamically in tests or runtime.
    """

    # Canonical channel keys
    _channels: Dict[str, Type[NotificationChannel]] = {
        "email": EmailChannel,
        "zalo_oa": ZaloOAChannel,
        "mobile_push": MobilePushChannel,
        "web_push": WebPushChannel,
        "facebook_page": FacebookPageChannel,
    }

    @classmethod
    def register_channel(cls, key: str, channel_cls: Type[NotificationChannel]):
        """Register or override a channel handler by key."""
        cls._channels[key.lower()] = channel_cls
        logger.debug("Registered channel '%s' -> %s", key, channel_cls)

    @classmethod
    def list_channels(cls) -> Dict[str, Type[NotificationChannel]]:
        return dict(cls._channels)

    @classmethod
    def execute(cls, channel_key: str, segment: str, message: str, **kwargs: Any) -> Dict[str, Any]:
        raw = (channel_key or "").lower().strip()

        # Normalize incoming key (handles spaces, hyphens, compact forms)
        resolved = normalize_channel_key(raw)

        # If normalization didn't yield a registered canonical channel, fall back to previous heuristics
        if resolved not in cls._channels:
            # Direct alias lookup
            resolved = CHANNEL_ALIASES.get(raw, raw)

            # Try stripping common suffixes if not found
            if resolved not in cls._channels:
                for s in ("_push", "-push", " push", "_page", "-page", " page"):
                    if raw.endswith(s):
                        candidate = raw[: -len(s)]
                        resolved = CHANNEL_ALIASES.get(candidate, candidate)
                        if resolved in cls._channels:
                            break

            # Extra shorthand
            if resolved not in cls._channels and raw == "fb":
                resolved = CHANNEL_ALIASES.get("fb", "facebook_page")

        if resolved not in cls._channels:
            raise ValueError(f"Unsupported channel: {channel_key}")

        channel_class = cls._channels[resolved]

        try:
            return channel_class().send(segment, message, **kwargs)
        except Exception as exc:
            logger.exception("Channel %s failed: %s", channel_key, exc)
            return {"status": "error", "message": str(exc), "channel": resolved}

# =====================================================

def activate_channel(channel: str, segment_name: str, message: str, title: str = "Notification", timeout: Optional[int] = 6, retries: Optional[int] = None, **kwargs: Any) -> Dict[str, Any]:
    """
    LEO CDP activation tool for sending messages.

    Args:
        channel: Channel type (email, zalo, mobile_push, or web_push).
        segment_name: The target segment for activation.
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

    if not segment_name or not isinstance(segment_name, str):
        return {"status": "error", "message": "`segment_name` must be a non-empty string"}

    if not message or not isinstance(message, str):
        return {"status": "error", "message": "`message` must be a non-empty string"}

    # normalize channel (support alias and variants)
    resolved = normalize_channel_key(channel)

    if resolved not in ActivationManager.list_channels():
        return {"status": "error", "message": f"Unsupported channel: {channel}", "available": list(ActivationManager.list_channels().keys())}

    logger.info("Activating channel '%s' (resolved '%s') for segment '%s'", channel, resolved, segment_name)

    try:
        # Forward retries and any other provider-specific kwargs to the channel implementation
        merged_kwargs = dict(kwargs)
        merged_kwargs.setdefault("timeout", timeout)
        if retries is not None:
            merged_kwargs.setdefault("retries", retries)
        merged_kwargs.setdefault("title", title)

        return ActivationManager.execute(
            channel_key=resolved,
            segment=segment_name,
            message=message,
            **merged_kwargs,
        )
    except Exception as exc:
        logger.exception("activate_channel failed")
        return {"status": "error", "message": str(exc)}
