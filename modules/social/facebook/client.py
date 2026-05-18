import httpx
from typing import Dict, Any, Optional
from ..base import SocialPlatform
from modules.common.logger import get_logger

logger = get_logger(__name__)

class FacebookClient(SocialPlatform):
    FACEBOOK_API_VERSION = "v21.0"
    BASE_URL = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}"
    
    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to Facebook Graph API."""
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        params = kwargs.pop("params", {})
        params["access_token"] = self.access_token
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, params=params, **kwargs)
            response.raise_for_status()
            return response.json()
    
    async def _download_image(self, url: str) -> bytes:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    
    async def post_message(self, message: str, media_url: Optional[str] = None) -> Dict[str, Any]:
        """Post to Facebook Page feed."""
        if media_url:
            # Upload photo with caption
            return await self._request(
                "POST",
                f"{self.account_id}/photos",
                data={"caption": message},
                files={"source": ("image.jpg", await self._download_image(media_url), "image/jpeg")}
            )
        else:
            return await self._request(
                "POST",
                f"{self.account_id}/feed",
                data={"message": message}
            )
    
    async def create_ad_campaign(self, campaign_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a complete lead ad campaign."""
        # 1. Campaign
        campaign = await self._request(
            "POST",
            f"act_{campaign_data['ad_account_id']}/campaigns",
            data={
                "name": campaign_data["name"],
                "objective": "OUTCOME_LEADS",
                "status": "ACTIVE",
                "special_ad_categories": []
            }
        )
        # 2. Ad Set
        adset = await self._request(
            "POST",
            f"act_{campaign_data['ad_account_id']}/adsets",
            data={
                "name": f"{campaign_data['name']} Ad Set",
                "campaign_id": campaign["id"],
                "daily_budget": campaign_data["daily_budget"],
                "billing_event": "IMPRESSIONS",
                "optimization_goal": "LEAD_GENERATION",
                "targeting": campaign_data["targeting"],
                "status": "ACTIVE",
                "start_time": campaign_data.get("start_time")
            }
        )
        # 3. Lead Form
        form = await self._request(
            "POST",
            f"{self.account_id}/leadgen_forms",
            data={
                "name": f"{campaign_data['name']} Form",
                "page_id": self.account_id,
                "status": "ACTIVE",
                "questions": campaign_data["lead_form_questions"]
            }
        )
        # 4. Ad Creative
        creative = await self._request(
            "POST",
            f"act_{campaign_data['ad_account_id']}/adcreatives",
            data={
                "name": f"{campaign_data['name']} Creative",
                "object_story_spec": campaign_data.get("story_spec", {})
            }
        )
        # 5. Ad
        ad = await self._request(
            "POST",
            f"act_{campaign_data['ad_account_id']}/ads",
            data={
                "name": campaign_data["name"],
                "adset_id": adset["id"],
                "creative": {"creative_id": creative["id"]},
                "leadgen_form_id": form["id"],
                "status": "ACTIVE"
            }
        )
        return {
            "campaign_id": campaign["id"],
            "adset_id": adset["id"],
            "lead_form_id": form["id"],
            "ad_id": ad["id"]
        }
    
    async def get_lead_form_submissions(self, since: Optional[str] = None) -> list:
        """Retrieve leads from a form (requires lead_form_id stored in DB)."""
        # Implementation depends on your stored form IDs
        raise NotImplementedError("Lead retrieval not yet implemented")
