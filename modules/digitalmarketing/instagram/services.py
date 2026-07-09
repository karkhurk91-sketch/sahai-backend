from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.logger import get_logger
from modules.digitalmarketing.instagram.client import InstagramGraphClient
from modules.digitalmarketing.instagram.repositories import InstagramPostRepository, InstagramAccountRepository
from modules.digitalmarketing.instagram.models import InstagramPost

logger = get_logger(__name__)

class InstagramPostService:
    def __init__(self, post_repo: InstagramPostRepository, account_repo: InstagramAccountRepository):
        self.post_repo = post_repo
        self.account_repo = account_repo

    async def _get_ig_user_id(self, db: AsyncSession, org_id: str) -> str:
        # Retrieve active Instagram account from DB
        stmt = select(InstagramAccount).where(InstagramAccount.organization_id == org_id, InstagramAccount.is_active == True)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError("No active Instagram account found. Please connect one.")
        return account.ig_user_id

    async def publish_post(self, db: AsyncSession, org_id: str, caption: str, media_url: str, media_type: str = "IMAGE", carousel_children: list = None, scheduled_for: datetime = None) -> dict:
        ig_user_id = await self._get_ig_user_id(db, org_id)
        # Get access token from organization_channels (reuse Facebook token)
        from modules.common.models import OrganizationChannel
        from sqlalchemy import select
        stmt = select(OrganizationChannel).where(OrganizationChannel.organization_id == org_id, OrganizationChannel.channel_type == "facebook")
        result = await db.execute(stmt)
        channel = result.scalar_one_or_none()
        if not channel:
            raise ValueError("No Facebook channel found. Instagram requires a connected Facebook Page.")
        access_token = channel.config.get("page_access_token")
        client = InstagramGraphClient(ig_user_id, access_token)

        # Create container
        container = await client.create_media_container(media_url, caption, media_type, carousel_children)
        creation_id = container.get("id")

        if scheduled_for:
            # For scheduled posts, we'd store the container ID and publish later
            post = await self.post_repo.create(
                db,
                organization_id=org_id,
                ig_user_id=ig_user_id,
                caption=caption,
                media_url=media_url,
                media_type=media_type,
                status="scheduled",
                scheduled_for=scheduled_for,
                is_scheduled=True
            )
            await db.commit()
            return {"message": "Post scheduled", "db_id": str(post.id)}
        else:
            # Publish immediately
            result = await client.publish_media(creation_id)
            post = await self.post_repo.create(
                db,
                organization_id=org_id,
                ig_user_id=ig_user_id,
                caption=caption,
                media_url=media_url,
                media_type=media_type,
                status="published",
                meta_post_id=result.get("id"),
                published_at=datetime.utcnow()
            )
            await db.commit()
            return {"post_id": result.get("id"), "db_id": str(post.id)}