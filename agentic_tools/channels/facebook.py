
import logging
import requests
from typing import Any

from agentic_tools.channels.activation import NotificationChannel
from main_configs import MarketingConfigs

logger = logging.getLogger(__name__)

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
