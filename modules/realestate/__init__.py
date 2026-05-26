# modules/ai/industries/realestate/__init__.py
from typing import List, Dict, Any
from modules.ai.industries.base import BaseIndustry
from modules.realestate.repo import search_properties  # your stub/real repo
import logging

logger = logging.getLogger(__name__)

class RealEstateIndustry(BaseIndustry):
    """Real estate industry implementation."""
    
    @property
    def name(self) -> str:
        return "real_estate"
    
    @property
    def required_fields(self) -> List[str]:
        return ["name", "phone", "budget", "location", "property_type", "bhk"]
    
    async def get_recommendations(self, lead_data: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fetch property recommendations based on lead preferences.
        Calls search_properties from the repo.
        """
        try:
            budget = lead_data.get("budget")
            # Convert budget string like "50 lakh" to integer (approximate)
            budget_max = self._parse_budget(budget) if budget else None
            
            properties = await search_properties(
                location=lead_data.get("location"),
                budget_max=budget_max,
                bhk=lead_data.get("bhk"),
                property_type=lead_data.get("property_type", "apartment"),
                limit=limit
            )
            logger.info(f"Found {len(properties)} properties for lead data: {lead_data}")
            return properties
        except Exception as e:
            logger.error(f"Error getting real estate recommendations: {e}", exc_info=True)
            return []
    
    def get_booking_slots(self, lead_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return available slots for site visits (mock or real API)."""
        # You can replace this with a calendar API or database query
        return [
            {"date": "tomorrow", "time": "10:00 AM", "available": True},
            {"date": "tomorrow", "time": "2:00 PM", "available": True},
            {"date": "day after tomorrow", "time": "11:00 AM", "available": False},
        ]
    
    def get_system_prompt(self, stage: str, completed_fields: Dict[str, Any]) -> str:
        """Return industry‑specific prompt for LLM."""
        return f"""
You are a helpful real estate assistant for WhatsApp.
Current stage: {stage}
Already collected: {', '.join(completed_fields.keys()) if completed_fields else 'none'}
Never ask for already collected fields.
Be concise and friendly.
"""
    
    def _parse_budget(self, budget_str: str) -> int:
        """Convert budget like '50 lakh' to integer (in rupees)."""
        if not budget_str:
            return None
        budget_str = budget_str.lower().replace(",", "")
        import re
        match = re.search(r"(\d+(?:\.\d+)?)\s*(lac|crore|k|thousand|million|billion)?", budget_str)
        if not match:
            return None
        amount = float(match.group(1))
        unit = match.group(2) or "lakh"
        if unit == "lac" or unit == "lakh":
            return int(amount * 100000)
        if unit == "crore":
            return int(amount * 10000000)
        if unit == "k" or unit == "thousand":
            return int(amount * 1000)
        if unit == "million":
            return int(amount * 1000000)
        if unit == "billion":
            return int(amount * 1000000000)
        return int(amount)