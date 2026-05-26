from .intent import SalonIntentClassifier as IntentClassifier
from .rules import SalonRulesEngine as RulesEngine
from .state import SalonState as State
from .prompts import SalonPrompts as Prompts

# modules/ai/industries/salon/__init__.py
from typing import List, Dict, Any
from modules.ai.industries.base import BaseIndustry
import logging

logger = logging.getLogger(__name__)

class SalonIndustry(BaseIndustry):
    """Salon industry implementation."""
    
    @property
    def name(self) -> str:
        return "salon"
    
    @property
    def required_fields(self) -> List[str]:
        return ["name", "phone", "service", "preferred_date", "preferred_time"]
    
    async def get_recommendations(self, lead_data: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
        """Recommend salon services."""
        service_type = lead_data.get("service", "haircut")
        return [
            {
                "id": "serv_1",
                "title": f"Premium {service_type.title()}",
                "price": 499,
                "duration": "45 mins",
                "description": "Includes shampoo, style, and blow-dry."
            },
            {
                "id": "serv_2",
                "title": f"{service_type.title()} + Spa",
                "price": 999,
                "duration": "90 mins",
                "description": "Relaxing spa followed by your service."
            }
        ][:limit]
    
    def get_booking_slots(self, lead_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"date": "today", "time": "10:00 AM", "available": True},
            {"date": "today", "time": "2:30 PM", "available": True},
            {"date": "tomorrow", "time": "11:00 AM", "available": False},
        ]
    
    def get_system_prompt(self, stage: str, completed_fields: Dict[str, Any]) -> str:
        return f"""
You are a helpful salon appointment assistant.
Stage: {stage}
Completed: {', '.join(completed_fields.keys())}
Ask only for missing info. Be polite.
"""