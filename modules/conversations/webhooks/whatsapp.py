from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from typing import Dict, Any
import hmac
import hashlib
from modules.common.logger import get_logger
from modules.common.database import AsyncSessionLocal
from modules.conversations.services import ConversationService
from modules.message.webhook import process_whatsapp_webhook  # Assuming this exists

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# WhatsApp webhook verification
@router.get("/whatsapp")
async def verify_whatsapp_webhook(
    request: Request,
    hub_mode: str = None,
    hub_challenge: str = None,
    hub_verify_token: str = None
):
    """
    Verifies WhatsApp webhook.
    """
    # Get verify token from config
    expected_token = "your_verify_token"  # Should come from config

    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return int(hub_challenge)
    else:
        raise HTTPException(403, "Verification failed")

@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Handles incoming WhatsApp messages.
    """
    try:
        # Verify signature
        signature = request.headers.get('X-Hub-Signature-256')
        if not signature:
            raise HTTPException(403, "Missing signature")

        body = await request.body()
        expected_signature = hmac.new(
            b'your_app_secret',  # Should come from config
            body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(f'sha256={expected_signature}', signature):
            raise HTTPException(403, "Invalid signature")

        data = await request.json()

        # Process in background
        background_tasks.add_task(process_whatsapp_message, data)

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(500, "Internal error")

async def process_whatsapp_message(data: Dict[str, Any]):
    """
    Processes incoming WhatsApp message in background.
    """
    try:
        # Use existing webhook processor
        await process_whatsapp_webhook(data)
    except Exception as e:
        logger.error(f"Message processing error: {e}")
        # Could add retry logic or dead letter queue here