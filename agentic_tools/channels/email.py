import logging
import ssl
import smtplib
import requests

from typing import Any, Dict, List
from email.message import EmailMessage
from email.utils import formataddr

from agentic_tools.channels.activation import NotificationChannel
from main_configs import MarketingConfigs

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

    def send_via_smtp(
        self,
        recipients: List[str],
        subject: str,
        body: str,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        if not self.smtp_username or not self.smtp_password:
            return {"status": "error", "provider": "smtp", "message": "SMTP credentials not set"}

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["To"] = ", ".join(recipients)
        msg["From"] = formataddr(("Notification", self.smtp_username))
        msg.set_content(body)

        ctx = ssl.create_default_context()

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=timeout) as server:
                server.ehlo()
                if self.smtp_use_tls:
                    server.starttls(context=ctx)
                    server.ehlo()

                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            return {
                "status": "success",
                "channel": "email",
                "provider": "smtp",
                "sent_to": recipients,
            }

        except smtplib.SMTPAuthenticationError:
            return {
                "status": "error",
                "provider": "smtp",
                "message": "SMTP authentication failed",
            }

        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return {
                "status": "error",
                "provider": "smtp",
                "message": str(exc),
            }

    # ============================================================
    # Public Entry Point
    # ============================================================

    def send(self, segment_name: str, message: str, **kwargs: Any) -> Dict[str, Any]:
        logger.info("[Email] Segment=%s | kwargs=%s", segment_name, kwargs)

        # TODO: Replace with real segment → email resolution
        recipients = kwargs.get("recipients") or [
            "tantrieuf31.database@gmail.com",
            "tantrieuf31@gmail.com",
        ]

        subject = kwargs.get("subject") or "Notification"
        timeout = kwargs.get("timeout", 8)
        provider = kwargs.get("provider", self.provider).lower()

        if provider == "brevo":
            return self.send_via_brevo_api(recipients, subject, message, timeout)

        if provider == "sendgrid":
            return self.send_via_sendgrid_api(recipients, subject, message, timeout)

        # Default fallback
        return self.send_via_smtp(recipients, subject, message, timeout)
