from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class SocialPlatform(ABC):
    """Base class for all social media integrations."""
    
    def __init__(self, organization_id: str, account_id: str, access_token: str):
        self.organization_id = organization_id
        self.account_id = account_id
        self.access_token = access_token
    
    @abstractmethod
    async def post_message(self, message: str, media_url: Optional[str] = None) -> Dict[str, Any]:
        """Publish a simple post (text or image)."""
        pass
    
    @abstractmethod
    async def create_ad_campaign(self, campaign_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a full ad campaign (including lead form)."""
        pass
    
    @abstractmethod
    async def get_lead_form_submissions(self, since: Optional[str] = None) -> list:
        """Retrieve lead submissions."""
        pass
