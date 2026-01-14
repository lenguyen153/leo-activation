
import logging
import requests
import re
import time
import random
from typing import Dict, Any, Optional, Tuple

from agentic_tools.channels.activation import NotificationChannel
from main_configs import MarketingConfigs

from agentic_tools.channels.helpers import get_emails_from_arango
from data_workers.database import get_arango_db

logger = logging.getLogger(__name__)

class ZaloOAChannel(NotificationChannel):

    # Constants for DB Lookup
    CONNECTOR_NAME = "LEO Zalo Connector"
    COLLECTION_NAME = "cdp_dataconnector"

    def __init__(self, override_token: str = None):
        # -------- Database Connection --------
        try:
            self.db = get_arango_db()
        except Exception as e:
            logger.error(f"[EmailChannel] Failed to connect to ArangoDB on init: {e}")
            self.db = None

        self.zns_url = "https://business.openapi.zalo.me/message/template"
        self.oauth_url = "https://oauth.zaloapp.com/v4/oa/access_token"
        
        self.app_id = MarketingConfigs.ZALO_APP_ID
        self.secret_key = MarketingConfigs.ZALO_APP_SECRET
        self.template_id = MarketingConfigs.ZALO_ZNS_TEMPLATE_ID
        
        # Token Management
        self.access_token = override_token or MarketingConfigs.ZALO_OA_TOKEN
        self.refresh_token = MarketingConfigs.ZALO_OA_REFRESH_TOKEN

        # Always try to load the initial state from DB if available
        if self.db:
            self._load_tokens_from_db()


    def send(self, recipient_segment: str, message: str = None, **kwargs):
        """
        Main Execution Flow (Test Mode)
        """
        logger.info(f"[Zalo] Starting TEST MODE send to segment: {recipient_segment}")
        
        # 1. Fetch Recipients
        recipients = get_emails_from_arango(self.db, recipient_segment)
        if not recipients:
            return {"status": "warning", "message": f"No profiles found in '{recipient_segment}'"}

        stats = {"sent": 0, "failed": 0, "invalid_phone": 0}

        # 2. Loop & Send
        for p in recipients:
            phone = self._format_phone_for_zalo(p.get('phone'))
            name = p.get('firstName', 'Customer')

            if not phone:
                stats["invalid_phone"] += 1
                continue

            # Construct Payload
            # NOTE: Ensure keys like 'customer_name' match your ZNS Template exactly!
            # 1. Generate a random 6-digit OTP
            generated_otp = str(random.randint(100000, 999999))

            # 2. Construct Payload
            payload = {
                "phone": phone,
                "template_id": self.template_id,
                "template_data": {
                    # Zalo requires the key to match "otp" exactly
                    "otp": generated_otp,
                },
                "tracking_id": f"track_{int(time.time())}_{phone}"
            }

            # 3. Attempt 1 Send
            success, error_code, result_msg = self._execute_zns_call(payload)

            # 4. Auto-Refresh Logic
            if not success and error_code == -124:
                logger.warning(f"[Zalo] Token expired for {phone}. Refreshing and Retrying...")
                if self._refresh_access_token():
                    # Attempt 2 (Retry with new token)
                    success, error_code, result_msg = self._execute_zns_call(payload)
                else:
                    logger.error("[Zalo] Token refresh failed. Aborting retry.")

            # 5. Handle Final Result
            if success:
                stats["sent"] += 1
                # NOTE: In real mode, consider saving verified phones
                # self._save_verified_phone(phone, name, result_msg)
            else:
                stats["failed"] += 1
                logger.warning(f"[Zalo] Failed to send to {phone}. Error: {error_code} - {result_msg}")

        return {
            "status": "success", 
            "details": f"Run complete. Sent: {stats['sent']}, Failed: {stats['failed']}", 
            "stats": stats
        }

    
    def _execute_zns_call(self, payload: Dict) -> Tuple[bool, int, str]:
        """
        Executes API call with VERBOSE DEBUGGING.
        """
        # 1. Sanitize Token (Strip whitespace which causes many errors)
        clean_token = self.access_token.strip()
        
        headers = {
            "access_token": clean_token,  # ZNS uses this specific header key
            "Content-Type": "application/json"
        }
        
        # 2. DEBUG LOGS: Print what we are actually sending
        # Mask the token so we can verify it without leaking it entirely
        masked_token = f"{clean_token[:10]}...{clean_token[-10:]}" if len(clean_token) > 20 else "INVALID_SHORT_TOKEN"
        
        logger.info("------------- ZALO DEBUG REQUEST -------------")
        logger.info(f"URL: {self.zns_url}")
        logger.info(f"Token Used: {masked_token}") 
        logger.info(f"Token Length: {len(clean_token)} chars")
        logger.info(f"Payload: {payload}")
        logger.info("----------------------------------------------")

        try:
            resp = requests.post(self.zns_url, json=payload, headers=headers, timeout=15)
            data = resp.json()
            
            # 3. DEBUG LOGS: Print exactly what Zalo replied
            logger.info("------------- ZALO DEBUG RESPONSE ------------")
            logger.info(f"Status Code: {resp.status_code}")
            logger.info(f"Raw Body: {resp.text}")
            logger.info("----------------------------------------------")
            
            error_code = data.get("error", -999)
            message = data.get("message", "Unknown")
            
            # Case 1: Success
            if error_code == 0:
                msg_id = data.get("data", {}).get("msg_id", "unknown")
                return True, 0, msg_id

            # Case 2: Token Expired (-124) or Invalid (-14014 sometimes)
            return False, error_code, message

        except Exception as e:
            logger.error(f"[Zalo Network Error] {e}")
            return False, -999, str(e)
        
        
    def _refresh_access_token(self) -> bool:
        """
        1. Reads latest Refresh Token from DB.
        2. Calls Zalo OAuth.
        3. Saves new tokens to DB.
        """
        logger.info("[Zalo] Access Token invalid/expired. Preparing to refresh...")
        
        # 1. CRITICAL: Fetch the latest Refresh Token from DB right now
        # This prevents using a stale token if another process updated it.
        self._load_tokens_from_db()
        
        if not self.refresh_token:
            logger.error("[Zalo] No Refresh Token available (DB & Config empty). Cannot refresh.")
            return False

        headers = {"secret_key": self.secret_key}
        payload = {
            "refresh_token": self.refresh_token,
            "app_id": self.app_id,
            "grant_type": "refresh_token"
        }

        try:
            resp = requests.post(self.oauth_url, headers=headers, data=payload, timeout=15)
            data = resp.json()

            if "access_token" in data:
                new_at = data["access_token"]
                new_rt = data["refresh_token"]
                
                # Update Memory
                self.access_token = new_at
                self.refresh_token = new_rt 
                
                # Update Database
                self._save_tokens_to_db(new_at, new_rt)
                return True
            else:
                logger.error(f"[Zalo] Refresh Failed. Response: {data}")
                return False
        except Exception as e:
            logger.error(f"[Zalo] Refresh Exception: {e}")
            return False


    def _load_tokens_from_db(self):
        """
        Fetches the latest tokens from 'cdp_dataconnector' collection.
        """
        if not self.db: return

        try:
            aql = f"""
            FOR d IN {self.COLLECTION_NAME}
                FILTER d.name == @name
                RETURN d.configs
            """
            cursor = self.db.aql.execute(aql, bind_vars={'name': self.CONNECTOR_NAME})
            configs = list(cursor)
            
            if configs and len(configs) > 0:
                cfg = configs[0]
                self.access_token = cfg.get("zalo_oa_token", self.access_token)
                self.refresh_token = cfg.get("zalo_refresh_token", self.refresh_token)
                logger.info("[Zalo] Successfully loaded tokens from DB.")
            else:
                logger.warning(f"[Zalo] No connector found with name '{self.CONNECTOR_NAME}'. Using static configs.")
        except Exception as e:
            logger.error(f"[Zalo] Failed to load tokens from DB: {e}")


    def _save_tokens_to_db(self, new_access_token: str, new_refresh_token: str):
        """
        Persists the NEW tokens to 'cdp_dataconnector'.
        CRITICAL: Zalo Refresh Tokens are single-use. We must save the new one.
        """
        if not self.db: return

        try:
            # We use MERGE to update only the specific fields inside 'configs' object
            aql = f"""
            FOR d IN {self.COLLECTION_NAME}
                FILTER d.name == @name
                UPDATE d WITH {{
                    configs: MERGE(d.configs, {{
                        zalo_oa_token: @at,
                        zalo_refresh_token: @rt
                    }}),
                    updatedAt: DATE_ISO8601(DATE_NOW())
                }} IN {self.COLLECTION_NAME}
            """
            self.db.aql.execute(aql, bind_vars={
                'name': self.CONNECTOR_NAME,
                'at': new_access_token,
                'rt': new_refresh_token
            })
            logger.info("[Zalo] ✅ New tokens saved to Database successfully.")
        except Exception as e:
            logger.error(f"[Zalo] ❌ CRITICAL: Failed to save new tokens to DB! Next run will fail. Error: {e}")


    def _format_phone_for_zalo(self, phone: str) -> Optional[str]:
        """
        Converts 09xx -> 849xx. Returns None if invalid.
        """
        if not phone:
            return None
        
        # Remove non-digits
        clean_phone = re.sub(r'\D', '', phone)
        
        # Handle 84 prefix
        if clean_phone.startswith('84'):
            return clean_phone
        if clean_phone.startswith('0'):
            return '84' + clean_phone[1:]
            
        return clean_phone
    
    
    def _save_verified_phone(self, phone: str, name: str, msg_id: str):
        """
        Saves successfully reached numbers to 'cdp_verified_phone'.
        Uses UPSERT to avoid duplicates.
        """
        if not self.db: return

        aql_upsert = """
        UPSERT { phone: @phone } 
        INSERT { 
            phone: @phone, 
            firstName: @name, 
            firstVerifiedAt: DATE_ISO8601(DATE_NOW()),
            lastVerifiedAt: DATE_ISO8601(DATE_NOW()),
            lastMsgId: @msg_id,
            channel: 'zalo_zns',
            status: 'active'
        } 
        UPDATE { 
            lastVerifiedAt: DATE_ISO8601(DATE_NOW()),
            lastMsgId: @msg_id,
            firstName: @name,
            status: 'active'
        } 
        IN cdp_verified_phone
        """
        try:
            self.db.aql.execute(aql_upsert, bind_vars={
                'phone': phone, 
                'name': name,
                'msg_id': msg_id
            })
            # logger.info(f"[Zalo] Verified phone saved: {phone}")
        except Exception as e:
            logger.error(f"[Zalo] Failed to save verified phone {phone}: {e}")