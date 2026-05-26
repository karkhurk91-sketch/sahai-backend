"""
Lead Merge Service - Deterministic lead extraction and merging.

Features:
- Create or find existing leads
- Merge extracted data intelligently
- Prevent duplicates
- Update lead scores
- Audit trail of merges
"""

from typing import Dict, Tuple, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)


class LeadMergeService:
    """
    Deterministic lead extraction and merging.
    
    Prevents duplicate leads and merge conflicts.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def extract_or_update_lead(
        self,
        phone: str,
        organization_id: str,
        extracted_data: Dict,
        conversation_id: str,
        source: str = "ai_extraction"
    ) -> Tuple[str, bool]:
        """
        Extract lead data and create or merge with existing lead.
        
        Args:
            phone: User's phone number
            organization_id: Organization UUID
            extracted_data: Data extracted from conversation
            conversation_id: Conversation UUID
            source: Source of extraction (ai_extraction, user_input, etc.)
        
        Returns:
            (lead_id, is_new_lead)
        """
        
        from modules.common.models import Lead
        
        # Find existing lead
        result = await self.db.execute(
            select(Lead).where(
                (Lead.phone_number == phone) &
                (Lead.organization_id == organization_id)
            )
        )
        existing_lead = result.scalar_one_or_none()
        
        if existing_lead:
            # Merge data
            lead_id = await self._merge_lead_data(
                existing_lead,
                extracted_data,
                conversation_id,
                source
            )
            return lead_id, False
        else:
            # Create new lead
            lead_id = await self._create_lead(
                phone,
                organization_id,
                extracted_data,
                conversation_id,
                source
            )
            return lead_id, True
    
    async def _create_lead(
        self,
        phone: str,
        organization_id: str,
        extracted_data: Dict,
        conversation_id: str,
        source: str
    ) -> str:
        """Create new lead"""
        
        from modules.common.models import Lead
        
        lead = Lead(
            phone_number=phone,
            organization_id=organization_id,
            data=extracted_data,
            lead_score=self._calculate_lead_score(extracted_data),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            source=source
        )
        
        self.db.add(lead)
        await self.db.flush()
        
        logger.info(
            f"Created new lead: {lead.id} from conversation: {conversation_id}, "
            f"phone: {phone}, source: {source}"
        )
        
        return str(lead.id)
    
    async def _merge_lead_data(
        self,
        existing_lead,
        new_data: Dict,
        conversation_id: str,
        source: str
    ) -> str:
        """
        Merge new data into existing lead.
        
        Strategy:
        - New data overwrites old data if more complete
        - Lists are appended to (if different)
        - Null values are skipped
        - Audit trail maintained
        """
        
        merged_data = existing_lead.data.copy() if existing_lead.data else {}
        changes = {}
        
        for key, new_value in new_data.items():
            if new_value is None or new_value == "":
                continue  # Skip empty values
            
            old_value = merged_data.get(key)
            
            # If field doesn't exist, add it
            if old_value is None:
                merged_data[key] = new_value
                changes[key] = {"old": None, "new": new_value}
            
            # If field is list, append if different
            elif isinstance(merged_data.get(key), list):
                if new_value not in merged_data[key]:
                    merged_data[key].append(new_value)
                    changes[key] = {"action": "appended", "value": new_value}
            
            # If new value is more complete, replace old
            elif self._is_more_complete(new_value, old_value):
                merged_data[key] = new_value
                changes[key] = {"old": old_value, "new": new_value}
        
        existing_lead.data = merged_data
        existing_lead.updated_at = datetime.utcnow()
        existing_lead.lead_score = self._calculate_lead_score(merged_data)
        
        # Log merge in audit trail
        if not hasattr(existing_lead, 'merge_history'):
            existing_lead.merge_history = []
        
        existing_lead.merge_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "conversation_id": conversation_id,
            "source": source,
            "changes": changes
        })
        
        await self.db.commit()
        
        logger.info(
            f"Merged lead data into existing lead: {existing_lead.id}, "
            f"changes: {changes}"
        )
        
        return str(existing_lead.id)
    
    def _is_more_complete(self, new_value, old_value) -> bool:
        """
        Check if new value is more complete than old value.
        
        Heuristics:
        - Longer strings are more complete
        - Non-null > null
        - Non-empty list > empty list
        """
        
        # Null > non-null
        if old_value is None:
            return True
        if new_value is None:
            return False
        
        # String length
        if isinstance(new_value, str) and isinstance(old_value, str):
            return len(new_value) > len(old_value)
        
        # List size
        if isinstance(new_value, list) and isinstance(old_value, list):
            return len(new_value) > len(old_value)
        
        # Same type, new value wins
        if type(new_value) == type(old_value):
            return True
        
        # Prioritize certain types
        type_priority = {str: 3, int: 2, float: 2, list: 1, dict: 1, bool: 0}
        return type_priority.get(type(new_value), 0) > type_priority.get(type(old_value), 0)
    
    def _calculate_lead_score(self, lead_data: Dict) -> float:
        """
        Calculate lead score based on data completeness.
        
        Score = (filled_fields / expected_fields) * 100
        """
        
        # Expected fields vary by industry, but use default count
        expected_fields = 10
        
        # Count non-empty fields
        filled_fields = sum(
            1 for v in lead_data.values()
            if v is not None and v != "" and v != []
        )
        
        score = (filled_fields / expected_fields) * 100
        return min(score, 100)  # Cap at 100
    
    async def find_duplicate_leads(
        self,
        lead_id: str,
        similarity_threshold: float = 0.85
    ) -> list:
        """
        Find potential duplicate leads based on similarity.
        
        Args:
            lead_id: Lead UUID to check
            similarity_threshold: Similarity threshold (0-1)
        
        Returns:
            List of potentially duplicate lead IDs
        """
        
        from modules.common.models import Lead
        
        # Load lead
        result = await self.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )
        lead = result.scalar_one_or_none()
        
        if not lead:
            return []
        
        # Simple duplicate detection based on phone + organization
        # More sophisticated: use embeddings if available
        
        result = await self.db.execute(
            select(Lead).where(
                (Lead.phone_number == lead.phone_number) &
                (Lead.organization_id == lead.organization_id) &
                (Lead.id != lead_id)
            )
        )
        
        duplicates = result.scalars().all()
        
        return [str(dup.id) for dup in duplicates]
    
    async def merge_duplicate_leads(
        self,
        primary_lead_id: str,
        secondary_lead_id: str
    ) -> bool:
        """
        Merge two leads (secondary into primary).
        
        Args:
            primary_lead_id: Lead to keep
            secondary_lead_id: Lead to merge into primary
        
        Returns:
            Success status
        """
        
        from modules.common.models import Lead
        
        try:
            # Load leads
            result = await self.db.execute(
                select(Lead).where(Lead.id == primary_lead_id)
            )
            primary = result.scalar_one_or_none()
            
            result = await self.db.execute(
                select(Lead).where(Lead.id == secondary_lead_id)
            )
            secondary = result.scalar_one_or_none()
            
            if not primary or not secondary:
                logger.error(f"Lead not found during merge")
                return False
            
            # Merge secondary into primary
            for key, value in (secondary.data or {}).items():
                if key not in (primary.data or {}):
                    primary.data[key] = value
            
            # Update score
            primary.lead_score = self._calculate_lead_score(primary.data)
            primary.updated_at = datetime.utcnow()
            
            # Mark secondary as merged
            secondary.merged_into_lead_id = primary_lead_id
            secondary.merged_at = datetime.utcnow()
            
            await self.db.commit()
            
            logger.info(f"Merged lead {secondary_lead_id} into {primary_lead_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error merging leads: {e}")
            return False
