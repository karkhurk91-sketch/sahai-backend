import uuid
from sqlalchemy import Column, String, Text, DateTime, Date, Integer, Boolean, Index, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from modules.common.database import Base

class FacebookPost(Base):
    __tablename__ = "facebook_posts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    page_id = Column(String(255), nullable=False)
    meta_post_id = Column(String(255), nullable=True)
    title = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    hashtags = Column(Text, nullable=True)
    media_url = Column(Text, nullable=True)
    media_type = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default='draft')
    error_message = Column(Text, nullable=True)
    boost_campaign_id = Column(String(255), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    is_scheduled = Column(Boolean, default=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted = Column(Boolean, default=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index('ix_facebook_posts_org_status', 'organization_id', 'status'),
        Index('ix_facebook_posts_org_created', 'organization_id', 'created_at'),
        Index('ix_facebook_posts_scheduled', 'scheduled_for'),
    )

class FacebookPage(Base):
    __tablename__ = "facebook_pages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    page_id = Column(String(255), nullable=False)
    page_name = Column(String(255), nullable=False)
    page_access_token = Column(Text, nullable=False)
    page_category = Column(String(100), nullable=True)
    follower_count = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    __table_args__ = (Index('ix_facebook_pages_org_page', 'organization_id', 'page_id', unique=True),)

class FacebookBoost(Base):
    __tablename__ = "facebook_boosts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    post_id = Column(UUID(as_uuid=True), nullable=False)
    meta_campaign_id = Column(String(255), nullable=True)
    meta_adset_id = Column(String(255), nullable=True)
    meta_ad_id = Column(String(255), nullable=True)
    daily_budget_cents = Column(Integer, nullable=False)
    duration_days = Column(Integer, nullable=False)
    targeting = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default='active')
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    goal = Column(String(50), nullable=True)
    cta_type = Column(String(50), nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    advantage_audience = Column(Boolean, default=False)
    advantage_creative = Column(Boolean, default=False)
    special_ad_category = Column(String(50), nullable=True)
    estimated_reach = Column(Integer, nullable=True)
    spent_so_far = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# ====== PHASE 05-07 MODELS ======

class FacebookCampaign(Base):
    __tablename__ = "facebook_campaigns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    meta_campaign_id = Column(String(255), unique=True)
    name = Column(String(255), nullable=False)
    objective = Column(String(50))
    daily_budget_cents = Column(Integer, nullable=True)
    lifetime_budget_cents = Column(Integer, nullable=True)
    status = Column(String(20), default="ACTIVE")
    special_ad_categories = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FacebookAdSet(Base):
    __tablename__ = "facebook_adsets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("facebook_campaigns.id", ondelete="CASCADE"))
    meta_adset_id = Column(String(255), unique=True)
    name = Column(String(255), nullable=False)
    daily_budget_cents = Column(Integer, nullable=True)
    lifetime_budget_cents = Column(Integer, nullable=True)
    targeting = Column(JSON, nullable=False)
    status = Column(String(20), default="ACTIVE")
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FacebookAdCreative(Base):
    __tablename__ = "facebook_ad_creatives"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    meta_creative_id = Column(String(255), unique=True)
    name = Column(String(255), nullable=False)
    page_id = Column(String(255))  # Facebook Page ID
    post_id = Column(String(255), nullable=True)  # Use existing post
    media_url = Column(Text, nullable=True)
    headline = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    cta_type = Column(String(50), nullable=True)
    cta_url = Column(Text, nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FacebookAd(Base):
    __tablename__ = "facebook_ads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("facebook_campaigns.id", ondelete="CASCADE"))
    adset_id = Column(UUID(as_uuid=True), ForeignKey("facebook_adsets.id", ondelete="CASCADE"))
    creative_id = Column(UUID(as_uuid=True), ForeignKey("facebook_ad_creatives.id", ondelete="CASCADE"))
    meta_ad_id = Column(String(255), unique=True)
    name = Column(String(255), nullable=False)
    status = Column(String(20), default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FacebookAudience(Base):
    __tablename__ = "facebook_audiences"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    meta_audience_id = Column(String(255), unique=True)
    name = Column(String(255), nullable=False)
    audience_type = Column(String(30))  # custom, saved, lookalike
    targeting_spec = Column(JSON, nullable=True)
    size = Column(Integer, nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# ====== PHASE 09-10 MODELS ======

class FacebookLead(Base):
    __tablename__ = "facebook_leads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    leadgen_id = Column(String(255), unique=True)
    ad_id = Column(String(255))
    form_id = Column(String(255))
    full_name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    phone_number = Column(Text, nullable=True)
    custom_fields = Column(JSON, default={})
    created_time = Column(DateTime(timezone=True))
    matched_crm_lead_id = Column(UUID(as_uuid=True), nullable=True)
    attributed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class FacebookROISnapshot(Base):
    __tablename__ = "facebook_roi_snapshots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(UUID(as_uuid=True), nullable=True)
    date = Column(Date, nullable=False)
    spend_cents = Column(Integer, default=0)
    revenue_cents = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    leads = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type = Column(String(30))  # campaign, audience, copy, optimisation
    input_data = Column(JSON)
    output_data = Column(JSON)
    is_applied = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())