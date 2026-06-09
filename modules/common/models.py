from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON, Text, Float, ForeignKey, Index, Date, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.types import PickleType   # <-- ADD THIS LINE
from modules.common.database import Base
from sqlalchemy.orm import relationship
import uuid

# ========== Audit Log Model ==========
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)  # e.g., "CREATE", "UPDATE", "DELETE", "LOGIN"
    resource_type = Column(String(50), nullable=False)  # e.g., "user", "customer", "message"
    resource_id = Column(UUID(as_uuid=True))  # ID of the affected resource
    old_values = Column(JSON)  # Previous state for updates
    new_values = Column(JSON)  # New state for creates/updates
    ip_address = Column(String(45))  # IPv4/IPv6 address
    user_agent = Column(Text)  # Browser/client info
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    extra_metadata = Column(JSON)  # Additional context

    # Relationships
    organization = relationship("Organization")
    user = relationship("User")

# ========== Partner Model (moved to top) ==========
class Partner(Base):
    __tablename__ = "partners"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    status = Column(String(20), default="active")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    organizations = relationship("Organization", back_populates="partner", cascade="all, delete-orphan")
    user = relationship("User", foreign_keys=[user_id], back_populates="partner")
    creator = relationship("User", foreign_keys=[created_by], backref="created_partners")
    
