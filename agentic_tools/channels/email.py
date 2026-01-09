import logging
import ssl
import smtplib
import requests

from typing import Any, Dict, List
from email.message import EmailMessage
from email.utils import formataddr

from agentic_tools.channels.activation import NotificationChannel
from main_configs import MarketingConfigs

from data_workers.database import get_arango_db  # Import your connection function

from helpers import (
    get_recipients_from_arango,
    render_template,
    PRODUCT_RECOMMENDATION_TEMPLATE
)

logger = logging.getLogger(__name__)


# ============================================================
# Email Channel
# ============================================================

class EmailChannel(NotificationChannel):
    """
    Email channel supporting:
      - Brevo API
      - SendGrid API
      - SMTP (Gmail, Brevo SMTP, custom)
      
    Configuration (via ENV vars):
      - EMAIL_PROVIDER: 'brevo', 'sendgrid' or 'smtp' (default: 'smtp')
      - SENDGRID_API_KEY: API key for SendGrid (if using sendgrid)
      - SENDGRID_FROM: default from email for SendGrid
      - BREVO_API_KEY: API key for Brevo (if using brevo)
      - BREVO_FROM_EMAIL: default from email for Brevo
      - BREVO_FROM_NAME: default from name for Brevo
      - SMTP_HOST: SMTP host (default: smtp.gmail.com)
      - SMTP_PORT: SMTP port (default: 587)
      - SMTP_USERNAME: SMTP login username (for Gmail this is the full email)
      - SMTP_PASSWORD: SMTP password or app-specific password
      - SMTP_USE_TLS: '1'/'true' to use STARTTLS (default: true)

    Providers:
      EMAIL_PROVIDER = brevo | sendgrid | smtp
    """

    def __init__(self):
        self.provider = MarketingConfigs.EMAIL_PROVIDER or "smtp"

        # -------- Database Connection --------
        try:
            self.db = get_arango_db()
        except Exception as e:
            logger.error(f"[EmailChannel] Failed to connect to ArangoDB on init: {e}")
            self.db = None

        # -------- Brevo --------
        self.brevo_api_key = MarketingConfigs.BREVO_API_KEY
        self.brevo_from_email = MarketingConfigs.BREVO_FROM_EMAIL
        self.brevo_from_name = MarketingConfigs.BREVO_FROM_NAME or "Notification"

        # -------- SendGrid --------
        self.sendgrid_api_key = MarketingConfigs.SENDGRID_API_KEY
        self.sendgrid_from = MarketingConfigs.SENDGRID_FROM

        # -------- SMTP --------
        self.smtp_host = MarketingConfigs.SMTP_HOST or "smtp.gmail.com"
        self.smtp_port = MarketingConfigs.SMTP_PORT or 587
        self.smtp_username = MarketingConfigs.SMTP_USERNAME
        self.smtp_password = MarketingConfigs.SMTP_PASSWORD
        self.smtp_use_tls = MarketingConfigs.SMTP_USE_TLS

    # ============================================================
    # Brevo API
    # ============================================================
    def send_via_brevo_api(
        self,
        recipients: List[str],
        subject: str,
        html_body: str,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        """
        Send transactional email via Brevo SMTP API.
        Docs: POST /v3/smtp/email
        """

        if not self.brevo_api_key:
            return {
                "status": "error",
                "provider": "brevo",
                "message": "BREVO_API_KEY not set",
            }

        if not self.brevo_from_email:
            return {
                "status": "error",
                "provider": "brevo",
                "message": "BREVO_FROM_EMAIL not set",
            }

        if not recipients:
            return {
                "status": "error",
                "provider": "brevo",
                "message": "Recipient list is empty",
            }

        payload = {
            "sender": {
                "email": self.brevo_from_email,
                "name": self.brevo_from_name or "Notification",
            },
            "to": [{"email": r} for r in recipients],
            "subject": subject,
            "htmlContent": html_body,
        }

        headers = {
            "accept": "application/json",
            "api-key": self.brevo_api_key,
            "content-type": "application/json",
        }

        try:
            resp = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers=headers,
                timeout=timeout,
            )

            if resp.status_code >= 400:
                logger.error(
                    "Brevo API error %s: %s",
                    resp.status_code,
                    resp.text,
                )
                return {
                    "status": "error",
                    "channel": "email",
                    "provider": "brevo",
                    "http_status": resp.status_code,
                    "message": resp.text,
                }

            data = resp.json()

            return {
                "status": "success",
                "channel": "email",
                "provider": "brevo",
                "message_id": data.get("messageId"),
            }

        except requests.RequestException as exc:
            logger.exception("Brevo API request failed")
            return {
                "status": "error",
                "channel": "email",
                "provider": "brevo",
                "message": str(exc),
            }


    # ============================================================
    # SendGrid API
    # ============================================================

    def send_via_sendgrid_api(
        self,
        recipients: List[str],
        subject: str,
        body: str,
        timeout: int = 8,
    ) -> Dict[str, Any]:
        if not self.sendgrid_api_key:
            return {"status": "error", "provider": "sendgrid", "message": "SENDGRID_API_KEY not set"}

        from_email = self.sendgrid_from or self.smtp_username
        if not from_email:
            return {"status": "error", "provider": "sendgrid", "message": "SendGrid FROM email not configured"}

        payload = {
            "personalizations": [
                {
                    "to": [{"email": r} for r in recipients],
                    "subject": subject,
                }
            ],
            "from": {"email": from_email},
            "content": [{"type": "text/plain", "value": body}],
        }

        headers = {
            "Authorization": f"Bearer {self.sendgrid_api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            return {
                "status": "success",
                "channel": "email",
                "provider": "sendgrid",
                "response_status": resp.status_code,
            }

        except requests.RequestException as exc:
            logger.error("SendGrid send failed: %s", exc)
            return {
                "status": "error",
                "channel": "email",
                "provider": "sendgrid",
                "message": str(exc),
            }

    # ============================================================
    # SMTP
    # ============================================================
    def send_via_smtp(self, recipients: List[str], subject: str, body: str, timeout: int = 10) -> Dict[str, Any]:
        if not self.smtp_username or not self.smtp_password:
             return {"status": "error", "message": "SMTP credentials missing"}

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["To"] = ", ".join(recipients) 
        msg["From"] = formataddr(("Notification", self.smtp_username))
        
        # ✅ CRITICAL FIX: Explicitly set content type to HTML
        msg.set_content(body, subtype='html') 

        ctx = ssl.create_default_context()
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=timeout) as server:
                server.ehlo()
                if self.smtp_use_tls:
                    server.starttls(context=ctx)
                    server.ehlo()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            return {"status": "success", "sent_to": recipients}
        except Exception as e:
            logger.error(f"SMTP Error: {e}")
            return {"status": "error", "message": str(e)}

    # ============================================================
    # 4. Main Send Logic (The Orchestrator)
    # ============================================================
    def send(self, recipient_segment: str, message: str = None, **kwargs: Any) -> Dict[str, Any]:
        """
        Orchestrates sending. 
        If 'message' is not provided, defaults to the PRODUCT_RECOMMENDATION_TEMPLATE.
        Performes 1-to-1 sending if personalization tokens are detected.
        """
        logger.info("[Email] Starting send process for Segment: %s", recipient_segment)

        if message and message.strip():
            html_content = message
            logger.info("Using custom message provided in arguments (Template ignored).")
        else:
            html_content = PRODUCT_RECOMMENDATION_TEMPLATE
            logger.info("Using Default Product Recommendation Template.")

        # 1. Determine Content
        # If user passed a message, use it. Otherwise use the default HTML template.
        subject = kwargs.get("subject") or "Special Offer for You"
        timeout = kwargs.get("timeout", 10)
        provider = kwargs.get("provider", self.provider).lower()

        # 2. Fetch Recipients Data (List of Dicts)
        # We need the full object {email, firstName}, not just strings.
        recipient_objects = get_recipients_from_arango(self.db_connection, recipient_segment)
        
        if not recipient_objects:
            logger.warning("[Email] No recipients found. Aborting.")
            return {"status": "skipped", "reason": "no_recipients"}

        # 3. Personalization Loop
        # Since the template has {{profile.firstName}}, we must send emails individually.
        success_count = 0
        fail_count = 0

        logger.info(f"[Email] Sending {len(recipient_objects)} individual emails via {provider}...")

        for user in recipient_objects:
            email = user.get("email")
            
            # Render unique body for this user
            personalized_body = self.render_template(html_content, user)
            
            # Send logic
            try:
                if provider == "brevo":
                    res = self.send_via_brevo_api([email], subject, personalized_body, timeout)
                elif provider == "sendgrid":
                    res = self.send_via_sendgrid_api([email], subject, personalized_body, timeout)
                else:
                    # SMTP default
                    res = self.send_via_smtp([email], subject, personalized_body, timeout)

                if res.get("status") == "success":
                    success_count += 1
                else:
                    fail_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to send to {email}: {e}")
                fail_count += 1

        # 4. Final Report
        return {
            "status": "completed",
            "segment": recipient_segment,
            "total_attempted": len(recipient_objects),
            "success": success_count,
            "failed": fail_count
        }

# ============================================================
# End Email Channel Class
# ============================================================