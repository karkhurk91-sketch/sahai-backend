from pydantic import BaseModel
from typing import Optional, List, Dict
from uuid import UUID
from datetime import datetime

class FacebookPostCreate(BaseModel):
    page_id: str
    title: Optional[str] = None
    content: str
    hashtags: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    scheduled_for: Optional[str] = None
    publish_now: Optional[bool] = True
    privacy: Optional[str] = 'public'
    is_ad_post: Optional[bool] = False
    feeling: Optional[Dict[str, str]] = None
    location: Optional[str] = None
    cta: Optional[Dict[str, str]] = None
    link_preview: Optional[Dict[str, str]] = None
    ab_test: Optional[Dict] = None
    attached_media: Optional[List[Dict[str, str]]] = None

class FacebookPostResponse(BaseModel):
    id: UUID
    organization_id: UUID
    page_id: str
    meta_post_id: Optional[str]
    title: Optional[str]
    content: str
    hashtags: Optional[str]
    media_url: Optional[str]
    media_type: Optional[str]
    status: str
    published_at: Optional[datetime]
    created_at: datetime
    scheduled_for: Optional[datetime] = None
    is_scheduled: Optional[bool] = False
    class Config:
        from_attributes = True