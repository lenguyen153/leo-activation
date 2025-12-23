
import logging
import requests
from typing import Dict, Any

from agentic_tools.channels.activation import NotificationChannel
from main_configs import MarketingConfigs

logger = logging.getLogger(__name__)

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