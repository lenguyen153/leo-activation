import logging
import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)

# ============================================================
# App Metadata
# ============================================================
MAIN_APP_HOST = os.getenv("MAIN_APP_HOST","0.0.0.0") 
MAIN_APP_PORT = int(os.getenv("MAIN_APP_PORT", "8000")) if os.getenv("MAIN_APP_PORT") else 8000 

MAIN_APP_TITLE = os.getenv("MAIN_APP_TITLE", "LEO Activation API")
MAIN_APP_DESCRIPTION = os.getenv("MAIN_APP_DESCRIPTION", "LEO Activation Chatbot for LEO CDP with Function Calling")
MAIN_APP_VERSION = os.getenv("MAIN_APP_VERSION", "1.0.0")

# ============================================================
# CORS Configuration
# ============================================================
# ⚠️ In production, DO NOT use ["*"] with credentials=True
CORS_ALLOW_ORIGINS = [
    "*"  # e.g. "https://cdp-admin.example.com"
]

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["*"]
CORS_ALLOW_HEADERS = ["*"]

# ============================================================
# Marketing / Email / Zalo / Facebook Configurations
# ============================================================
class MarketingConfigs:
    """Centralized configuration class that reads environment variables for marketing integrations.

    Access values as class attributes to avoid scattering os.getenv calls throughout the codebase.
    """

    # Email / SMTP / SendGrid
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "smtp").lower()
    SENDGRID_API_KEY: Optional[str] = os.getenv("SENDGRID_API_KEY")
    SENDGRID_FROM: Optional[str] = os.getenv("SENDGRID_FROM")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else 587
    SMTP_USERNAME: Optional[str] = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD: Optional[str] = os.getenv("SMTP_PASSWORD")
    SMTP_USE_TLS: bool = os.getenv(
        "SMTP_USE_TLS", "1").lower() in ("1", "true", "yes")

    # Zalo OA
    ZALO_OA_API_URL: Optional[str] = os.getenv("ZALO_OA_API_URL")
    ZALO_OA_TOKEN: Optional[str] = os.getenv("ZALO_OA_TOKEN")
    try:
        ZALO_OA_MAX_RETRIES: int = int(os.getenv("ZALO_OA_MAX_RETRIES", "1"))
    except Exception:
        ZALO_OA_MAX_RETRIES = 1

    # Facebook
    FB_PAGE_ACCESS_TOKEN: Optional[str] = os.getenv("FB_PAGE_ACCESS_TOKEN")
    FB_PAGE_ID: Optional[str] = os.getenv("FB_PAGE_ID")


# ============================================================
# Gemini LLM Configurations
# ============================================================
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash-lite")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ============================================================
# Gemma Function Calling Model Configurations.
# ============================================================
# The 270M model is specialized; it requires specific control tokens and prompts.
GEMMA_FUNCTION_MODEL_ID = "google/functiongemma-270m-it"
