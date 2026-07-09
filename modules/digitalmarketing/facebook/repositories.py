from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from modules.digitalmarketing.facebook.models import FacebookPost, FacebookBoost

class FacebookPostRepository:
    async def create(self, db: AsyncSession, **kwargs) -> FacebookPost:
        post = FacebookPost(**kwargs)
        db.add(post)
        await db.flush()
        return post

    async def update_status(self, db: AsyncSession, post_id: str, status: str,
                            meta_post_id: str = None, error: str = None):
        values = {"status": status, "updated_at": func.now()}
        if meta_post_id:
            values["meta_post_id"] = meta_post_id
            values["published_at"] = func.now()
        if error:
            values["error_message"] = error
        await db.execute(update(FacebookPost).where(FacebookPost.id == post_id).values(**values))

    async def get_by_org(self, db: AsyncSession, org_id: str, limit: int = 50, offset: int = 0, status: str = None):
        stmt = select(FacebookPost).where(FacebookPost.organization_id == org_id)
        if status:
            stmt = stmt.where(FacebookPost.status == status)
        stmt = stmt.order_by(FacebookPost.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_one(self, db: AsyncSession, post_id: str, org_id: str):
        stmt = select(FacebookPost).where(FacebookPost.id == post_id, FacebookPost.organization_id == org_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_scheduled_posts(self, db: AsyncSession) -> list[FacebookPost]:
        stmt = select(FacebookPost).where(FacebookPost.status == "scheduled", FacebookPost.scheduled_for <= func.now())
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_meta_post_id(self, db: AsyncSession, org_id: str, meta_post_id: str):
        stmt = select(FacebookPost).where(FacebookPost.organization_id == org_id, FacebookPost.meta_post_id == meta_post_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

class FacebookBoostRepository:
    async def create(self, db: AsyncSession, **kwargs) -> FacebookBoost:
        boost = FacebookBoost(**kwargs)
        db.add(boost)
        await db.flush()
        return boost

    async def update(self, db: AsyncSession, boost_id: str, **values):
        await db.execute(update(FacebookBoost).where(FacebookBoost.id == boost_id).values(**values))

    async def get_by_org(self, db: AsyncSession, org_id: str, limit=50):
        stmt = select(FacebookBoost).where(FacebookBoost.organization_id == org_id).order_by(FacebookBoost.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_one(self, db: AsyncSession, boost_id: str, org_id: str):
        stmt = select(FacebookBoost).where(FacebookBoost.id == boost_id, FacebookBoost.organization_id == org_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()