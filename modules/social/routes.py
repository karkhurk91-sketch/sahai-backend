# modules/social/routes.py
from fastapi import APIRouter, Request, HTTPException
from modules.common.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/social", tags=["Social"])

@router.post("/webhook/facebook-leads")
async def facebook_lead_webhook(request: Request):
    """Endpoint for Facebook to send lead data."""
    data = await request.json()
    logger.info(f"Received Facebook lead: {data}")
    # Process lead data (store in your database)
    return {"status": "ok"}