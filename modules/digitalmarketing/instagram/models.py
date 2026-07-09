import uuid
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, Index, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from modules.common.database import Base

class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    ig_user_id = Column(String(255), nullable=False, unique=True)
    username = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    profile_picture_url = Column(Text, nullable=True)
    follower_count = Column(Integer, default=0)
    follows_count = Column(Integer, default=0)
    media_count = Column(Integer, default=0)
    account_type = Column(String(50))  # BUSINESS, CREATOR
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class InstagramPost(Base):
    __tablename__ = "instagram_posts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    ig_user_id = Column(String(255), nullable=False)
    meta_post_id = Column(String(255), nullable=True)  # Instagram media ID
    caption = Column(Text, nullable=True)
    media_url = Column(Text, nullable=True)  # URL of the media (for preview)
    media_type = Column(String(20), nullable=False)  # IMAGE, VIDEO, CAROUSEL_ALBUM
    status = Column(String(20), default="draft")  # draft, scheduled, published, failed
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    is_scheduled = Column(Boolean, default=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class InstagramInsights(Base):
    __tablename__ = "instagram_insights"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    post_id = Column(UUID(as_uuid=True), ForeignKey("instagram_posts.id", ondelete="CASCADE"))
    metric = Column(String(50), nullable=False)
    value = Column(JSON, nullable=True)
    date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())