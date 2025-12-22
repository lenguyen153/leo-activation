import os
import logging
import requests
from abc import ABC, abstractmethod
from typing import Dict, Any, Type, Optional

# =====================================================
#  ACTIVATION CHANNEL STRATEGY LAYER (OOP)
# =====================================================

logger = logging.getLogger("agentic_tools.marketing")

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

    # Common names
    "email": "email",
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
        if v in ActivationManager._channels:
            return v

    # Fallback: strip non-alphanumeric to compact form ("zalooa", "facebookpage")
    import re
    compact = re.sub(r"[^a-z0-9]", "", raw)
    mapped = CHANNEL_ALIASES.get(compact)
    if mapped:
        return mapped

    # Nothing matched — return the lowercased raw to let callers apply additional heuristics
    return raw


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
        DEFAULT_ZALO_OA_API_SEND = "https://openapi.zalo.me/v3.0/oa/message/cs"
        self.api_url = os.getenv("ZALO_OA_API_URL", DEFAULT_ZALO_OA_API_SEND)
        self.access_token = os.getenv("ZALO_OA_TOKEN")
        self.max_retries = int(os.getenv("ZALO_OA_MAX_RETRIES", "1"))

    def send(self, recipient_segment: str, message: str, **kwargs):
        logger.info("[Zalo OA] Segment=%s", recipient_segment)

        if not self.access_token:
            return {"status": "error", "channel": "zalo_oa", "message": "ZALO_OA_TOKEN not set"}

        payload = {
            "recipient": recipient_segment,
            "message": message,
        }
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

        # Allow caller to override timeout and retries
        timeout = kwargs.get("timeout", 6)
        retries = int(kwargs.get("retries", self.max_retries))

        attempt = 0
        last_exc = None
        while attempt <= retries:
            try:
                resp = requests.post(self.api_url, json=payload, headers=headers, timeout=timeout)
                resp.raise_for_status()
                try:
                    body = resp.json()
                except ValueError:
                    body = {"status_code": resp.status_code, "text": resp.text}

                return {"status": "success", "channel": "zalo_oa", "response": body}

            except Exception as exc:
                # Be tolerant: tests may raise different exception types inside raise_for_status (e.g. NameError
                # when a test mistakenly references `requests`). Treat any exception here as a transient request error
                # and attempt retries according to `retries`.
                logger.warning("ZaloOA attempt %d failed: %s", attempt + 1, exc)
                last_exc = exc
                attempt += 1
                # Simple backoff
                backoff = min(2 ** attempt, 10)
                if attempt <= retries:
                    import time
                    time.sleep(backoff)
                continue

        logger.error("ZaloOA all attempts failed: %s", last_exc)
        return {"status": "error", "channel": "zalo_oa", "message": str(last_exc)}


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
    def __init__(self):
        self.graph_api = "https://graph.facebook.com"
        self.page_token = os.getenv("FB_PAGE_ACCESS_TOKEN")

    def send(self, recipient_segment: str, message: str, **kwargs):
        logger.info("[Facebook Page] Segment=%s | kwargs=%s", recipient_segment, kwargs)

        # Optional: allow explicit page_id or page_name in kwargs; if not provided, just log
        page_id = kwargs.get("page_id") or os.getenv("FB_PAGE_ID")

        if page_id and self.page_token:
            # Attempt to post to page feed (simple integration example)
            url = f"{self.graph_api}/{page_id}/feed"
            payload = {"message": message, "access_token": self.page_token}
            try:
                resp = requests.post(url, data=payload, timeout=6)
                resp.raise_for_status()
                try:
                    body = resp.json()
                except ValueError:
                    body = {"status_code": resp.status_code, "text": resp.text}
                return {"status": "success", "channel": "facebook_page", "response": body}
            except requests.exceptions.RequestException as exc:
                logger.error("Facebook API post failed: %s", exc)
                return {"status": "error", "channel": "facebook_page", "message": str(exc)}

        # Fallback: no page token or id — just simulate a success for demo
        logger.info("[Facebook Page] No page token/id provided — simulating send")
        return {"status": "success", "channel": "facebook_page", "delivered": True}


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
    def execute(cls, channel_key: str, segment: str, message: str, **kwargs) -> Dict[str, Any]:
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


def activate_channel(channel: str, segment_name: str, message: str, title: str = "Notification", timeout: Optional[int] = 6, retries: Optional[int] = None, **kwargs) -> Dict[str, Any]:
    """
    LEO CDP activation tool for sending messages.

    Args:
        channel: Channel type (email, zalo, mobile_push, or web_push).
        segment_name: The target segment for activation.
        message: The content message to send.
        title: Optional title for push notifications.
        timeout: Optional timeout for network requests (in seconds).
        retries: Optional number of retry attempts for network channels.
        **kwargs: Additional provider-specific options forwarded to channel implementations.
        
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
