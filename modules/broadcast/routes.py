import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from uuid import UUID
from typing import List, Optional

from modules.common.database import get_db
from modules.common.models import BroadcastTemplate, BroadcastHistory, Customer, Organization, OrganizationChannel
from modules.auth.jwt import get_current_user
from modules.message.sender import send_whatsapp_template   # expects org_id
from modules.messages.service import send_message
from modules.common.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/broadcast", tags=["Broadcast"])

# ---------- Pydantic models ----------
class TemplateCreate(BaseModel):
    name: str
    content: str
    media_url: Optional[str] = None
    meta_template_name: Optional[str] = None
    language_code: Optional[str] = "en_US"
    category: str = "MARKETING"

class BroadcastSend(BaseModel):
    template_id: UUID
    recipient_ids: List[UUID]

class SendMetaBroadcast(BaseModel):
    template_name: str
    language_code: str = "en_US"
    recipient_phone_numbers: List[str]

class MultiChannelBroadcast(BaseModel):
    channel: str
    message: dict
    recipient_ids: List[UUID]

class SendMetaTemplate(BaseModel):
    template_name: str
    language_code: str = "en_US"
    recipient_ids: List[UUID]

# ---------- Helper: get WhatsApp channel config for an org ----------
async def get_whatsapp_config(org_id: UUID, db: AsyncSession):
    """Fetch the active WhatsApp channel configuration for an organization."""
    result = await db.execute(
        select(OrganizationChannel).where(
            OrganizationChannel.organization_id == org_id,
            OrganizationChannel.channel_type == "whatsapp",
            OrganizationChannel.enabled == True
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(404, f"No active WhatsApp channel found for organization {org_id}")
    # config is stored as JSON (dict) – ensure it has the required keys
    config = channel.config
    if not config.get("access_token") or not config.get("phone_number_id"):
        raise HTTPException(500, "WhatsApp config missing access_token or phone_number_id")
    return config

# ---------- Local templates endpoints (unchanged) ----------
@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    result = await db.execute(
        select(BroadcastTemplate)
        .where(BroadcastTemplate.organization_id == current_user["org_id"])
        .order_by(BroadcastTemplate.created_at.desc())
    )
    return result.scalars().all()

@router.post("/templates")
async def create_template(data: TemplateCreate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    template = BroadcastTemplate(
        organization_id=current_user["org_id"],
        name=data.name,
        content=data.content,
        media_url=data.media_url,
        status="pending",
        meta_template_name=data.meta_template_name,
        language_code=data.language_code,
        category=data.category
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template

@router.post("/templates/{template_id}/submit")
async def submit_template(template_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    stmt = update(BroadcastTemplate).where(
        BroadcastTemplate.id == template_id,
        BroadcastTemplate.organization_id == current_user["org_id"]
    ).values(status="approved")
    await db.execute(stmt)
    await db.commit()
    return {"status": "approved"}

# ---------- Send broadcast using approved Meta template (phone numbers) ----------
@router.post("/send-meta")
async def send_meta_broadcast(
    data: SendMetaBroadcast,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user)
):

    if current_user.get("role") not in ["org_admin", "agent"]:
        raise HTTPException(403, "Permission denied")

    if not data.recipient_phone_numbers:
        raise HTTPException(400, "No recipients provided")
    if not data.template_name:
        raise HTTPException(400, "Template name is required")

    background_tasks.add_task(
        send_bulk_template_messages,
        recipients=data.recipient_phone_numbers,
        template_name=data.template_name,
        language_code=data.language_code,
        org_id=current_user["org_id"],
        category="MARKETING"   # or make it dynamic
    )
    return {
        "status": "queued",
        "recipient_count": len(data.recipient_phone_numbers),
        "template": data.template_name
    }

async def send_bulk_template_messages(recipients: list, template_name: str, language_code: str, org_id: str, category: str):
    for phone in recipients:
        success = await send_whatsapp_template(
            to_number=phone,
            template_name=template_name,
            language_code=language_code,
            category=category,
            org_id=org_id
        )
        await asyncio.sleep(0.5)

# ---------- Fetch approved templates from Meta (using org's credentials) ----------
@router.get("/meta-templates")
async def fetch_meta_templates(
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    config = await get_whatsapp_config(org_id, db)
    access_token = config["access_token"]
    waba_id = config.get("business_account_id")   # stored as business_account_id

    # If business_account_id not stored, try to fetch it from Meta
    if not waba_id:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.facebook.com/v21.0/me/whatsapp_business_accounts",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("data"):
                waba_id = data["data"][0]["id"]
                # Optionally store it back to the channel config
                config["business_account_id"] = waba_id
                await db.execute(
                    update(OrganizationChannel)
                    .where(OrganizationChannel.organization_id == org_id, OrganizationChannel.channel_type == "whatsapp")
                    .values(config=config)
                )
                await db.commit()
            else:
                raise HTTPException(400, "No WhatsApp Business Account found for this organization")

    url = f"https://graph.facebook.com/v21.0/{waba_id}/message_templates"
    params = {}
    if category:
        params["category"] = category.upper()
    if status:
        params["status"] = status.upper()

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

    templates = []
    for t in data.get("data", []):
        templates.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "status": t.get("status"),
            "category": t.get("category"),
            "language": t.get("language"),
            "components": t.get("components", []),
        })
    return templates

# ---------- Multi‑channel broadcast (any enabled channel) ----------
@router.post("/send-multichannel")
async def send_multichannel_broadcast(
    data: MultiChannelBroadcast,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    # Verify channel is enabled for this organization
    chk = await db.execute(
        select(OrganizationChannel).where(
            OrganizationChannel.organization_id == org_id,
            OrganizationChannel.channel_type == data.channel,
            OrganizationChannel.enabled == True
        )
    )
    if not chk.scalar_one_or_none():
        raise HTTPException(400, f"Channel {data.channel} not enabled for this organization")

    # Fetch customers
    customers_result = await db.execute(
        select(Customer).where(
            Customer.id.in_(data.recipient_ids),
            Customer.organization_id == org_id,
            Customer.deleted_at.is_(None)
        )
    )
    recipients = customers_result.scalars().all()
    if not recipients:
        raise HTTPException(400, "No valid recipients")

    async def send():
        for cust in recipients:
            if data.channel == "whatsapp":
                to = cust.phone_number
            elif data.channel == "facebook":
                to = cust.fb_psid
            elif data.channel == "instagram":
                to = cust.instagram_id
            elif data.channel == "telegram":
                to = cust.telegram_chat_id
            elif data.channel == "email":
                to = cust.email
            else:
                continue
            if not to:
                continue
            try:
                await send_message(
                    org_id=str(org_id),
                    channel=data.channel,
                    recipient=to,
                    message=data.message
                )
                logger.info(f"Broadcast sent via {data.channel} to {cust.id}")
            except Exception as e:
                logger.error(f"Failed to send via {data.channel} to {cust.id}: {e}")
            await asyncio.sleep(0.5)

    background_tasks.add_task(send)
    return {"status": "queued", "channel": data.channel, "recipient_count": len(recipients)}

# ---------- Send WhatsApp template broadcast using customer IDs (uses org credentials) ----------
@router.post("/send-meta-template")
async def send_meta_template_broadcast(
    data: SendMetaTemplate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    # Fetch customers
    customers_result = await db.execute(
        select(Customer).where(
            Customer.id.in_(data.recipient_ids),
            Customer.organization_id == org_id,
            Customer.deleted_at.is_(None)
        )
    )
    recipients = customers_result.scalars().all()
    if not recipients:
        raise HTTPException(400, "No valid recipients")

    async def send():
        for cust in recipients:
            try:
                await send_whatsapp_template(
                    to_number=cust.phone_number,
                    template_name=data.template_name,
                    language_code=data.language_code,
                    org_id=str(org_id),
                    category="MARKETING"
                )
                logger.info(f"Template sent to {cust.phone_number}")
            except Exception as e:
                logger.error(f"Failed to send to {cust.phone_number}: {e}")
            await asyncio.sleep(0.5)

    background_tasks.add_task(send)
    return {"status": "queued", "recipient_count": len(recipients)}