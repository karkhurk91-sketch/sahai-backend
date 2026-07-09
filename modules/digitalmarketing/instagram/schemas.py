from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime

class InstagramPostCreate(BaseModel):
    caption: Optional[str] = None
    media_url: str          # URL of image/video
    media_type: str = "IMAGE"  # IMAGE, VIDEO, CAROUSEL_ALBUM
    carousel_children: Optional[List[str]] = None  # URLs for carousel
    scheduled_for: Optional[str] = None
    publish_now: Optional[bool] = True

class InstagramPostResponse(BaseModel):
    id: UUID
    organization_id: UUID
    ig_user_id: str
    meta_post_id: Optional[str]
    caption: Optional[str]
    media_url: Optional[str]
    media_type: str
    status: str
    scheduled_for: Optional[datetime]
    published_at: Optional[datetime]
    created_at: datetime
    class Config:
        from_attributes = True