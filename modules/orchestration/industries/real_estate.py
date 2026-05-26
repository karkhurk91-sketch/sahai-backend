from .base import BaseIndustry
from typing import List, Dict
from modules.realestate.repo import search_properties  # your existing repo

class RealEstateIndustry(BaseIndustry):
    @property
    def name(self) -> str:
        return "real_estate"

    @property
    def required_fields(self) -> List[str]:
        return ["name", "phone", "budget", "location", "property_type", "bhk"]

    async def get_recommendations(self, lead_data: Dict, limit: int = 5) -> List[Dict]:
        return await search_properties(
            location=lead_data.get("location"),
            budget_max=lead_data.get("budget"),
            bhk=lead_data.get("bhk"),
            property_type=lead_data.get("property_type", "apartment"),
            limit=limit
        )

    def get_booking_slots(self, lead_data: Dict) -> List[Dict]:
        # Mock or call calendar API
        return [{"date": "2026-05-27", "time": "10:00 AM", "available": True}]

    def get_system_prompt(self, stage: str, completed_fields: Dict) -> str:
        # Return industry‑specific prompt for the LLM
        return f"You are a real estate assistant. Current stage: {stage}. Completed: {completed_fields}"