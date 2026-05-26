from .intent import RestaurantIntentClassifier as IntentClassifier
from .rules import RestaurantRulesEngine as RulesEngine
from .state import RestaurantState as State
from .prompts import RestaurantPrompts as Prompts

# modules/ai/industries/restaurant/__init__.py
from typing import List, Dict, Any
from modules.ai.industries.base import BaseIndustry
import logging

logger = logging.getLogger(__name__)

class RestaurantIndustry(BaseIndustry):
    """Restaurant industry implementation."""
    
    @property
    def name(self) -> str:
        return "restaurant"
    
    @property
    def required_fields(self) -> List[str]:
        return ["name", "phone", "party_size", "date", "time", "cuisine"]
    
    async def get_recommendations(self, lead_data: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
        """Recommend menu items based on cuisine and party size."""
        # Stub – replace with your actual menu search logic
        cuisine = lead_data.get("cuisine", "any")
        return [
            {
                "id": "dish_1",
                "title": f"Special {cuisine.title()} Platter",
                "price": 599,
                "description": "A delicious assortment of chef's specials.",
                "cuisine": cuisine
            },
            {
                "id": "dish_2",
                "title": "Grilled Chicken",
                "price": 349,
                "description": "Juicy grilled chicken with herbs.",
                "cuisine": "continental"
            }
        ][:limit]
    
    def get_booking_slots(self, lead_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return available table slots."""
        return [
            {"date": "today", "time": "7:00 PM", "available": True},
            {"date": "today", "time": "8:30 PM", "available": False},
            {"date": "tomorrow", "time": "1:00 PM", "available": True},
        ]
    
    def get_system_prompt(self, stage: str, completed_fields: Dict[str, Any]) -> str:
        return f"""
You are a friendly restaurant booking assistant.
Stage: {stage}
Known info: {', '.join(completed_fields.keys())}
Ask only for missing fields. Keep answers short.
"""