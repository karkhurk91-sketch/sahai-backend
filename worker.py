from modules.queue.producer import celery_app
from modules.queue.tasks import *   # ensure tasks are registered
from modules.common.logger import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    logger.info("Starting Celery worker")
    celery_app.start()
