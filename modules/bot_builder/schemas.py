from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime

class BotConfigBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    config: Dict[str, Any]  # JSON config
    version: int = 1

class BotConfigCreate(BotConfigBase):
    pass

class BotConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    version: Optional[int] = None

class BotConfigResponse(BotConfigBase):
    id: UUID
    organization_id: UUID
    is_active: bool
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: Optional[datetime]

    # Pydantic v2 style
    model_config = ConfigDict(from_attributes=True)

class BotConfigActivate(BaseModel):
    organization_id: UUID  # Only super admin can specify; org admin uses own org

class BotConfigListResponse(BaseModel):
    items: List[BotConfigResponse]
    total: int