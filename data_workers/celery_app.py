import os
from celery import Celery
from celery.schedules import crontab
from main_configs import CELERY_REDIS_URL, CELERY_SYNC_PROFILES_CRON



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
worker.conf.beat_schedule = {
    "sync-arango-to-pg-profiles": {
        "task": "tasks.sync_profiles_task",
        "schedule": SYNC_PROFILES_CRON,
    },
}
