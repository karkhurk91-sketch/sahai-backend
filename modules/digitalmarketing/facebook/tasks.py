from celery import shared_task
import asyncio
from modules.common.database import async_session_maker
from modules.digitalmarketing.facebook.repositories import FacebookPostRepository, FacebookBoostRepository
from modules.digitalmarketing.facebook.services import FacebookPostService

@shared_task
def publish_scheduled_post(post_id: str):
    async def _publish():
        async with async_session_maker() as db:
            repo = FacebookPostRepository()
            service = FacebookPostService(repo)
            post = await repo.get_one(db, post_id, None)  # org_id not needed for scheduled
            if not post or post.status != "scheduled":
                return
            try:
                access_token = await service._get_page_token(db, str(post.organization_id), post.page_id)
                client = FacebookGraphClient(post.page_id, access_token)
                parts = []
                if post.title: parts.append(post.title)
                if post.content: parts.append(post.content)
                if post.hashtags: parts.append(post.hashtags)
                full_message = "\n\n".join(parts)
                result = await client.publish(full_message, post.media_url, post.media_type)
                await repo.update_status(db, post_id, "published", meta_post_id=result.get("id"))
                await db.commit()
            except Exception as e:
                await repo.update_status(db, post_id, "failed", error=str(e))
                await db.commit()
    asyncio.run(_publish())



# ====== PHASE 05-11: Additional sync tasks ======

@shared_task
def sync_facebook_campaigns():
    """Sync campaigns from Facebook to CRM."""
    pass

@shared_task
def sync_facebook_audiences():
    """Sync audiences from Facebook to CRM."""
    pass

@shared_task
def fetch_campaign_insights():
    """Fetch daily insights for all active campaigns."""
    pass
