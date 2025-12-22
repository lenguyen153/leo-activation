import os
import logging
import requests
from abc import ABC, abstractmethod
from typing import Dict, Any, Type, Optional

# =====================================================
#  ACTIVATION CHANNEL STRATEGY LAYER (OOP)
# =====================================================

logger = logging.getLogger("agentic_tools.marketing")

# Channel alias map to support short names (e.g., 'zalo' -> 'zalo_oa')
CHANNEL_ALIASES = {
    "zalo": "zalo_oa",
    "facebook": "facebook_page",
}


class NotificationChannel(ABC):
    """Base strategy for all activation channels."""

    @abstractmethod
    def send(self, recipient_segment: str, message: str, **kwargs) -> Dict[str, Any]:
        """Send a message to a recipient segment.

        Returns a dict with at least a `status` key.
        """
        pass


class EmailChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        logger.info("[Email] Segment=%s | Message=%s", recipient_segment, message)
        # TODO: integrate real SMTP or transactional provider
        return {"status": "success", "channel": "email", "sent": 120}


class ZaloOAChannel(NotificationChannel):
    def __init__(self):
        self.api_url = os.getenv("ZALO_OA_API_URL", "https://openapi.zalo.me/v3.0/oa/message/cs")
        self.access_token = os.getenv("ZALO_OA_TOKEN")

    def send(self, recipient_segment: str, message: str, **kwargs):
        logger.info("[Zalo OA] Segment=%s", recipient_segment)

        if not self.access_token:
            return {"status": "error", "channel": "zalo_oa", "message": "ZALO_OA_TOKEN not set"}

        payload = {
            "recipient": recipient_segment,
            "message": message,
        }
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

        # Allow caller to override timeout
        timeout = kwargs.get("timeout", 6)

        try:
            resp = requests.post(self.api_url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            # Attempt to return the provider response where possible
            try:
                body = resp.json()
            except ValueError:
                body = {"status_code": resp.status_code, "text": resp.text}

            return {"status": "success", "channel": "zalo_oa", "response": body}

        except requests.exceptions.RequestException as exc:
            logger.error("ZaloOA request failed: %s", exc)
            return {"status": "error", "channel": "zalo_oa", "message": str(exc)}


class MobilePushChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        title = kwargs.get("title", "Notification")
        logger.info("[Mobile Push] Segment=%s | Title=%s", recipient_segment, title)
        # TODO: integrate with push provider
        return {"status": "success", "channel": "mobile_push"}


class WebPushChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        logger.info("[Web Push] Segment=%s", recipient_segment)
        return {"status": "success", "channel": "web_push"}


class FacebookPageChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        logger.info("[Facebook Page] Segment=%s", recipient_segment)
        return {"status": "success", "channel": "facebook_page"}


class ActivationManager:
    """Factory + registry for activation channels.

    Use `register_channel` to add new channels dynamically in tests or runtime.
    """

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
    def execute(cls, channel_key: str, segment: str, message: str, **kwargs) -> Dict[str, Any]:
        key = (CHANNEL_ALIASES.get(channel_key.lower()) or channel_key).lower()

        channel_class = cls._channels.get(key)
        if not channel_class:
            raise ValueError(f"Unsupported channel: {channel_key}")

        try:
            return channel_class().send(segment, message, **kwargs)
        except Exception as exc:
            logger.exception("Channel %s failed: %s", channel_key, exc)
            return {"status": "error", "message": str(exc), "channel": key}
    
# =====================================================


def activate_channel(channel: str, segment_name: str, message: str, title: str = "Notification", timeout: Optional[int] = 6) -> Dict[str, Any]:
    """
    LEO CDP activation tool for sending messages.

    Args:
        channel: Channel type (email, zalo, mobile_push, or web_push).
        segment_name: The target segment for activation.
        message: The content message to send.
        title: Optional title for push notifications.
        timeout: Optional timeout for network requests (in seconds).
        
    Returns:
        A dict with at least a `status` key indicating success or failure, generated message, and other info.
    """
    if not channel or not isinstance(channel, str):
        return {"status": "error", "message": "`channel` must be a non-empty string"}

    if not segment_name or not isinstance(segment_name, str):
        return {"status": "error", "message": "`segment_name` must be a non-empty string"}

    if not message or not isinstance(message, str):
        return {"status": "error", "message": "`message` must be a non-empty string"}

    # normalize channel (support alias)
    resolved = CHANNEL_ALIASES.get(channel.lower(), channel.lower())

    if resolved not in ActivationManager.list_channels():
        return {"status": "error", "message": f"Unsupported channel: {channel}", "available": list(ActivationManager.list_channels().keys())}

    logger.info("Activating channel '%s' (resolved '%s') for segment '%s'", channel, resolved, segment_name)

    try:
        return ActivationManager.execute(
            channel_key=resolved,
            segment=segment_name,
            message=message,
            title=title,
            timeout=timeout,
        )
    except Exception as exc:
        logger.exception("activate_channel failed")
        return {"status": "error", "message": str(exc)}
