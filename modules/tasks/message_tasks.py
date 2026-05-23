import sys
from pathlib import Path
# Add project root to path (absolute)
sys.path.insert(0, str(Path(__file__).parents[2]))

import asyncio
from celery import Celery
from modules.ai.processor import process_incoming_message
from modules.common.logger import get_logger

logger = get_logger(__name__)

# Create Celery app here (or import from celery_app)
# To avoid circular imports, we create it locally
REDIS_URL = "redis://localhost:6379/1"
celery_app = Celery("sahai", broker=REDIS_URL, backend=REDIS_URL)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_message_task(self, message_data: dict):
    try:
        asyncio.run(process_incoming_message(message_data))
    except Exception as exc:
        logger.error(f"Task failed, retrying: {exc}")
        self.retry(exc=exc)