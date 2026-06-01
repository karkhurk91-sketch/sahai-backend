# modules/ai/industries/realestate/__init__.py

from .state import State
from .rules_engine import RulesEngine
from .prompts import Prompts

# Optional: keep for AI mode (if needed)
class RealEstateIndustry:
    def get_system_prompt(self) -> str:
        return "You are a helpful real estate assistant."

    def get_lead_schema(self) -> dict:
        return {
            "name": {"type": "string", "required": True},
            "phone": {"type": "string", "required": True},
            "budget": {"type": "string", "required": True},
            "location": {"type": "string", "required": True},
            "bhk": {"type": "string", "required": True},
            "possession": {"type": "string"},
            "loan_status": {"type": "string"},
            "is_decision_maker": {"type": "boolean"},
            "reason": {"type": "string"},
        }