import httpx
from typing import Optional
from modules.common.logger import get_logger

logger = get_logger(__name__)

class InstagramGraphClient:
    BASE_URL = "https://graph.facebook.com/v20.0"
    DEFAULT_TIMEOUT = 30.0

    def __init__(self, ig_user_id: str, access_token: str):
        self.ig_user_id = ig_user_id
        self.access_token = access_token

    async def _request(self, method: str, url: str, timeout: float = DEFAULT_TIMEOUT, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning("Request timed out, retrying...")
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()

    async def get_user_info(self) -> dict:
        url = f"{self.BASE_URL}/{self.ig_user_id}"
        params = {"fields": "id,username,name,profile_picture_url,follower_count,follows_count,media_count,account_type", "access_token": self.access_token}
        return await self._request("GET", url, params=params)

    async def create_media_container(self, media_url: str, caption: str, media_type: str = "IMAGE", carousel_children: Optional[list] = None) -> dict:
        url = f"{self.BASE_URL}/{self.ig_user_id}/media"
        data = {
            "image_url": media_url,
            "caption": caption,
            "access_token": self.access_token
        }
        if media_type == "VIDEO":
            data["media_type"] = "VIDEO"
        elif media_type == "CAROUSEL_ALBUM":
            data["media_type"] = "CAROUSEL"
            data["children"] = carousel_children
        return await self._request("POST", url, data=data)

    async def publish_media(self, creation_id: str) -> dict:
        url = f"{self.BASE_URL}/{self.ig_user_id}/media_publish"
        data = {"creation_id": creation_id, "access_token": self.access_token}
        return await self._request("POST", url, data=data)

    async def get_post_insights(self, media_id: str, metrics: list = None) -> dict:
        url = f"{self.BASE_URL}/{media_id}/insights"
        if not metrics:
            metrics = ["impressions", "reach", "engagement", "saved"]
        params = {"metric": ",".join(metrics), "access_token": self.access_token}
        return await self._request("GET", url, params=params)