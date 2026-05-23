from modules.ai.industries.default import DefaultIndustry
from .prompts import REAL_ESTATE_SYSTEM_PROMPT

class RealEstateIndustry(DefaultIndustry):
    def get_system_prompt(self) -> str:
        return REAL_ESTATE_SYSTEM_PROMPT

    def get_lead_schema(self) -> dict:
        return {
            "name": {"type": "string", "required": True},
            "interest": {"type": "string", "required": True},
            "property_type": {"type": "string", "required": True},
            "bedrooms": {"type": "number"},
            "min_budget": {"type": "number"},
            "max_budget": {"type": "number"},
            "location": {"type": "string", "required": True},
            "possession_timeframe": {"type": "string"},
            "email": {"type": "string"}
        }