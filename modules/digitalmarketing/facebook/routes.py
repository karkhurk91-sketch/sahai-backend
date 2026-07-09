from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import shutil
import os
from uuid import uuid4
from modules.auth.jwt import get_current_user
from modules.common.database import get_db
from modules.digitalmarketing.facebook.schemas import FacebookPostCreate, FacebookPostResponse
from modules.digitalmarketing.facebook.services import FacebookPostService, FacebookBoostService, FacebookSyncService
from modules.digitalmarketing.facebook.repositories import FacebookPostRepository, FacebookBoostRepository
from modules.common.logger import get_logger
from modules.common.config import API_BASE_URL

logger = get_logger(__name__)
router = APIRouter(prefix="/api/facebook", tags=["Facebook Marketing"])

# ---- Posts ----
@router.post("/posts", response_model=dict)
async def create_and_publish_post(
    data: FacebookPostCreate,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    org_id = user["org_id"]
    from sqlalchemy import select
    from modules.common.models import OrganizationChannel
    stmt = select(OrganizationChannel).where(
        OrganizationChannel.organization_id == org_id,
        OrganizationChannel.channel_type == "facebook",
        OrganizationChannel.enabled == True
    )
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    actual_page_id = None
    if channel:
        config = channel.config or {}
        if str(data.page_id) == str(channel.id):
            actual_page_id = config.get("page_id")
        elif data.page_id.isdigit():
            actual_page_id = data.page_id
        elif config.get("page_id") == data.page_id:
            actual_page_id = data.page_id
    if not actual_page_id:
        raise HTTPException(400, "Unable to resolve Facebook page ID")
    data.page_id = actual_page_id

    service = FacebookPostService(FacebookPostRepository())
    if not data.publish_now:
        result = await service.save_draft_post(db, org_id, data.page_id, data.title, data.content,
                                               data.hashtags, data.media_url, data.media_type)
        return result
    scheduled_for = None
    if data.scheduled_for:
        scheduled_for = datetime.fromisoformat(data.scheduled_for.replace("Z", "+00:00"))
    result = await service.publish_post(db, org_id, data.page_id, data.title, data.content,
                                        data.hashtags, data.media_url, data.media_type, scheduled_for)
    return result

@router.get("/posts", response_model=list[FacebookPostResponse])
async def list_posts(db: AsyncSession = Depends(get_db), user = Depends(get_current_user),
                     limit: int = 50, offset: int = 0, status: str = None):
    repo = FacebookPostRepository()
    posts = await repo.get_by_org(db, user["org_id"], limit, offset, status)
    return posts

@router.get("/posts/{post_id}", response_model=FacebookPostResponse)
async def get_post(post_id: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    repo = FacebookPostRepository()
    post = await repo.get_one(db, post_id, user["org_id"])
    if not post:
        raise HTTPException(404, "Post not found")
    return post

@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    repo = FacebookPostRepository()
    post = await repo.get_one(db, post_id, user["org_id"])
    if not post:
        raise HTTPException(404, "Post not found")
    if post.status != "draft":
        raise HTTPException(400, "Only draft posts can be deleted")
    await db.delete(post)
    await db.commit()
    return {"message": "Post deleted"}

@router.post("/posts/sync")
async def sync_facebook_posts(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.common.models import OrganizationChannel
    from sqlalchemy import select
    stmt = select(OrganizationChannel).where(
        OrganizationChannel.organization_id == user["org_id"],
        OrganizationChannel.channel_type == "facebook",
        OrganizationChannel.enabled == True
    )
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(400, "No active Facebook channel found")
    config = channel.config or {}
    page_id = config.get("page_id")
    access_token = config.get("page_access_token")
    if not access_token:
        raise HTTPException(400, "Page access token missing")
    service = FacebookSyncService()
    synced_count = await service.sync_posts_from_facebook(db, user["org_id"], page_id, access_token)
    return {"message": f"Synced {synced_count} posts", "synced_count": synced_count}

@router.get("/posts/{post_id}/eligibility")
async def check_post_eligibility(post_id: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    repo = FacebookPostRepository()
    post = await repo.get_one(db, post_id, user["org_id"])
    if not post:
        raise HTTPException(404, "Post not found")
    if post.status != "published":
        return {"eligible": False, "reason": "Post is not published"}
    service = FacebookPostService(repo)
    try:
        access_token = await service._get_page_token(db, user["org_id"], post.page_id)
        client = FacebookGraphClient(post.page_id, access_token)
        eligibility = await client.get_post_eligibility(post.meta_post_id)
        return {"eligible": eligibility.get("eligible", False), "reason": eligibility.get("reason", "")}
    except Exception as e:
        logger.error(f"Eligibility check failed: {e}")
        return {"eligible": False, "reason": f"Error: {str(e)}"}

# ---- Pages ----
@router.get("/pages")
async def list_pages(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.common.models import OrganizationChannel
    from sqlalchemy import select
    stmt = select(OrganizationChannel).where(
        OrganizationChannel.organization_id == user["org_id"],
        OrganizationChannel.channel_type == "facebook"
    )
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        return []
    return [{
        "id": str(channel.id),
        "page_id": channel.config.get("page_id"),
        "page_name": channel.config.get("page_name") or f"Page {channel.config.get('page_id')}",
        "page_category": channel.config.get("page_category"),
        "follower_count": channel.config.get("follower_count"),
        "is_active": channel.enabled
    }]

@router.post("/pages/sync")
async def sync_pages(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.common.models import OrganizationChannel, SocialAccount
    from sqlalchemy import select
    from modules.digitalmarketing.facebook.client import FacebookGraphClient
    from modules.digitalmarketing.facebook.utils import encrypt_token
    from modules.common.config import FACEBOOK_ACCESS_TOKEN
    import datetime
    stmt = select(SocialAccount).where(
        SocialAccount.organization_id == user["org_id"],
        SocialAccount.platform == "facebook",
        SocialAccount.is_active == True
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    user_token = account.access_token if account else FACEBOOK_ACCESS_TOKEN
    if not user_token:
        return {"message": "No user token found. Please add a Facebook page via Admin → Channels manually.", "page_count": 0}
    client = FacebookGraphClient(page_id=None, access_token=user_token)
    pages_data = await client.get_pages()
    stmt2 = select(OrganizationChannel).where(
        OrganizationChannel.organization_id == user["org_id"],
        OrganizationChannel.channel_type == "facebook"
    )
    result2 = await db.execute(stmt2)
    channel = result2.scalar_one_or_none()
    if not channel:
        channel = OrganizationChannel(organization_id=user["org_id"], channel_type="facebook", enabled=True, config={})
        db.add(channel)
        await db.flush()
    if pages_data:
        first_page = pages_data[0]
        channel.config = {
            "page_id": first_page["id"],
            "page_name": first_page["name"],
            "page_access_token": encrypt_token(first_page["access_token"]),
            "page_category": first_page.get("category"),
            "follower_count": first_page.get("fan_count"),
            "last_synced": datetime.datetime.utcnow().isoformat()
        }
        await db.commit()
    return {"message": "Pages synced", "page_count": len(pages_data)}

@router.post("/pages/{channel_uuid}/activate")
async def activate_page(channel_uuid: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.common.models import OrganizationChannel
    from sqlalchemy import update
    await db.execute(update(OrganizationChannel).where(
        OrganizationChannel.organization_id == user["org_id"],
        OrganizationChannel.channel_type == "facebook"
    ).values(enabled=False))
    await db.execute(update(OrganizationChannel).where(
        OrganizationChannel.id == channel_uuid,
        OrganizationChannel.organization_id == user["org_id"]
    ).values(enabled=True))
    await db.commit()
    return {"message": "Page activated"}

# ---- Boosts ----
class BoostCreateRequest(BaseModel):
    daily_budget: int
    duration_days: int
    targeting: dict
    goal: Optional[str] = "automatic"
    start_date: Optional[str] = None
    start_time: Optional[str] = None
    run_continuously: Optional[bool] = False
    cta: Optional[str] = None
    advantage_audience: Optional[bool] = False
    advantage_creative: Optional[bool] = False
    special_ad_category: Optional[str] = None

@router.post("/posts/{post_id}/boost")
async def boost_post(post_id: str, req: BoostCreateRequest, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    service = FacebookBoostService(FacebookPostRepository(), FacebookBoostRepository())
    try:
        boost = await service.create_boost(
            db, user["org_id"], post_id, req.daily_budget, req.duration_days, req.targeting,
            req.goal, req.start_date, req.start_time, req.run_continuously, req.cta,
            req.advantage_audience, req.advantage_creative, req.special_ad_category
        )
        return {"success": True, "boost_id": str(boost.id), "campaign_id": boost.meta_campaign_id}
    except Exception as e:
        logger.error(f"Boost creation failed: {e}")
        raise HTTPException(400, detail=str(e))

@router.get("/boosts")
async def list_boosts(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    repo = FacebookBoostRepository()
    boosts = await repo.get_by_org(db, user["org_id"])
    return boosts

@router.post("/boosts/{boost_id}/pause")
async def pause_boost(boost_id: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    service = FacebookBoostService(FacebookPostRepository(), FacebookBoostRepository())
    await service.pause_boost(db, boost_id, user["org_id"])
    return {"message": "Boost paused"}

@router.post("/boosts/{boost_id}/resume")
async def resume_boost(boost_id: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    repo = FacebookBoostRepository()
    await repo.update(db, boost_id, status="active")
    return {"message": "Boost resumed"}

# ---- Media Upload ----
@router.post("/upload-media")
async def upload_media(file: UploadFile = File(...), user = Depends(get_current_user)):
    upload_dir = "uploads/facebook"
    os.makedirs(upload_dir, exist_ok=True)
    ext = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{ext}"
    filepath = os.path.join(upload_dir, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    media_url = f"{API_BASE_URL}/static/facebook/{filename}"
    return {"media_url": media_url, "media_type": file.content_type.split("/")[0]}



# ====== PHASE 05: Campaign Management ======
from pydantic import BaseModel
class CampaignCreateRequest(BaseModel):
    page_id: str
    name: str
    objective: str
    daily_budget: int
    targeting: dict
    creative: dict
    start_time: Optional[str] = None
    end_time: Optional[str] = None

@router.post("/campaigns")
async def create_campaign(
    req: CampaignCreateRequest,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    from modules.digitalmarketing.facebook.campaign_service import CampaignService
    service = CampaignService()
    result = await service.create_campaign(
        db, user["org_id"], req.page_id, req.name, req.objective,
        req.daily_budget, req.targeting, req.creative,
        start_time=datetime.fromisoformat(req.start_time) if req.start_time else None,
        end_time=datetime.fromisoformat(req.end_time) if req.end_time else None
    )
    return result

@router.get("/campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.campaign_service import CampaignService
    service = CampaignService()
    # Return list from DB (TODO)
    return {"campaigns": []}

@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.campaign_service import CampaignService
    service = CampaignService()
    return await service.pause_campaign(db, campaign_id, user["org_id"])

# ====== PHASE 06: Audience Management ======
class AudienceCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    targeting_spec: Optional[dict] = None
    customer_list: Optional[List[str]] = None  # for custom audience

@router.post("/audiences")
async def create_audience(req: AudienceCreateRequest, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.audience_service import AudienceService
    service = AudienceService()
    if req.customer_list:
        result = await service.create_custom_audience(db, user["org_id"], req.name, req.customer_list)
    else:
        result = await service.create_saved_audience(db, user["org_id"], req.name, req.targeting_spec or {})
    return result

@router.get("/audiences")
async def list_audiences(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.audience_service import AudienceService
    service = AudienceService()
    return await service.list_audiences(db, user["org_id"])

# ====== PHASE 07: Ad Management ======
class CreativeCreateRequest(BaseModel):
    name: str
    page_id: str
    media_url: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    cta_type: Optional[str] = None
    cta_url: Optional[str] = None

@router.post("/creatives")
async def create_creative(req: CreativeCreateRequest, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.ad_service import AdService
    service = AdService()
    # Store creative in DB
    return {"creative_id": "123"}

@router.get("/creatives")
async def list_creatives(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    return {"creatives": []}

# ====== PHASE 08: Analytics ======
@router.get("/analytics")
async def get_analytics(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.analytics_service import AnalyticsService
    service = AnalyticsService()
    return await service.get_dashboard_metrics(user["org_id"], None)

# ====== PHASE 09: Lead Attribution ======
@router.get("/leads")
async def get_facebook_leads(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.attribution_service import AttributionService
    service = AttributionService()
    # Return stored leads
    return []

# ====== PHASE 10: ROI ======
@router.get("/roi")
async def get_roi(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    from modules.digitalmarketing.facebook.roi_service import ROIService
    service = ROIService()
    return await service.calculate_roi(user["org_id"], None)

# ====== PHASE 11: AI ======
class AIGenerateRequest(BaseModel):
    product_name: str
    price: str
    location: str
    description: Optional[str] = None

@router.post("/ai/generate-campaign")
async def generate_campaign(req: AIGenerateRequest):
    from modules.digitalmarketing.facebook.ai_service import AIService
    service = AIService()
    result = await service.generate_campaign(req.dict())
    return result
