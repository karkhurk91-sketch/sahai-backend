# modules/messages/router.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from modules.auth.jwt import get_current_user
from modules.messages.service import send_message

router = APIRouter(prefix="/api/messages", tags=["Messages"])

class SendRequest(BaseModel):
    channel: str
    recipient: str
    message: dict
    fallback_channels: Optional[List[str]] = None

@router.post("/send")
async def send_endpoint(
    req: SendRequest,
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    try:
        msg_id = await send_message(
            org_id=org_id,
            channel=req.channel,
            recipient=req.recipient,
            message=req.message,
            fallback_channels=req.fallback_channels
        )
        return {"status": "queued", "message_id": msg_id, "channel": req.channel}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Message failed: {e}")