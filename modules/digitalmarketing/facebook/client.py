import httpx
from typing import Optional
from modules.common.logger import get_logger

logger = get_logger(__name__)

class FacebookGraphClient:
    BASE_URL = "https://graph.facebook.com/v20.0"
    DEFAULT_TIMEOUT = 30.0

    def __init__(self, page_id: Optional[str], access_token: str):
        self.page_id = page_id
        self.access_token = access_token

    async def _request(self, method: str, url: str, timeout: float = DEFAULT_TIMEOUT, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning(f"Request timed out. Retrying once...")
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()

    async def post_text(self, message: str) -> dict:
        url = f"{self.BASE_URL}/{self.page_id}/feed"
        data = {"message": message, "access_token": self.access_token}
        return await self._request("POST", url, data=data)

    async def post_image(self, message: str, image_url: str) -> dict:
        if not image_url.startswith(('http://', 'https://')):
            raise ValueError(f"Invalid image URL: {image_url}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            image_data = img_resp.content
        url = f"{self.BASE_URL}/{self.page_id}/photos"
        files = {"source": ("image.jpg", image_data, "image/jpeg")}
        data = {"caption": message, "access_token": self.access_token, "published": True}
        return await self._request("POST", url, timeout=60.0, files=files, data=data)

    async def post_video(self, message: str, video_url: str) -> dict:
        if not video_url.startswith(('http://', 'https://')):
            raise ValueError(f"Invalid video URL: {video_url}")
        async with httpx.AsyncClient(timeout=120.0) as client:
            video_resp = await client.get(video_url)
            video_resp.raise_for_status()
            video_data = video_resp.content
        url = f"{self.BASE_URL}/{self.page_id}/videos"
        files = {"source": ("video.mp4", video_data, "video/mp4")}
        data = {"title": message[:100], "description": message, "access_token": self.access_token, "published": "true"}
        return await self._request("POST", url, timeout=120.0, files=files, data=data)

    async def publish(self, message: str, media_url: Optional[str] = None, media_type: Optional[str] = None):
        if not media_url:
            return await self.post_text(message)
        if media_type == "video":
            return await self.post_video(message, media_url)
        return await self.post_image(message, media_url)

    async def get_pages(self) -> list[dict]:
        url = f"{self.BASE_URL}/me/accounts"
        params = {"access_token": self.access_token}
        result = await self._request("GET", url, params=params)
        return result.get("data", [])

    async def get_page_posts(self, limit=50):
        url = f"{self.BASE_URL}/{self.page_id}/posts"
        params = {
            "access_token": self.access_token,
            "limit": limit,
            "fields": "id,message,created_time,permalink_url,status_type,is_published"
        }
        result = await self._request("GET", url, params=params)
        return result.get("data", [])

    async def search_interest(self, query: str) -> Optional[str]:
        url = f"{self.BASE_URL}/search"
        params = {"type": "adinterest", "q": query, "access_token": self.access_token, "limit": 1}
        try:
            result = await self._request("GET", url, params=params)
            data = result.get("data", [])
            return data[0]["id"] if data else None
        except Exception as e:
            logger.error(f"Interest search failed for '{query}': {e}")
            return None

    async def get_post_eligibility(self, post_id: str) -> dict:
        if "_" not in post_id:
            post_id = f"{self.page_id}_{post_id}"
        url = f"{self.BASE_URL}/{post_id}"
        params = {"fields": "is_eligible_for_promotion,promotion_eligibility", "access_token": self.access_token}
        try:
            result = await self._request("GET", url, params=params)
            eligible = result.get("is_eligible_for_promotion", False)
            reason = ""
            if not eligible:
                promo = result.get("promotion_eligibility", [])
                if promo and isinstance(promo, list) and len(promo) > 0:
                    reason = promo[0].get("reason", "Unknown reason")
            return {"eligible": eligible, "reason": reason}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                error_detail = e.response.json().get("error", {})
                error_msg = error_detail.get("message", "")
                if "permission" in error_msg.lower():
                    return {"eligible": False, "reason": "Missing permissions. Please reconnect your Facebook page with 'pages_read_engagement'."}
                return {"eligible": False, "reason": f"Post not found or inaccessible: {error_msg}"}
            logger.error(f"Eligibility check failed: {e}")
            return {"eligible": False, "reason": f"Error: {str(e)}"}
        except Exception as e:
            logger.error(f"Eligibility check failed: {e}")
            return {"eligible": False, "reason": f"Error: {str(e)}"}

    async def create_boost_ad(
        self,
        ad_account_id: str,
        page_id: str,
        post_id: str,
        daily_budget_cents: int,
        targeting: dict,
        duration_days: int,
        start_time: str,
        end_time: Optional[str] = None,
        cta: Optional[str] = None,
        special_ad_category: Optional[str] = None,
        objective: str = "REACH"
    ) -> dict:
        campaign_url = f"{self.BASE_URL}/{ad_account_id}/campaigns"
        campaign_data = {
            "name": f"Boost Campaign for post {post_id}",
            "objective": objective,
            "status": "ACTIVE",
            "special_ad_categories": [special_ad_category] if special_ad_category and special_ad_category != "none" else [],
            "access_token": self.access_token
        }
        campaign = await self._request("POST", campaign_url, data=campaign_data)

        adset_url = f"{self.BASE_URL}/{ad_account_id}/adsets"
        adset_data = {
            "name": f"Ad Set for post {post_id}",
            "campaign_id": campaign["id"],
            "daily_budget": daily_budget_cents,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "REACH" if objective == "REACH" else "CONVERSIONS",
            "targeting": targeting,
            "status": "ACTIVE",
            "start_time": start_time,
            "end_time": end_time,
            "access_token": self.access_token
        }
        adset = await self._request("POST", adset_url, data=adset_data)

        creative_url = f"{self.BASE_URL}/{ad_account_id}/adcreatives"
        creative_data = {
            "name": f"Creative for post {post_id}",
            "object_story_id": f"{page_id}_{post_id}",
            "access_token": self.access_token
        }
        if cta and cta != "none":
            creative_data["object_story_spec"] = {
                "page_id": page_id,
                "post_id": post_id,
                "link_data": {"call_to_action": {"type": cta}}
            }
        creative = await self._request("POST", creative_url, json=creative_data)

        ad_url = f"{self.BASE_URL}/{ad_account_id}/ads"
        ad_data = {
            "name": f"Ad for post {post_id}",
            "adset_id": adset["id"],
            "creative": {"creative_id": creative["id"]},
            "status": "ACTIVE",
            "access_token": self.access_token
        }
        ad = await self._request("POST", ad_url, data=ad_data)

        return {
            "campaign_id": campaign["id"],
            "adset_id": adset["id"],
            "ad_id": ad["id"]
        }

    # ====== PHASE 05-07: Campaign, AdSet, Creative, Ad methods ======

    async def create_campaign(
        self,
        ad_account_id: str,
        name: str,
        objective: str,
        status: str = "ACTIVE",
        daily_budget_cents: Optional[int] = None,
        lifetime_budget_cents: Optional[int] = None,
        special_ad_categories: list = None
    ) -> dict:
        url = f"{self.BASE_URL}/{ad_account_id}/campaigns"
        data = {
            "name": name,
            "objective": objective,
            "status": status,
            "access_token": self.access_token
        }
        if daily_budget_cents:
            data["daily_budget"] = daily_budget_cents
        if lifetime_budget_cents:
            data["lifetime_budget"] = lifetime_budget_cents
        if special_ad_categories:
            data["special_ad_categories"] = special_ad_categories
        return await self._request("POST", url, data=data)

    async def create_adset(
        self,
        ad_account_id: str,
        campaign_id: str,
        name: str,
        daily_budget_cents: Optional[int] = None,
        lifetime_budget_cents: Optional[int] = None,
        targeting: dict = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        optimization_goal: str = "REACH",
        status: str = "ACTIVE"
    ) -> dict:
        url = f"{self.BASE_URL}/{ad_account_id}/adsets"
        data = {
            "name": name,
            "campaign_id": campaign_id,
            "status": status,
            "targeting": targeting or {},
            "access_token": self.access_token,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": optimization_goal
        }
        if daily_budget_cents:
            data["daily_budget"] = daily_budget_cents
        if lifetime_budget_cents:
            data["lifetime_budget"] = lifetime_budget_cents
        if start_time:
            data["start_time"] = start_time
        if end_time:
            data["end_time"] = end_time
        return await self._request("POST", url, data=data)

    async def create_ad_creative(
        self,
        ad_account_id: str,
        name: str,
        page_id: str,
        creative_data: dict
    ) -> dict:
        url = f"{self.BASE_URL}/{ad_account_id}/adcreatives"
        data = {
            "name": name,
            "access_token": self.access_token,
            "object_story_spec": {
                "page_id": page_id,
                "link_data": {}
            }
        }
        if creative_data.get("link"):
            data["object_story_spec"]["link_data"]["link"] = creative_data["link"]
        if creative_data.get("message"):
            data["object_story_spec"]["link_data"]["message"] = creative_data["message"]
        if creative_data.get("headline"):
            data["object_story_spec"]["link_data"]["name"] = creative_data["headline"]
        if creative_data.get("description"):
            data["object_story_spec"]["link_data"]["description"] = creative_data["description"]
        if creative_data.get("picture"):
            data["object_story_spec"]["link_data"]["picture"] = creative_data["picture"]
        if creative_data.get("call_to_action"):
            data["object_story_spec"]["link_data"]["call_to_action"] = {"type": creative_data["call_to_action"]}
        return await self._request("POST", url, json=data)

    async def create_ad(
        self,
        ad_account_id: str,
        adset_id: str,
        creative_id: str,
        status: str = "ACTIVE",
        name: Optional[str] = None
    ) -> dict:
        url = f"{self.BASE_URL}/{ad_account_id}/ads"
        data = {
            "name": name or f"Ad for {adset_id}",
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": status,
            "access_token": self.access_token
        }
        return await self._request("POST", url, data=data)

    async def list_campaigns(self, ad_account_id: str, fields: str = None) -> list:
        url = f"{self.BASE_URL}/{ad_account_id}/campaigns"
        params = {"access_token": self.access_token, "limit": 100}
        if fields:
            params["fields"] = fields
        result = await self._request("GET", url, params=params)
        return result.get("data", [])

    async def list_adsets(self, ad_account_id: str, campaign_id: str = None) -> list:
        url = f"{self.BASE_URL}/{ad_account_id}/adsets"
        params = {"access_token": self.access_token}
        if campaign_id:
            params["campaign_id"] = campaign_id
        result = await self._request("GET", url, params=params)
        return result.get("data", [])

    async def list_ads(self, ad_account_id: str, adset_id: str = None) -> list:
        url = f"{self.BASE_URL}/{ad_account_id}/ads"
        params = {"access_token": self.access_token}
        if adset_id:
            params["adset_id"] = adset_id
        result = await self._request("GET", url, params=params)
        return result.get("data", [])

    async def get_insights(
        self,
        object_id: str,
        object_type: str = "ad",
        fields: list = None,
        date_preset: str = "today"
    ) -> dict:
        url = f"{self.BASE_URL}/{object_id}/insights"
        params = {
            "access_token": self.access_token,
            "date_preset": date_preset,
            "fields": ",".join(fields) if fields else "impressions,clicks,spend,leads"
        }
        result = await self._request("GET", url, params=params)
        data = result.get("data", [])
        return data[0] if data else {}

    # ====== PHASE 06: Audience methods ======

    async def create_custom_audience(
        self,
        ad_account_id: str,
        name: str,
        customer_file: bytes,
        description: str = ""
    ) -> dict:
        url = f"{self.BASE_URL}/{ad_account_id}/customaudiences"
        data = {
            "name": name,
            "description": description,
            "subtype": "CUSTOM",
            "access_token": self.access_token,
            "content_type": "CUSTOMER_FILE",
            "customer_file_source": "USER_PROVIDED_ONLY"
        }
        # Placeholder – actual upload requires multipart
        return {"id": "pending"}

    async def list_audiences(self, ad_account_id: str) -> list:
        url = f"{self.BASE_URL}/{ad_account_id}/customaudiences"
        params = {"access_token": self.access_token}
        result = await self._request("GET", url, params=params)
        return result.get("data", [])

    # ====== PHASE 09: Lead methods ======

    async def get_lead_forms(self, page_id: str) -> list:
        url = f"{self.BASE_URL}/{page_id}/leadgen_forms"
        params = {"access_token": self.access_token}
        result = await self._request("GET", url, params=params)
        return result.get("data", [])

    async def get_lead_submissions(self, form_id: str) -> list:
        url = f"{self.BASE_URL}/{form_id}/leads"
        params = {"access_token": self.access_token}
        result = await self._request("GET", url, params=params)
        return result.get("data", [])
