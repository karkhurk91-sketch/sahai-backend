from pydantic import BaseModel
from typing import List, Dict, Optional
from uuid import UUID
from datetime import datetime

class TemplateComponent(BaseModel):
    type: str
    format: Optional[str] = None
    text: Optional[str] = None
    buttons: Optional[List[Dict]] = None
    example: Optional[Dict] = None

class TemplateCreate(BaseModel):
    name: str
    category: str
    language: str
    components: List[TemplateComponent]
    local_name: Optional[str] = None

class TemplateResponse(BaseModel):
    id: UUID
    organization_id: UUID
    meta_template_id: str
    name: str
    language: str
    category: str
    status: str
    components: Dict
    created_at: datetime
    updated_at: datetime

class SendTemplateRequest(BaseModel):
    template_name: str
    language_code: str
    recipient_ids: List[UUID]
    parameters: Dict[str, str]  # e.g., {"1": "John", "2": "ORD-123"}
    
class SendTemplateDynamicRequest(BaseModel):
    template_id: UUID
    recipient_ids: List[UUID]
    values: Dict[str, str]   # e.g., {"1": "John", "2": "ORD-123"}