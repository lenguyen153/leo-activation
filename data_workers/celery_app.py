import os
from celery import Celery
from celery.schedules import crontab
from main_configs import CELERY_REDIS_URL, CELERY_SYNC_PROFILES_CRON

# When True, Celery only runs CDC-related tasks (fingerprint cache + batch reconciliation).
# All other tasks (zalo, email, profile sync) are disabled.
CELERY_CDC_ONLY = os.getenv("CELERY_CDC_ONLY", "false").lower() in ("1", "true", "yes")

def cron_from_expr(expr: str):
    """
    Convert standard 5-field cron string into celery crontab.
    Example: "*/5 * * * *"
    """
    minute, hour, day, month, weekday = expr.split()
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day,
        month_of_year=month,
        day_of_week=weekday,
    )

SYNC_PROFILES_CRON = cron_from_expr(CELERY_SYNC_PROFILES_CRON)

# ---------------------------------------------------------
# Celery Worker Instance
# ---------------------------------------------------------
worker = Celery(
    "leo_sync_worker",
    broker=CELERY_REDIS_URL,
    backend=CELERY_REDIS_URL,
    include=["data_workers.tasks"],
)

# ---------------------------------------------------------
# Core Configuration
# ---------------------------------------------------------
worker.conf.update(
    timezone="UTC",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

# ---------------------------------------------------------
# Beat Schedule
# ---------------------------------------------------------
_CDC_SCHEDULE = {
    "populate-fingerprint-cache": {
        "task": "data_workers.tasks.populate_fingerprint_cache_task",
        "schedule": crontab(minute="*/5"),  # Every 5 min
    },
    "batch-scoring-reconciliation": {
        "task": "data_workers.tasks.batch_scoring_reconciliation",
        "schedule": crontab(minute="0", hour="*/6"),  # Every 6 hours
    },
}

_FULL_SCHEDULE = {
    "sync-arango-to-pg-profiles": {
        "task": "data_workers.tasks.sync_profiles_task",
        "schedule": SYNC_PROFILES_CRON,
    },
    "zalo-promo-daily-dispatch": {
        "task": "data_workers.tasks.zalo_promo_dispatch",
        "schedule": crontab(minute="0", hour="2"),  # 02:00 UTC = 09:00 VN (UTC+7)
    },
    "zalo-suggested-stock-daily": {
        "task": "data_workers.tasks.zalo_suggested_stock_dispatch",
        "schedule": crontab(minute="45", hour="1"),  # 01:45 UTC = 08:45 VN (UTC+7)
    },
    "email-suggested-stock-daily": {
        "task": "data_workers.tasks.email_suggested_stock_dispatch",
        "schedule": crontab(minute="45", hour="1"),  # 01:45 UTC = 08:45 VN (UTC+7)
    },
    "sync-active-users-portfolios": {
        "task": "data_workers.tasks.sync_active_users_portfolios_task",
        "schedule": crontab(minute="30", hour="1"),  # 01:30 UTC = 08:30 VN (UTC+7)
    },
    **_CDC_SCHEDULE,
}

worker.conf.beat_schedule = _CDC_SCHEDULE if CELERY_CDC_ONLY else _FULL_SCHEDULE