class Organization(Base):
    __tablename__ = "organizations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    business_type = Column(String(100))
    whatsapp_phone_number = Column(String(100), unique=True)
    status = Column(String(20), default="pending")
    plan = Column(String(50), default="basic")
    settings = Column(JSON, default={})
    partner_id = Column(UUID, ForeignKey('partners.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    partner = relationship("Partner", back_populates="organizations")
    sla_minutes = Column(Integer, default=60)


class OrganizationConversationFlow(Base):
    __tablename__ = "organization_conversation_flows"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    flow_type = Column(String(50), nullable=False, default="buyer")
    is_active = Column(Boolean, default=True)
    steps = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    __table_args__ = (UniqueConstraint("organization_id", "flow_type"),)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    country_code = Column(String(10), default="+91")
    phone_number = Column(String(20), nullable=False)
    name = Column(String(255))
    email = Column(String(255))
    address = Column(Text)
    pincode = Column(String(20))
    profession = Column(String(100))
    is_active = Column(Boolean, default=True)   
    fb_psid = Column(String(255), nullable=True)
    notes = Column(Text)
    deleted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    opt_in = Column(Boolean, default=False)
    __table_args__ = (
        Index("ix_customers_org_phone", organization_id, phone_number, unique=True),
    )


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(String(50), nullable=False)  # super_admin, partner, org_admin, agent, viewer
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String(255), nullable=True)

    # Relationships
    partner = relationship("Partner", back_populates="user", uselist=False, foreign_keys=[Partner.user_id])

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    customer_phone_number = Column(String(20), nullable=False)
    customer_name = Column(String(255))
    status = Column(String(20), default="open") 
    lead_score = Column(Integer, default=0)
    service = Column(String(100), nullable=True)
    tags = Column(ARRAY(String))
    reply_mode = Column(String(255))
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_message_at = Column(DateTime(timezone=True), server_default=func.now())
    campaign_id = Column(UUID(as_uuid=True), nullable=True)
    rule_state = Column(JSON, default={})
    closed_at = Column(DateTime(timezone=True))
    assigned_agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    unread_count = Column(Integer, default=0)
    last_customer_message_at = Column(DateTime, nullable=True)  # without timezone=True
    custom_fields = Column(JSON, default={})
    # New state machine fields (Phase 1 stabilization)
    conversation_stage = Column(String(50), default="greeting")  # greeting, qualification, recommendation, booking, followup, support, closed
    completed_fields = Column(JSON, default={})  # {field_name: {value, completed_at}}
    booking_status = Column(String(50), nullable=True)  # pending, confirmed, cancelled, completed
    recommendation_shown = Column(Boolean, default=False)  # Track if recommendation was already shown
    last_intent = Column(String(100), nullable=True)  # Last detected intent (not LLM-driven)

class Message(Base):
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"))
    direction = Column(String(10), nullable=False)
    message_type = Column(String(20), default="text")
    content = Column(Text, nullable=False)
    media_url = Column(Text)
    media_whatsapp_id = Column(String(255), nullable=True)
    media_content_type = Column(String(100), nullable=True)
    media_file_name = Column(String(255), nullable=True)
    media_file_size = Column(Integer, nullable=True)
    retry_count = Column(Integer, default=0)
    is_ai_generated = Column(Boolean, default=True)
    human_agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default="sent")
    whatsapp_message_id = Column(String(255), unique=True, nullable=True)
    local_media_path = Column(String(500), nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    # New fields for proper message ordering (source of truth: Meta's timestamp)
    whatsapp_timestamp = Column(Integer, nullable=True)  # Unix seconds from Meta's webhook
    sort_timestamp = Column(DateTime(timezone=True), nullable=False)    
    __table_args__ = (
        Index("ix_messages_sort_timestamp", "sort_timestamp"),
        Index("ix_messages_conversation_sort", "conversation_id", "sort_timestamp"),
    )


class LeadSchema(Base):
    __tablename__ = "lead_schemas"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    schema_fields = Column(JSON, nullable=False, default=[])
    extraction_prompt = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    __table_args__ = (UniqueConstraint('organization_id', 'name'),)

class Lead(Base):
    __tablename__ = "leads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True)
    customer_phone = Column(String(20), nullable=False)
    customer_name = Column(String(255))
    email = Column(String(255))
    interest = Column(String(255))
    data = Column(JSON, default={})
    schema_id = Column(UUID(as_uuid=True), ForeignKey("lead_schemas.id"), nullable=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), default="new")
    notes = Column(Text)
    service = Column(String(100), nullable=True)
    lead_score = Column(Integer, default=0)
    urgency = Column(String(50), default="medium")
    intent = Column(String(100), nullable=True)
    sentiment = Column(String(50), default="neutral")
    conversion_probability = Column(Float, default=0.0)
    follow_up_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    lead_stage = Column(String(50), default="new")
    rule_state = Column(JSON, default={})
    active_nurturing_sequence_id = Column(UUID(as_uuid=True), ForeignKey("lead_nurturing_sequences.id"), nullable=True)
    last_nurturing_step = Column(Integer, default=0)
    last_nurturing_sent_at = Column(DateTime(timezone=True), nullable=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    sentiment_score = Column(Float, default=0.0)
    intent_label = Column(String(50), nullable=True)
    embedding = Column(PickleType, nullable=True)  # or use PGVector if available
    last_scored_at = Column(DateTime, nullable=True)
    assignee = relationship("User", foreign_keys=[assigned_to], backref="assigned_leads")
    schema = relationship("LeadSchema", foreign_keys=[schema_id], backref="leads")
    active_nurturing_sequence = relationship("LeadNurturingSequence", foreign_keys=[active_nurturing_sequence_id])
    nurturing_logs = relationship("LeadNurturingLog", back_populates="lead", cascade="all, delete-orphan")
    conversation = relationship("Conversation", foreign_keys=[conversation_id], backref="lead")
    duplicate_checked = Column(Boolean, default=False)

class AIConfig(Base):
    __tablename__ = "ai_configurations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    system_prompt = Column(Text, default="You are a helpful sales assistant...")
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=500)
    model_name = Column(String(50), default="gemini-1.5-flash")
    enable_lead_capture = Column(Boolean, default=True)
    enable_auto_escalation = Column(Boolean, default=True)
    escalation_keywords = Column(ARRAY(String))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class BroadcastTemplate(Base):
    __tablename__ = "broadcast_templates"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    media_url = Column(Text)
    status = Column(String(20), default="pending")
    meta_template_id = Column(String(100))
    meta_template_name = Column(String(100), nullable=True)
    language_code = Column(String(10), default="en_US")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class BroadcastHistory(Base):
    __tablename__ = "broadcast_history"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    template_id = Column(UUID(as_uuid=True), ForeignKey("broadcast_templates.id"))
    recipient_count = Column(Integer, default=0)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    title = Column(String(255))
    description = Column(Text)
    file_name = Column(String(255), nullable=False)
    file_url = Column(Text, nullable=False)
    file_type = Column(String(50))
    status = Column(String(20), default="processing")
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    customer_phone = Column(String(20), nullable=False)
    customer_name = Column(String(255))
    service = Column(String(100))
    booking_date = Column(Date)
    booking_time = Column(Time)
    status = Column(String(20), default="confirmed")
    reminder_sent = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OrganizationPrompt(Base):
    __tablename__ = "organization_prompts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    prompt_text = Column(Text, nullable=False)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Blog(Base):
    __tablename__ = "blogs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    description = Column(String(500))
    content = Column(Text, nullable=False)
    image_url = Column(String(500))
    published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OrganizationChannel(Base):
    __tablename__ = "organization_channels"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    channel_type = Column(String(50), nullable=False)
    enabled = Column(Boolean, default=False)
    config = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    __table_args__ = (UniqueConstraint('organization_id', 'channel_type'),)

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name = Column(String(255))
    product_name = Column(String(255))
    price = Column(String(50))
    location = Column(String(100))
    description = Column(Text)
    whatsapp_link = Column(Text)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class CampaignCreative(Base):
    __tablename__ = "campaign_creatives"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    type = Column(String(20))
    content = Column(Text)
    is_selected = Column(Boolean, default=False)
    media_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CampaignMeta(Base):
    __tablename__ = "campaign_meta"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    audience_suggestion = Column(Text)
    budget_suggestion = Column(String(50))
    platform_suggestion = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SocialAccount(Base):
    __tablename__ = "social_accounts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    platform = Column(String(50), nullable=False)
    account_id = Column(String(255), nullable=False)
    access_token = Column(Text, nullable=False)
    token_expires_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class SocialPost(Base):
    __tablename__ = "social_posts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"))
    platform = Column(String(50), nullable=False)
    post_id = Column(String(255))
    status = Column(String(50), default="draft")
    content = Column(Text)
    media_url = Column(Text)
    published_at = Column(DateTime(timezone=True))
    platform_response = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SocialAdCampaign(Base):
    __tablename__ = "social_ad_campaigns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    platform = Column(String(50), nullable=False)
    campaign_id = Column(String(255))
    adset_id = Column(String(255))
    ad_id = Column(String(255))
    lead_form_id = Column(String(255))
    name = Column(String(255))
    objective = Column(String(50))
    status = Column(String(50))
    daily_budget = Column(Integer)
    targeting = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Tag(Base):
    __tablename__ = "tags"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    color = Column(String(7), default="#4F46E5")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ConversationTag(Base):
    __tablename__ = "conversation_tags"
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

