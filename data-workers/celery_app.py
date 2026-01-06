
import os
from celery import Celery
from celery.schedules import crontab

# Initialize Celery
app = Celery(
    'leo_sync_worker',
    broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    include=['tasks']  # This tells Celery where to find the logic
)

# Configuration
app.conf.update(
    timezone='UTC',
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
)

# --- Schedule: Every 15 Minutes ---
app.conf.beat_schedule = {
    'sync-arango-to-pg-every-15-mins': {
        'task': 'tasks.sync_profiles_task',
        'schedule': crontab(minute='*/15'), # Runs at :00, :15, :30, :45
    },
}