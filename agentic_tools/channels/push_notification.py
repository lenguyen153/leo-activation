

import logging
import requests
from typing import Dict, Any

from agentic_tools.channels.activation import NotificationChannel
from main_configs import MarketingConfigs

logger = logging.getLogger(__name__)

# ============================================================
PUSH_PROVIDER = MarketingConfigs.PUSH_PROVIDER
FCM_PROJECT_ID = MarketingConfigs.FCM_PROJECT_ID
FCM_SERVICE_ACCOUNT_JSON = MarketingConfigs.FCM_SERVICE_ACCOUNT_JSON

# ============================================================

# Mobile Push Channel
class MobilePushChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs: Any):
        title = kwargs.get("title", "Notification")
        logger.info("[Mobile Push] Segment=%s | Title=%s", recipient_segment, title)
        # TODO: integrate with push provider
        return {"status": "success", "channel": "mobile_push"}


# Web Push Channel
class WebPushChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs: Any):
        logger.info("[Web Push] Segment=%s", recipient_segment)
        return {"status": "success", "channel": "web_push"}
