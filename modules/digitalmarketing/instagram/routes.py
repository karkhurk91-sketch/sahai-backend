from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from modules.auth.jwt import get_current_user
from modules.common.database import get_db
from modules.digitalmarketing.instagram.schemas import InstagramPostCreate, InstagramPostResponse
from modules.digitalmarketing.instagram.services import InstagramPostService
from modules.digitalmarketing.instagram.repositories import InstagramPostRepository, InstagramAccountRepository
from modules.digitalmarketing.instagram.models import InstagramAccount

router = APIRouter(prefix="/api/instagram", tags=["Instagram Marketing"])

@router.post("/posts")
async def create_and_publish_post(data: InstagramPostCreate, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    service = InstagramPostService(InstagramPostRepository(), InstagramAccountRepository())
    scheduled_for = None
    if data.scheduled_for:
        scheduled_for = datetime.fromisoformat(data.scheduled_for.replace("Z", "+00:00"))
    result = await service.publish_post(
        db, user["org_id"], data.caption, data.media_url, data.media_type,
        data.carousel_children, scheduled_for
    )
    return result

@router.get("/posts", response_model=list[InstagramPostResponse])
async def list_posts(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    repo = InstagramPostRepository()
    posts = await repo.get_by_org(db, user["org_id"])
    return posts

@router.post("/accounts/sync")
async def sync_account(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.common.models import OrganizationChannel
    from sqlalchemy import select
    from modules.digitalmarketing.instagram.client import InstagramGraphClient
    # Get Facebook channel
    stmt = select(OrganizationChannel).where(OrganizationChannel.organization_id == user["org_id"], OrganizationChannel.channel_type == "facebook")
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(400, "No Facebook channel found. Please connect a Facebook Page first.")
    page_id = channel.config.get("page_id")
    access_token = channel.config.get("page_access_token")
    # Get Instagram Business Account from Facebook Page
    fb_client = InstagramGraphClient(None, access_token)  # we'll use a helper
    ig_accounts = await fb_client.get_instagram_accounts(page_id)
    # For simplicity, take the first
    if ig_accounts:
        ig_user_id = ig_accounts[0]["id"]
        # Fetch details
        client = InstagramGraphClient(ig_user_id, access_token)
        info = await client.get_user_info()
        repo = InstagramAccountRepository()
        await repo.upsert(db, user["org_id"], {
            "ig_user_id": ig_user_id,
            "username": info["username"],
            "name": info.get("name"),
            "profile_picture_url": info.get("profile_picture_url"),
            "follower_count": info.get("follower_count", 0),
            "follows_count": info.get("follows_count", 0),
            "media_count": info.get("media_count", 0),
            "account_type": info.get("account_type"),
            "is_active": True,
            "last_synced_at": datetime.utcnow()
        })
        await db.commit()
        return {"message": "Instagram account synced", "ig_user_id": ig_user_id}
    else:
        raise HTTPException(404, "No Instagram Business Account found for this Facebook Page.")