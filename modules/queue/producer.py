import os
from celery import Celery
from modules.common.config import REDIS_URL

# Initialize Celery app
broker = os.getenv("CELERY_BROKER_URL", REDIS_URL)
celery_app = Celery("wabot", broker=broker)

# Basic configuration; extend in production as needed
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# Simple beat schedule: check follow-ups every 5 minutes
celery_app.conf.beat_schedule = {
    'check-followups-every-5m': {
        'task': 'modules.queue.tasks.check_due_followups',
        'schedule': 300.0,
    }
}

# Hourly check for lead nurturing sequences
celery_app.conf.beat_schedule.update({
    'check-lead-nurturing-every-1h': {
        'task': 'modules.leads.nurturing_scheduler.check_nurturing',
        'schedule': 3600.0,
    }
})

# Register tasks module so worker picks them up
celery_app.autodiscover_tasks(['modules.queue.tasks'])
celery_app.autodiscover_tasks(['modules.leads.nurturing_scheduler'])

__all__ = ["celery_app"]
