from pydantic import BaseModel
from typing import Optional
from uuid import UUID

class MessageCreate(BaseModel):
    text: str
    sender_type: str  # 'agent'
    reply_to_id: Optional[UUID] = None

class NoteCreate(BaseModel):
    note: str

class TagCreate(BaseModel):
    name: str
    color: Optional[str] = "#4F46E5"

class AssignAgentRequest(BaseModel):
    agent_id: UUID

class MediaUploadRequest(BaseModel):
    caption: Optional[str] = None

class ConversationModeUpdate(BaseModel):
    mode: str  # 'ai', 'rule', 'human'