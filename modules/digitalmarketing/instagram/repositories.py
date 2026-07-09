from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from modules.digitalmarketing.instagram.models import InstagramAccount, InstagramPost, InstagramInsights

class InstagramAccountRepository:
    async def upsert(self, db: AsyncSession, org_id: str, data: dict) -> InstagramAccount:
        stmt = select(InstagramAccount).where(InstagramAccount.organization_id == org_id, InstagramAccount.ig_user_id == data["ig_user_id"])
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        if account:
            for key, value in data.items():
                setattr(account, key, value)
            account.updated_at = func.now()
        else:
            account = InstagramAccount(organization_id=org_id, **data)
            db.add(account)
        await db.flush()
        return account

class InstagramPostRepository:
    async def create(self, db: AsyncSession, **kwargs) -> InstagramPost:
        post = InstagramPost(**kwargs)
        db.add(post)
        await db.flush()
        return post

    async def update_status(self, db: AsyncSession, post_id: str, status: str, meta_post_id: str = None, error: str = None):
        values = {"status": status, "updated_at": func.now()}
        if meta_post_id:
            values["meta_post_id"] = meta_post_id
            values["published_at"] = func.now()
        if error:
            values["error_message"] = error
        await db.execute(update(InstagramPost).where(InstagramPost.id == post_id).values(**values))

    async def get_by_org(self, db: AsyncSession, org_id: str, limit=50):
        stmt = select(InstagramPost).where(InstagramPost.organization_id == org_id).order_by(InstagramPost.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()