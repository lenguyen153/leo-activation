import logging
import json
from typing import Dict, Any, Tuple, List

import firebase_admin
from firebase_admin import credentials, messaging

from agentic_tools.channels.activation import NotificationChannel
from main_configs import MarketingConfigs
from data_workers.cdp_db_utils import get_subscription_from_cdp

from data_utils.settings import DatabaseSettings
from data_utils.arango_client import get_arango_db

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

    CONNECTOR_NAME = "LEO Web Push Connector"
    COLLECTION_NAME = "cdp_dataconnector"

    def __init__(self, override_config: Dict = None):
        try:
            self.db = get_arango_db(DatabaseSettings())
        except Exception as e:
            logger.error(f"[FCM] Failed to connect to DB: {e}")
            self.db = None
            
        self.firebase_app = None
        if self.db:
            self._initialize_firebase()

    def send(self, recipient_segment: str, message: str = None, **kwargs) -> Dict[str, Any]:
        """
        Sends notifications. 1 Profile = 1 FCM Token.
        """
        if not self.firebase_app:
             return {"status": "error", "message": "Firebase App not initialized."}

        # 1. Fetch Recipients
        recipients = get_subscription_from_cdp(self.db, recipient_segment)
        if not recipients:
            return {"status": "warning", "message": f"No recipients found in '{recipient_segment}'"}

        stats = {"sent": 0, "failed": 0, "removed": 0}
        
        title = kwargs.get("title", "Notification")
        image_url = kwargs.get("image_url", "")
        
        # 2. Loop through Profiles (Each profile = 1 Platform/Device)
        for user in recipients:
            user_key = user.get("_key")
            identities = user.get("identities", [])

            # 3. Find the SINGLE FCM token in this profile
            target_token = None
            full_identity_string = None
            
            for identity_str in identities:
                if identity_str.startswith("fcm_tokens:"):
                    target_token = identity_str.split(":", 1)[1]
                    full_identity_string = identity_str
                    break # Stop after finding the first one

            if not target_token:
                # Profile is in the segment but has no FCM token identity
                continue

            # 4. Send to that single token
            try:
                msg = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=message,
                        image=image_url
                    ),
                    token=target_token 
                )
                
                response_id = messaging.send(msg)
                stats["sent"] += 1
                logger.info(f"[FCM] Sent to {user_key}: {response_id}")

            except firebase_admin._messaging_utils.UnregisteredError:
                # Token is dead -> Remove the specific "fcm_tokens:..." string
                logger.warning(f"[FCM] Token dead for user {user_key}. Removing identity...")
                if full_identity_string:
                    self._remove_dead_identity(user_key, full_identity_string)
                stats["removed"] += 1
                
            except Exception as e:
                logger.error(f"[FCM] Failed to send to {user_key}: {e}")
                stats["failed"] += 1

        return {"status": "success", "stats": stats}

    def _initialize_firebase(self):
        """
        Loads Service Account JSON from DB and initializes the Global App.
        """
        try:
            if firebase_admin._apps:
                self.firebase_app = firebase_admin.get_app()
                return

            aql = f"FOR d IN {self.COLLECTION_NAME} FILTER d.name == @name RETURN d.configs.service_account_json"
            cursor = self.db.aql.execute(aql, bind_vars={'name': self.CONNECTOR_NAME})
            service_account_dict = next(cursor, None)

            if service_account_dict:
                cred = credentials.Certificate(service_account_dict)
                self.firebase_app = firebase_admin.initialize_app(cred)
                logger.info("[FCM] Firebase App Initialized Successfully.")
            else:
                logger.error("[FCM] Service Account JSON missing in DB.")

        except Exception as e:
            logger.error(f"[FCM] Init failed: {e}")

    def _remove_dead_identity(self, user_key: str, full_identity_string: str):
        """
        Removes the specific 'fcm_tokens:xyz' string from the identities array.
        """
        aql = """
        LET user = DOCUMENT(CONCAT('cdp_profile/', @user_key))
        UPDATE user WITH {
            identities: REMOVE_VALUE(user.identities, @identity_to_remove)
        } IN cdp_profile
        """
        self.db.aql.execute(aql, bind_vars={
            'user_key': user_key, 
            'identity_to_remove': full_identity_string
        })