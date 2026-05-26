# modules/orchestration/lead_merge_service.py
import logging
from typing import Dict, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.common.models import Lead
from modules.ai.lead_capture import create_lead  # reuse existing

logger = logging.getLogger(__name__)

class LeadMergeService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def extract_or_update_lead(
        self,
        phone: str,
        organization_id: str,
        extracted_data: Dict,
        conversation_id: str,
        customer_name: str = ""
    ) -> Tuple[str, bool]:
        """Return (lead_id, is_new)."""
        # Find existing lead by phone + org
        result = await self.db.execute(
            select(Lead).where(
                Lead.phone_number == phone,
                Lead.organization_id == organization_id
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Merge: new data overwrites old if not null
            merged = existing.data.copy()
            for k, v in extracted_data.items():
                if v:
                    merged[k] = v
            existing.data = merged
            existing.updated_at = datetime.utcnow()
            await self.db.commit()
            return str(existing.id), False
        else:
            # Create new lead using existing service
            lead_id = await create_lead(
                org_id=organization_id,
                customer_phone=phone,
                extracted_data=extracted_data,
                conversation_id=conversation_id,
                customer_name=customer_name,
                lead_score=extracted_data.get("lead_score", 70),
                interest=extracted_data.get("interest", ""),
                service=extracted_data.get("service")
            )
            return lead_id, True