import logging
import os
from typing import Optional

from dotenv import load_dotenv


# ============================================================
# Environment bootstrap
# ============================================================
# Load variables from .env early.
# override=True allows local dev to intentionally shadow system envs.
load_dotenv(override=True)


# ============================================================
# Logging Configuration
# ============================================================
# LOG_LEVEL is expected to be something like: DEBUG, INFO, WARNING, ERROR
# Default to INFO if missing or invalid.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# Application Metadata
# ============================================================
# Network binding
MAIN_APP_HOST: str = os.getenv("MAIN_APP_HOST", "0.0.0.0")

# Port parsing should be strict: invalid values must fail fast
try:
    MAIN_APP_PORT: int = int(os.getenv("MAIN_APP_PORT", "8000"))
except ValueError:
    raise RuntimeError("MAIN_APP_PORT must be a valid integer")

# Descriptive metadata (used by FastAPI / OpenAPI)
MAIN_APP_TITLE: str = os.getenv("MAIN_APP_TITLE", "LEO Activation API")
MAIN_APP_DESCRIPTION: str = os.getenv(
    "MAIN_APP_DESCRIPTION",
    "LEO Activation Chatbot for LEO CDP with Function Calling",
)
MAIN_APP_VERSION: str = os.getenv("MAIN_APP_VERSION", "1.0.0")


# ============================================================
# CORS Configuration
# ============================================================
# ⚠️ SECURITY NOTE
# Using "*" with credentials=True is NOT allowed by browsers
# and should never be used in production.
# Replace "*" with explicit origins when deploying.
CORS_ALLOW_ORIGINS = [
    "*"  # e.g. "https://cdp-admin.example.com"
]

CORS_ALLOW_CREDENTIALS: bool = True
CORS_ALLOW_METHODS = ["*"]
CORS_ALLOW_HEADERS = ["*"]


# ============================================================
# Marketing / Messaging Integrations Configuration
# ============================================================
class MarketingConfigs:
    """
    Centralized configuration holder for outbound communication channels.

    Design choice:
    - Use class attributes instead of instance attributes
    - Read env vars once at import time
    - Avoid scattering os.getenv() across business logic
    """

    # --------------------------------------------------------
    # Email / SMTP / SendGrid
    # --------------------------------------------------------
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "smtp").lower()
    # Expected values: "smtp", "sendgrid"

    # -------- Brevo --------
    BREVO_API_KEY: Optional[str] = os.getenv("BREVO_API_KEY")
    BREVO_FROM_EMAIL: Optional[str] = os.getenv("BREVO_FROM_EMAIL")
    BREVO_FROM_NAME: Optional[str] = os.getenv("BREVO_FROM_NAME")
    
    # -------- SendGrid --------
    SENDGRID_API_KEY: Optional[str] = os.getenv("SENDGRID_API_KEY")
    SENDGRID_FROM: Optional[str] = os.getenv("SENDGRID_FROM")
    
    # -------- SMTP --------
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    try:
        SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        raise RuntimeError("SMTP_PORT must be a valid integer")
    SMTP_USERNAME: Optional[str] = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD: Optional[str] = os.getenv("SMTP_PASSWORD")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "1").lower() in (
        "1",
        "true",
        "yes",
    )  # Accept common truthy values to reduce config friction

    # --------------------------------------------------------
    # Zalo Official Account
    # --------------------------------------------------------
    ZALO_OA_API_URL: Optional[str] = os.getenv("ZALO_OA_API_URL")
    ZALO_OA_TOKEN: Optional[str] = os.getenv("ZALO_OA_TOKEN")

    try:
        ZALO_OA_MAX_RETRIES: int = int(os.getenv("ZALO_OA_MAX_RETRIES", "1"))
    except ValueError:
        ZALO_OA_MAX_RETRIES = 1

    # --------------------------------------------------------
    # Facebook Page Messaging
    # --------------------------------------------------------
    FB_PAGE_ACCESS_TOKEN: Optional[str] = os.getenv("FB_PAGE_ACCESS_TOKEN")
    FB_PAGE_ID: Optional[str] = os.getenv("FB_PAGE_ID")
    
    # --------------------------------------------------------
    # Mobile Push Notifications
    # --------------------------------------------------------
    PUSH_PROVIDER: str = os.getenv("PUSH_PROVIDER", "firebase").lower()

    # Firebase Cloud Messaging (FCM)
    FCM_PROJECT_ID: Optional[str] = os.getenv("FCM_PROJECT_ID")
    FCM_SERVICE_ACCOUNT_JSON: Optional[str] = os.getenv("FCM_SERVICE_ACCOUNT_JSON")



# ============================================================
# Gemini LLM Configuration
# ============================================================
# Model ID is configurable to allow rapid switching without redeploy.
# Default chosen for low latency and cost.
GEMINI_MODEL_ID: str = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash-lite")

# API key is intentionally not defaulted.
# Missing key should fail at runtime, not silently degrade.
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")


# ============================================================
# Gemma Function Calling Model Configuration
# ============================================================
# FunctionGemma 270M:
# - Small, fast
# - Requires strict prompt formatting and control tokens
# - Best used only for tool routing / function selection
GEMMA_FUNCTION_MODEL_ID: str = "google/functiongemma-270m-it"



# Hugging Face access token
# Required when loading private models or avoiding rate limits
HUGGINGFACE_TOKEN: str = os.getenv("HUGGINGFACE_TOKEN")