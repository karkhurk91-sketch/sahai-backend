from .base import SocialPlatform
from .facebook.client import FacebookClient

class SocialFactory:
    @staticmethod
    def get_platform(platform: str, organization_id: str, account_id: str, access_token: str) -> SocialPlatform:
        platform = platform.lower()
        if platform == "facebook":
            return FacebookClient(organization_id, account_id, access_token)
        elif platform == "instagram":
            raise NotImplementedError("Instagram integration coming soon")
        elif platform == "linkedin":
            raise NotImplementedError("LinkedIn integration coming soon")
        else:
            raise ValueError(f"Unsupported platform: {platform}")
