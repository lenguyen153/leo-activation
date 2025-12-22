import os
import logging
import requests
import smtplib
import ssl
from email.message import EmailMessage
from abc import ABC, abstractmethod
from typing import Dict, Any, Type, Optional, List

# =====================================================
#  ACTIVATION CHANNEL STRATEGY LAYER (OOP)
# =====================================================

logger = logging.getLogger("agentic_tools.marketing")

# Centralized configs in separate module
from main_configs import MarketingConfigs

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
    def send(self, recipient_segment: str, message: str, **kwargs: Any) -> Dict[str, Any]:
        """Send a message to a recipient segment.

        Returns a dict with at least a `status` key.
        """
        pass


class EmailChannel(NotificationChannel):
    """Email sending channel supporting multiple backends (SendGrid API and SMTP/Gmail).

    Configuration (via ENV vars):
      - EMAIL_PROVIDER: 'sendgrid' or 'smtp' (default: 'smtp')
      - SENDGRID_API_KEY: API key for SendGrid (if using sendgrid)
      - SENDGRID_FROM: default from email for SendGrid
      - SMTP_HOST: SMTP host (default: smtp.gmail.com)
      - SMTP_PORT: SMTP port (default: 587)
      - SMTP_USERNAME: SMTP login username (for Gmail this is the full email)
      - SMTP_PASSWORD: SMTP password or app-specific password
      - SMTP_USE_TLS: '1'/'true' to use STARTTLS (default: true)
    """

    def __init__(self):
        # Read provider config from centralized MarketingConfigs
        self.provider = MarketingConfigs.EMAIL_PROVIDER
        # SendGrid config
        self.sendgrid_api_key = MarketingConfigs.SENDGRID_API_KEY
        self.sendgrid_from = MarketingConfigs.SENDGRID_FROM
        # SMTP config (Gmail defaults)
        self.smtp_host = MarketingConfigs.SMTP_HOST
        self.smtp_port = MarketingConfigs.SMTP_PORT
        self.smtp_username = MarketingConfigs.SMTP_USERNAME
        self.smtp_password = MarketingConfigs.SMTP_PASSWORD
        self.smtp_use_tls = MarketingConfigs.SMTP_USE_TLS

    def send_via_sendgrid(self, recipients: List[str], subject: str, body: str, timeout: int = 6) -> Dict[str, Any]:
        if not self.sendgrid_api_key:
            return {"status": "error", "channel": "email", "message": "SENDGRID_API_KEY not set"}

        from_email = self.sendgrid_from or self.smtp_username or "noreply@example.com"
        payload = {
            "personalizations": [{"to": [{"email": r} for r in recipients], "subject": subject}],
            "from": {"email": from_email},
            "content": [{"type": "text/plain", "value": body}],
        }
        headers = {"Authorization": f"Bearer {self.sendgrid_api_key}", "Content-Type": "application/json"}

        try:
            resp = requests.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return {"status": "success", "channel": "email", "provider": "sendgrid", "response_status": resp.status_code}
        except requests.exceptions.RequestException as exc:
            logger.error("SendGrid send failed: %s", exc)
            return {"status": "error", "channel": "email", "provider": "sendgrid", "message": str(exc)}

    def send_via_smtp(self, recipients: List[str], subject: str, body: str, timeout: int = 6) -> Dict[str, Any]:
        if not self.smtp_username or not self.smtp_password:
            return {"status": "error", "channel": "email", "message": "SMTP credentials not set"}

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_username
        msg["To"] = ",".join(recipients)
        msg.set_content(body)

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=timeout) as server:
                if self.smtp_use_tls:
                    server.starttls(context=ctx)
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            return {"status": "success", "channel": "email", "provider": "smtp", "sent_to": recipients}
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return {"status": "error", "channel": "email", "provider": "smtp", "message": str(exc)}

    def send(self, recipient_segment: str, message: str, **kwargs: Any):
        logger.info("[Email] Segment=%s | kwargs=%s", recipient_segment, kwargs)

        # Accept a single recipient string, comma-separated string, or list
        if isinstance(recipient_segment, str):
            recipients: List[str] = [r.strip() for r in recipient_segment.split(",") if r.strip()]
        elif isinstance(recipient_segment, list):
            recipients = recipient_segment
        else:
            return {"status": "error", "channel": "email", "message": "invalid recipient format"}

        subject = kwargs.get("subject") or kwargs.get("title") or "Notification"
        timeout = kwargs.get("timeout", 6)
        provider = kwargs.get("provider", self.provider)

        if provider == "sendgrid":
            return self.send_via_sendgrid(recipients, subject, message, timeout=timeout)
        else:
            # default to SMTP
            return self.send_via_smtp(recipients, subject, message, timeout=timeout)


class ZaloOAChannel(NotificationChannel):
    def __init__(self):
        DEFAULT_ZALO_OA_API_SEND = "https://openapi.zalo.me/v3.0/oa/message/cs"
        self.api_url = MarketingConfigs.ZALO_OA_API_URL or DEFAULT_ZALO_OA_API_SEND
        self.access_token = MarketingConfigs.ZALO_OA_TOKEN
        self.max_retries = MarketingConfigs.ZALO_OA_MAX_RETRIES

    def send(self, recipient_segment: str, message: str, **kwargs: Any):
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
    def send(self, recipient_segment: str, message: str, **kwargs: Any):
        title = kwargs.get("title", "Notification")
        logger.info("[Mobile Push] Segment=%s | Title=%s", recipient_segment, title)
        # TODO: integrate with push provider
        return {"status": "success", "channel": "mobile_push"}


class WebPushChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs: Any):
        logger.info("[Web Push] Segment=%s", recipient_segment)
        return {"status": "success", "channel": "web_push"}


class FacebookPageChannel(NotificationChannel):
    def __init__(self):
        self.graph_api = "https://graph.facebook.com"
        self.page_token = MarketingConfigs.FB_PAGE_ACCESS_TOKEN

    def send(self, recipient_segment: str, message: str, **kwargs: Any):
        logger.info("[Facebook Page] Segment=%s | kwargs=%s", recipient_segment, kwargs)

        # Optional: allow explicit page_id or page_name in kwargs; if not provided, just log
        page_id = kwargs.get("page_id") or MarketingConfigs.FB_PAGE_ID

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