class ConversationNote(Base):
    __tablename__ = "conversation_notes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"))
    agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    note = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Permission(Base):
    __tablename__ = "permissions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255))

class UserPermission(Base):
    __tablename__ = "user_permissions"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)

class CustomerGroup(Base):
    __tablename__ = "customer_groups"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class CustomerGroupMember(Base):
    __tablename__ = "customer_group_members"
    group_id = Column(UUID(as_uuid=True), ForeignKey("customer_groups.id", ondelete="CASCADE"), primary_key=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

# Add this class to your existing models.py (after ConversationNote or at the end)

class ConversationAssignmentHistory(Base):
    __tablename__ = "conversation_assignment_history"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())


class LeadNurturingSequence(Base):
    __tablename__ = "lead_nurturing_sequences"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LeadNurturingStep(Base):
    __tablename__ = "lead_nurturing_steps"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence_id = Column(UUID(as_uuid=True), ForeignKey("lead_nurturing_sequences.id", ondelete="CASCADE"))
    step_order = Column(Integer, nullable=False)
    delay_days = Column(Integer, nullable=False)
    template_id = Column(UUID(as_uuid=True), ForeignKey("broadcast_templates.id", ondelete="SET NULL"), nullable=True)
    custom_message = Column(Text)
    condition = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LeadNurturingLog(Base):
    __tablename__ = "lead_nurturing_log"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"))
    step_id = Column(UUID(as_uuid=True), ForeignKey("lead_nurturing_steps.id"))
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default="sent")
    error_message = Column(Text)
    lead = relationship("Lead", back_populates="nurturing_logs")

class ConversationMemory(Base):
    __tablename__ = "conversation_memories"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"))
    facts = Column(JSON, default={})          # store extracted lead data, preferences, etc.
    last_summary = Column(Text)               # short summary of last conversation
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Relationships
    conversation = relationship("Conversation", backref="memories")


class BotConfig(Base):
    __tablename__ = "bot_configs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    config = Column(JSON, nullable=False)           # full bot definition (fields, messages, etc.)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, default=False)      # only one active per organisation
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("idx_bot_configs_org_active", "organization_id", "is_active"),
    )