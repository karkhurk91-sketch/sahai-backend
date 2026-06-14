from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text
from modules.common.database import get_db
from modules.common.models import Organization, User, OrganizationChannel, OrganizationConversationFlow
from modules.auth.jwt import get_current_user, hash_password, verify_password
from modules.common.masking import MaskingConfig
from modules.ai.flow_service import get_org_conversation_flow, set_org_conversation_flow, delete_org_conversation_flow
from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List

router = APIRouter(prefix="/api/organizations", tags=["Organizations"])

# ---------- Existing CRUD endpoints ----------
class OrganizationCreate(BaseModel):
    name: str
    business_type: str = None
    plan: str = "basic"

@router.get("")
async def list_organizations(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    role = current_user.get("role")
    if role == "super_admin":
        result = await db.execute(select(Organization))
    elif role == "partner":
        partner_id = current_user.get("partner_id")
        if not partner_id:
            raise HTTPException(403, "Partner ID missing")
        result = await db.execute(select(Organization).where(Organization.partner_id == partner_id))
    elif role == "org_admin":
        # Org admin should only see their own organization (if they have access to this endpoint)
        org_id = current_user.get("org_id")
        if not org_id:
            raise HTTPException(403, "Organization ID missing")
        result = await db.execute(select(Organization).where(Organization.id == org_id))
    else:
        raise HTTPException(403, "Not authorized")
    orgs = result.scalars().all()
    return orgs

@router.post("")
async def create_organization(
    org: OrganizationCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    role = current_user.get("role")
    if role not in ["super_admin", "partner"]:
        raise HTTPException(403, "Only super admin or partner can create organizations")
    
    new_org = Organization(name=org.name, business_type=org.business_type, plan=org.plan)
    if role == "partner":
        partner_id = current_user.get("partner_id")
        if not partner_id:
            raise HTTPException(403, "Partner ID missing")
        new_org.partner_id = partner_id
    # super_admin can optionally set partner_id via request body, but we'll ignore for simplicity.
    db.add(new_org)
    await db.commit()
    await db.refresh(new_org)
    return new_org

@router.get("/channels")
async def get_org_channels(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    result = await db.execute(
        select(OrganizationChannel).where(
            OrganizationChannel.organization_id == org_id,
            OrganizationChannel.enabled == True
        )
    )
    return result.scalars().all()

@router.get("/{org_id}")
async def get_organization(
    org_id: UUID,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    role = current_user.get("role")
    # Super admin can see any org; partner can only see their own; org admin only their own.
    query = select(Organization).where(Organization.id == org_id)
    if role == "partner":
        partner_id = current_user.get("partner_id")
        query = query.where(Organization.partner_id == partner_id)
    elif role == "org_admin":
        user_org_id = current_user.get("org_id")
        if str(user_org_id) != str(org_id):
            raise HTTPException(403, "Access denied")
    elif role != "super_admin":
        raise HTTPException(403, "Not authorized")
    
    result = await db.execute(query)
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    return org

# ---------- Conversation flow configuration endpoints ----------
class ConversationFlowStep(BaseModel):
    action: str | dict
    interactive_action: Optional[dict] = None
    field: str
    prompt: Optional[str] = None
    type: Optional[str] = "text"
    required: bool = True
    options: Optional[list] = None
    value_map: Optional[dict] = None

class OrganizationConversationFlowUpdate(BaseModel):
    flow_type: str = "buyer"
    steps: list[ConversationFlowStep]
    is_active: bool = True

@router.get("/{org_id}/conversation-flows/{flow_type}")
async def get_conversation_flow(
    org_id: UUID,
    flow_type: str,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.get("role") not in ["org_admin", "super_admin", "partner"]:
        raise HTTPException(403, "Only organization admins can view conversation flows")
    if str(current_user.get("org_id")) != str(org_id) and current_user.get("role") != "super_admin":
        raise HTTPException(403, "Access denied")

    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    industry = (org.business_type or "realestate").lower()

    steps, seeded = await get_org_conversation_flow(str(org_id), flow_type, industry, return_seeded=True)
    if steps is None:
        raise HTTPException(404, "Conversation flow not found")

    response = {
        "flow_type": flow_type,
        "steps": steps,
        "is_active": True,
    }
    if seeded:
        response["source"] = "seeded"
    return response

@router.put("/{org_id}/conversation-flows/{flow_type}")
async def update_conversation_flow(
    org_id: UUID,
    flow_type: str,
    flow_update: OrganizationConversationFlowUpdate,
    current_user = Depends(get_current_user),
):
    if current_user.get("role") not in ["org_admin", "super_admin", "partner"]:
        raise HTTPException(403, "Only organization admins can manage conversation flows")
    if str(current_user.get("org_id")) != str(org_id) and current_user.get("role") != "super_admin":
        raise HTTPException(403, "Access denied")

    flow = await set_org_conversation_flow(
        str(org_id),
        flow_type,
        [step.dict() for step in flow_update.steps],
        is_active=flow_update.is_active,
    )
    return {
        "flow_type": flow.flow_type,
        "steps": flow.steps,
        "is_active": flow.is_active,
        "created_at": flow.created_at,
        "updated_at": flow.updated_at,
    }

@router.delete("/{org_id}/conversation-flows/{flow_type}")
async def delete_conversation_flow(
    org_id: UUID,
    flow_type: str,
    current_user = Depends(get_current_user),
):
    if current_user.get("role") not in ["org_admin", "super_admin", "partner"]:
        raise HTTPException(403, "Only organization admins can manage conversation flows")
    if str(current_user.get("org_id")) != str(org_id) and current_user.get("role") != "super_admin":
        raise HTTPException(403, "Access denied")

    deleted = await delete_org_conversation_flow(str(org_id), flow_type)
    if not deleted:
        raise HTTPException(404, "Conversation flow not found")
    return {"status": "deleted"}

# ---------- Profile & Password endpoints ----------
class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    business_type: Optional[str] = None
    description: Optional[str] = None
    gst: Optional[str] = None

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

@router.get("/profile")
async def get_profile(current_user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    return org

@router.put("/profile")
async def update_profile(update: ProfileUpdate, current_user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    # Update organization fields
    stmt = update(Organization).where(Organization.id == org_id).values(
        name=update.name,
        business_type=update.business_type,
        settings={"gst": update.gst, "description": update.description}
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "updated"}

@router.post("/change-password")
async def change_password(data: ChangePassword, current_user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user_id = current_user.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password incorrect")
    new_hash = hash_password(data.new_password)
    user.password_hash = new_hash
    await db.commit()
    return {"status": "password updated"}

@router.get("/message-counts")
async def get_message_counts(current_user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    result = await db.execute(
        text("SELECT marketing_message_count, utility_message_count FROM organizations WHERE id = :org_id"),
        {"org_id": org_id}
    )
    row = result.fetchone()
    return {"marketing": row[0] or 0, "utility": row[1] or 0}

# ---------- Data Masking Settings endpoints ----------
class MaskingSettingsUpdate(BaseModel):
    mask_phone: bool = False
    mask_email: bool = False
    phone_partial: bool = True
    email_partial: bool = True


@router.get("/masking-settings")
async def get_masking_settings(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current masking settings for organization"""
    if current_user.get("role") not in ["org_admin", "super_admin", "partner"]:
        raise HTTPException(403, "Only organization admin can view masking settings")
    
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    
    # Get masking settings from organization settings
    settings = org.settings or {}
    masking_config = MaskingConfig.from_dict(settings)
    
    return {
        "mask_phone": masking_config.mask_phone,
        "mask_email": masking_config.mask_email,
        "phone_partial": masking_config.phone_partial,
        "email_partial": masking_config.email_partial,
    }


@router.put("/masking-settings")
async def update_masking_settings(
    settings_update: MaskingSettingsUpdate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update masking settings for organization"""
    if current_user.get("role") not in ["org_admin", "super_admin", "partner"]:
        raise HTTPException(403, "Only organization admin can update masking settings")
    
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    
    # Update masking settings
    current_settings = org.settings or {}
    current_settings.update({
        "mask_phone": settings_update.mask_phone,
        "mask_email": settings_update.mask_email,
        "phone_partial": settings_update.phone_partial,
        "email_partial": settings_update.email_partial,
    })
    
    stmt = update(Organization).where(Organization.id == org_id).values(settings=current_settings)
    await db.execute(stmt)
    await db.commit()
    
    return {
        "status": "updated",
        "mask_phone": settings_update.mask_phone,
        "mask_email": settings_update.mask_email,
        "phone_partial": settings_update.phone_partial,
        "email_partial": settings_update.email_partial,
    }