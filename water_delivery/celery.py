import os
from celery import Celery
from celery.schedules import crontab

"""
Celery configuration for water_delivery project.

This module configures Celery with Mexico timezone and basic settings
for task execution, result backend, and scheduling.
"""

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')

app = Celery('water_delivery')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Celery Configuration Options
app.conf.update(
    # Timezone configuration for Mexico
    timezone='America/Mexico_City',
    enable_utc=True,
    
    # Task configuration
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    
    # Broker configuration
    broker_url=f'redis://:{os.environ.get("REDIS_PASSWORD", "")}@{os.environ.get("REDIS_HOST", "localhost")}:{os.environ.get("REDIS_PORT", "6379")}/0',
    broker_connection_retry_on_startup=True,
    
    # Result backend
    result_backend=f'redis://:{os.environ.get("REDIS_PASSWORD", "")}@{os.environ.get("REDIS_HOST", "localhost")}:{os.environ.get("REDIS_PORT", "6379")}/1',
    result_expires=3600,  # 1 hour
    
    # Task execution
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    
    # Worker configuration
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    
    # Beat scheduler (for periodic tasks)
    beat_scheduler='django_celery_beat.schedulers:DatabaseScheduler',
)

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to verify Celery is working correctly."""
    print(f'Request: {self.request!r}')