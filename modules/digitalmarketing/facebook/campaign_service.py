"""
Campaign Service for Facebook Marketing
Handles creation, update, pause/resume, and insights of ad campaigns.
"""
from datetime import datetime
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.logger import get_logger
from modules.digitalmarketing.facebook.client import FacebookGraphClient
from modules.digitalmarketing.facebook.repositories import FacebookPostRepository
from modules.digitalmarketing.facebook.utils import decrypt_token

logger = get_logger(__name__)

class CampaignService:
    def __init__(self, post_repo=None):
        self.post_repo = post_repo or FacebookPostRepository()

    async def create_campaign(self, db: AsyncSession, org_id: str, page_id: str,
                              name: str, objective: str, daily_budget: int,
                              targeting: dict, creative: dict,
                              lifetime_budget: Optional[int] = None,
                              start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None,
                              status: str = "ACTIVE"):
        """Create a full ad campaign (campaign + adset + ad creative + ad)."""
        # 1. Get page access token
        from modules.digitalmarketing.facebook.services import FacebookPostService
        post_service = FacebookPostService(self.post_repo)
        access_token = await post_service._get_page_token(db, org_id, page_id)
        client = FacebookGraphClient(page_id, access_token)
        ad_account_id = os.getenv("FACEBOOK_AD_ACCOUNT_ID")
        # 2. Create campaign
        campaign = await client.create_campaign(ad_account_id, name, objective, status, daily_budget, lifetime_budget)
        # 3. Create adset
        adset = await client.create_adset(ad_account_id, campaign["id"], name + " Ad Set", daily_budget, targeting, start_time, end_time)
        # 4. Create creative
        creative_obj = await client.create_ad_creative(ad_account_id, name + " Creative", page_id, creative)
        # 5. Create ad
        ad = await client.create_ad(ad_account_id, adset["id"], creative_obj["id"], status)
        # 6. Store in DB (TODO)
        return {"campaign_id": campaign["id"], "adset_id": adset["id"], "creative_id": creative_obj["id"], "ad_id": ad["id"]}

    async def pause_campaign(self, db: AsyncSession, campaign_id: str, org_id: str):
        # Call Facebook API to pause
        # Update status in DB
        return {"status": "paused"}

    async def get_insights(self, db: AsyncSession, object_id: str, object_type: str = "campaign"):
        # Fetch insights from Facebook
        return {"impressions": 0, "clicks": 0, "spend": 0}