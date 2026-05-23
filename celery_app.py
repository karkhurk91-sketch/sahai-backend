import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from celery import Celery
import os

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
celery_app.autodiscover_tasks(["modules.tasks"])

celery_app.conf.beat_schedule = {
    "rescore-leads-hourly": {
        "task": "modules.tasks.periodic_tasks.rescore_leads_task",
        "schedule": 3600.0,
    },
    "run-nurturing-every-5-min": {
        "task": "modules.tasks.periodic_tasks.run_nurturing_task",
        "schedule": 300.0,
    },
}