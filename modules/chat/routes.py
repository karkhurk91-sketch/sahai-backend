from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from modules.auth.jwt import get_current_user
from modules.ai.agent import get_agent_for_user_compat
from modules.common.logger import get_logger

router = APIRouter(prefix="/api/chat", tags=["Chat"])
logger = get_logger(__name__)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "User has no organization")
    
    # Ensure message is not empty
    if not req.message or not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")
    
    agent = get_agent_for_user_compat(current_user["sub"], org_id)
    reply = agent.predict(req.message.strip())
    return ChatResponse(reply=reply)