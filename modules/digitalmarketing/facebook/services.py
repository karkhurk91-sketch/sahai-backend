import httpx
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.logger import get_logger
from modules.digitalmarketing.facebook.client import FacebookGraphClient
from modules.digitalmarketing.facebook.repositories import FacebookPostRepository, FacebookBoostRepository
from modules.digitalmarketing.facebook.models import FacebookBoost
from modules.digitalmarketing.facebook.utils import encrypt_token, decrypt_token

logger = get_logger(__name__)

class FacebookPostService:
    def __init__(self, post_repo: FacebookPostRepository):
        self.post_repo = post_repo

    async def _get_page_token(self, db: AsyncSession, org_id: str, page_id: str) -> str:
        from sqlalchemy import select
        from modules.common.models import OrganizationChannel
        from modules.common.config import FACEBOOK_ACCESS_TOKEN
        stmt = select(OrganizationChannel).where(
            OrganizationChannel.organization_id == org_id,
            OrganizationChannel.channel_type == "facebook",
            OrganizationChannel.enabled == True
        )
        result = await db.execute(stmt)
        channel = result.scalar_one_or_none()
        token = None
        if channel:
            config = channel.config or {}
            if config.get("page_id") == page_id:
                token = config.get("page_access_token")
        if not token:
            token = FACEBOOK_ACCESS_TOKEN
            if not token:
                raise ValueError(f"No token for page {page_id}")
        try:
            return decrypt_token(token)
        except:
            return token

    async def publish_post(self, db, org_id, page_id, title, content, hashtags,
                           media_url, media_type, scheduled_for=None):
        parts = []
        if title: parts.append(title)
        if content: parts.append(content)
        if hashtags: parts.append(hashtags)
        full_message = "\n\n".join(parts)
        access_token = await self._get_page_token(db, org_id, page_id)
        if scheduled_for:
            post = await self.post_repo.create(db, organization_id=org_id, page_id=page_id,
                title=title, content=content, hashtags=hashtags, media_url=media_url,
                media_type=media_type, status="scheduled", scheduled_for=scheduled_for, is_scheduled=True)
            await db.commit()
            from modules.digitalmarketing.facebook.tasks import publish_scheduled_post
            publish_scheduled_post.apply_async(args=[str(post.id)], eta=scheduled_for)
            return {"message": "Post scheduled", "db_id": str(post.id), "scheduled_for": scheduled_for.isoformat()}
        post = await self.post_repo.create(db, organization_id=org_id, page_id=page_id,
            title=title, content=content, hashtags=hashtags, media_url=media_url,
            media_type=media_type, status="draft")
        await db.commit()
        try:
            client = FacebookGraphClient(page_id, access_token)
            try:
                result = await client.publish(full_message, media_url, media_type)
            except ValueError:
                logger.warning("Media URL invalid, posting text only.")
                result = await client.post_text(full_message)
            await self.post_repo.update_status(db, str(post.id), "published", meta_post_id=result.get("id"))
            await db.commit()
            return {"post_id": result.get("id"), "db_id": str(post.id)}
        except Exception as e:
            await self.post_repo.update_status(db, str(post.id), "failed", error=str(e))
            await db.commit()
            raise

    async def save_draft_post(self, db, org_id, page_id, title, content, hashtags, media_url, media_type):
        post = await self.post_repo.create(db, organization_id=org_id, page_id=page_id,
            title=title, content=content, hashtags=hashtags, media_url=media_url,
            media_type=media_type, status="draft")
        await db.commit()
        return {"db_id": str(post.id), "message": "Post saved as draft"}

