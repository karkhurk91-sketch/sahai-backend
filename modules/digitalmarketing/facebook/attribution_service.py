"""
Lead Attribution – match Facebook leads to CRM leads.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.logger import get_logger

logger = get_logger(__name__)

class AttributionService:
    async def match_facebook_lead(self, db: AsyncSession, fb_lead: dict):
        """Match Facebook lead to existing CRM lead by phone/email."""
        # Search CRM leads table
        return {"matched": False, "crm_lead_id": None}

    async def store_lead(self, db: AsyncSession, org_id: str, fb_lead: dict):
        """Store Facebook lead data for later attribution."""
        pass