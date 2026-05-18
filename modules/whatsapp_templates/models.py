from sqlalchemy import Column, String, Integer, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from modules.common.database import Base
import uuid

class WhatsAppTemplate(Base):
    __tablename__ = "whatsapp_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    meta_template_id = Column(String(100), nullable=False, unique=True)
    name = Column(String(512), nullable=False)
    language = Column(String(10), nullable=False)
    category = Column(String(20), nullable=False)  # MARKETING, UTILITY, AUTHENTICATION
    status = Column(String(20), default="pending") # pending, approved, rejected, paused
    components = Column(JSON, nullable=False)      # full components array from Meta
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())