class FacebookBoostService:
    def __init__(self, post_repo: FacebookPostRepository, boost_repo: FacebookBoostRepository):
        self.post_repo = post_repo
        self.boost_repo = boost_repo

    def _map_goal_to_objective(self, goal: str) -> str:
        mapping = {"automatic": "REACH", "messages": "MESSAGES", "video_views": "VIDEO_VIEWS",
                   "leads": "LEAD_GENERATION", "calls": "CALLS", "engagement": "POST_ENGAGEMENT"}
        return mapping.get(goal, "REACH")

    async def _resolve_interest_ids(self, client: FacebookGraphClient, interests: list) -> list:
        if not interests:
            return []
        resolved = []
        for name in interests:
            interest_id = await client.search_interest(name)
            if interest_id:
                resolved.append({"id": interest_id})
            else:
                logger.warning(f"Interest '{name}' not found.")
        return resolved

    async def create_boost(self, db: AsyncSession, org_id: str, post_id: str,
                           daily_budget: int, duration_days: int, targeting: dict,
                           goal: str = "automatic", start_date: Optional[str] = None,
                           start_time: Optional[str] = None, run_continuously: bool = False,
                           cta: Optional[str] = None, advantage_audience: bool = False,
                           advantage_creative: bool = False, special_ad_category: Optional[str] = None):
        from modules.common.config import FACEBOOK_AD_ACCOUNT_ID
        from modules.digitalmarketing.facebook.services import FacebookPostService
        post = await self.post_repo.get_one(db, post_id, org_id)
        if not post:
            raise ValueError("Post not found")
        if post.status != "published":
            raise ValueError("Only published posts can be boosted")
        post_service = FacebookPostService(self.post_repo)
        access_token = await post_service._get_page_token(db, org_id, post.page_id)
        ad_account_id = FACEBOOK_AD_ACCOUNT_ID
        if not ad_account_id:
            raise ValueError("FACEBOOK_AD_ACCOUNT_ID not set")
        client = FacebookGraphClient(post.page_id, access_token)
        eligibility = await client.get_post_eligibility(post.meta_post_id)
        if not eligibility.get("eligible"):
            raise ValueError(f"Post not eligible: {eligibility.get('reason')}")
        interests = targeting.get("interests", [])
        if interests:
            interest_objects = await self._resolve_interest_ids(client, interests)
            if interest_objects:
                targeting["interests"] = interest_objects
            else:
                targeting.pop("interests", None)
        objective = self._map_goal_to_objective(goal)
        now = datetime.utcnow()
        if start_date and start_time:
            start_dt = datetime.fromisoformat(f"{start_date}T{start_time}:00+00:00")
        else:
            start_dt = now + timedelta(hours=1)
        if run_continuously:
            end_dt = None
        else:
            end_dt = start_dt + timedelta(days=duration_days)
        if "geo_locations" not in targeting:
            targeting["geo_locations"] = {"countries": ["IN"]}
        if "age_min" not in targeting:
            targeting["age_min"] = 18
        if "age_max" not in targeting:
            targeting["age_max"] = 65
        result = await client.create_boost_ad(ad_account_id, post.page_id, post.meta_post_id,
            daily_budget * 100, targeting, duration_days, start_dt.isoformat(),
            end_dt.isoformat() if end_dt else None, cta, special_ad_category, objective)
        boost = await self.boost_repo.create(db, organization_id=org_id, post_id=post_id,
            meta_campaign_id=result["campaign_id"], meta_adset_id=result["adset_id"],
            meta_ad_id=result["ad_id"], daily_budget_cents=daily_budget*100,
            duration_days=duration_days, targeting=targeting, status="active",
            started_at=start_dt, ended_at=end_dt, goal=goal, cta_type=cta,
            start_time=start_dt, end_time=end_dt, advantage_audience=advantage_audience,
            advantage_creative=advantage_creative, special_ad_category=special_ad_category)
        await db.commit()
        return boost

    async def pause_boost(self, db: AsyncSession, boost_id: str, org_id: str):
        boost = await self.boost_repo.get_one(db, boost_id, org_id)
        if not boost:
            raise ValueError("Boost not found")
        await self.boost_repo.update(db, boost_id, status="paused")
        await db.commit()

class FacebookSyncService:
    async def sync_posts_from_facebook(self, db: AsyncSession, org_id: str, page_id: str, access_token: str) -> int:
        from modules.digitalmarketing.facebook.client import FacebookGraphClient
        from modules.digitalmarketing.facebook.repositories import FacebookPostRepository
        from modules.digitalmarketing.facebook.utils import decrypt_token
        try:
            token = decrypt_token(access_token)
        except:
            token = access_token
        client = FacebookGraphClient(page_id, token)
        posts_data = await client.get_page_posts(limit=100)
        repo = FacebookPostRepository()
        synced = 0
        for fb_post in posts_data:
            existing = await repo.get_by_meta_post_id(db, org_id, fb_post["id"])
            if existing:
                if existing.status == "published" and not fb_post.get("is_published", True):
                    existing.status = "deleted"
                    existing.deleted = True
                existing.last_synced_at = datetime.utcnow()
            else:
                await repo.create(db, organization_id=org_id, page_id=page_id,
                    meta_post_id=fb_post["id"], title=fb_post.get("message", "")[:100],
                    content=fb_post.get("message", ""), status="published",
                    published_at=datetime.fromisoformat(fb_post["created_time"]),
                    created_at=datetime.fromisoformat(fb_post["created_time"]),
                    last_synced_at=datetime.utcnow())
                synced += 1
        await db.commit()
        return synced