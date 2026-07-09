"""
Celery tasks for periodic sync of campaigns, audiences, insights.
"""
from celery import shared_task
import asyncio

@shared_task
def sync_campaigns():
    async def _sync():
        # Logic to fetch campaigns from Facebook and update DB
        pass
    asyncio.run(_sync())

@shared_task
def sync_audiences():
    pass

@shared_task
def fetch_insights():
    pass