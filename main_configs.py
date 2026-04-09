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

# Default Redis Configuration for caching and state management
REDIS_URL: Optional[str] = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_REDIS_URL: Optional[str] = os.getenv("CELERY_REDIS_URL", "redis://localhost:6379/1")
CELERY_SYNC_PROFILES_CRON: Optional[str] = os.getenv("CELERY_SYNC_PROFILES_CRON", "*/5 * * * *")

# Recommendation cache TTL (seconds). Scores update hourly; 5 min keeps reads fast.
try:
    RECOMMENDATION_CACHE_TTL: int = int(os.getenv("RECOMMENDATION_CACHE_TTL", "300"))
except ValueError:
    raise RuntimeError("RECOMMENDATION_CACHE_TTL must be a valid integer (seconds)")

# Data Sync API Key for authenticating with LeoCDP
DATA_SYNC_API_KEY: Optional[str] = os.getenv("DATA_SYNC_API_KEY")

# ============================================================
# Real-Time Event-Driven Pipeline Configuration
# ============================================================
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
CDC_POLL_INTERVAL_S: int = int(os.getenv("CDC_POLL_INTERVAL_S", "2"))
ACTIVATION_APP_WEBHOOK_URL: Optional[str] = os.getenv("ACTIVATION_APP_WEBHOOK_URL")
REALTIME_SCORING_ENABLED: bool = os.getenv("REALTIME_SCORING_ENABLED", "False").lower() in ("1", "true", "yes")

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
    ZALO_APP_ID: Optional[str] = os.getenv("ZALO_APP_ID")
    ZALO_APP_SECRET: Optional[str] = os.getenv("ZALO_APP_SECRET")
    ZALO_OA_API_URL: Optional[str] = os.getenv("ZALO_OA_API_URL")
    ZALO_OA_TOKEN: Optional[str] = os.getenv("ZALO_OA_TOKEN")
    ZALO_ZNS_TEMPLATE_ID: Optional[str] = os.getenv("ZALO_ZNS_TEMPLATE_ID")
    ZALO_OA_REFRESH_TOKEN: Optional[str] = os.getenv("ZALO_OA_REFRESH_TOKEN")

    try:
        ZALO_OA_MAX_RETRIES: int = int(os.getenv("ZALO_OA_MAX_RETRIES", "1"))
    except ValueError:
        ZALO_OA_MAX_RETRIES = 1

    # -------- Zalo Promotional Messages (Tin Truyền Thông) --------
    ZALO_PROMO_API_URL: str = os.getenv(
        "ZALO_PROMO_API_URL",
        "https://openapi.zalo.me/v3.0/oa/message/promotion",
    )
    try:
        ZALO_PROMO_INTEREST_THRESHOLD: float = float(
            os.getenv("ZALO_PROMO_INTEREST_THRESHOLD", "0.70")
        )
    except ValueError:
        raise RuntimeError("ZALO_PROMO_INTEREST_THRESHOLD must be a valid float")
    try:
        ZALO_PROMO_EVENT_COUNT_THRESHOLD: int = int(
            os.getenv("ZALO_PROMO_EVENT_COUNT_THRESHOLD", "3")
        )
    except ValueError:
        raise RuntimeError("ZALO_PROMO_EVENT_COUNT_THRESHOLD must be a valid integer")

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

    # --------------------------------------------------------
    # Omnichannel Admin Notify (Push via core system)
    # --------------------------------------------------------
    ADMINNOTIFY_BASE_URL: str = os.getenv("ADMINNOTIFY_BASE_URL", "https://your-core-system.com")
    ADMINNOTIFY_ENDPOINT: str = os.getenv("ADMINNOTIFY_ENDPOINT", "/fo/api/adminnotify")


# ============================================================
# Campaign Engine Configuration
# ============================================================
class CampaignEngineConfigs:
    """Settings for the Rule-Based Notification Campaign Engine."""

    ENABLED: bool = os.getenv("CAMPAIGN_ENGINE_ENABLED", "False").lower() in ("1", "true", "yes")

    # Batch processing
    BATCH_SIZE: int = int(os.getenv("CAMPAIGN_ENGINE_BATCH_SIZE", "500"))

    # Global frequency caps (per user, overridable per-rule)
    MAX_NOTIFICATIONS_PER_DAY: int = int(os.getenv("CAMPAIGN_MAX_NOTIF_PER_DAY", "3"))
    MIN_COOLDOWN_HOURS: int = int(os.getenv("CAMPAIGN_MIN_COOLDOWN_HOURS", "4"))

    # Circuit breaker
    CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("CAMPAIGN_CB_THRESHOLD", "5"))
    CIRCUIT_BREAKER_RECOVERY_S: int = int(os.getenv("CAMPAIGN_CB_RECOVERY_S", "60"))

    # Retry
    MAX_DELIVERY_RETRIES: int = int(os.getenv("CAMPAIGN_MAX_RETRIES", "3"))
