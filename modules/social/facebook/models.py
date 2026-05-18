# Pydantic models for Facebook API (ad campaigns, targeting, etc.)
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class FacebookTargeting(BaseModel):
    geo_locations: Dict[str, Any]
    age_min: Optional[int] = 18
    age_max: Optional[int] = 65
    interests: Optional[List[Dict[str, Any]]] = None

class LeadFormQuestion(BaseModel):
    key: str
    label: str
    type: str = "CUSTOM"   # CUSTOM, MULTIPLE_CHOICE, etc.
    options: Optional[List[str]] = None

class FacebookCampaignCreate(BaseModel):
    name: str
    ad_account_id: str
    daily_budget: int          # in cents
    targeting: Dict[str, Any]
    lead_form_questions: List[LeadFormQuestion]
    story_spec: Dict[str, Any]
    start_time: Optional[str] = None
