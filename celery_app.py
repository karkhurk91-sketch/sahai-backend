import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from celery import Celery
import os
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")
celery_app = Celery("sahai", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
# ✅ FIX: Change autodiscover from "modules.tasks" to "modules.queue"
celery_app.autodiscover_tasks(["modules.queue"])

celery_app.conf.beat_schedule = {
    'run-nurturing-every-minute': {
        'task': 'modules.queue.tasks.run_nurturing_task',
        'schedule': 60.0,
    },
    'rescore-leads-hourly': {
        'task': 'modules.queue.tasks.rescore_leads_task',
        'schedule': 3600.0,
    },
    'send-booking-reminders-daily': {
        'task': 'modules.queue.tasks.send_booking_reminders',
        'schedule': crontab(hour=9, minute=0),
    },
}