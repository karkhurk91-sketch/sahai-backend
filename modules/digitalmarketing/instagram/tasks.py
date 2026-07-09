from celery import shared_task
import asyncio

@shared_task
def publish_scheduled_instagram_post(post_id: str):
    # similar to Facebook scheduled post
    pass