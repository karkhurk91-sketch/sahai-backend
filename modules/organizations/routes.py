from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text
from modules.common.database import get_db
from modules.common.models import Organization, User, OrganizationChannel
from modules.auth.jwt import get_current_user, hash_password, verify_password
from modules.common.masking import MaskingConfig
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
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organization))
    orgs = result.scalars().all()
    return orgs

@router.post("")
async def create_organization(org: OrganizationCreate, db: AsyncSession = Depends(get_db)):
    new_org = Organization(name=org.name, business_type=org.business_type, plan=org.plan)
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
async def get_organization(org_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    return org

# ---------- New Profile & Password endpoints ----------
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
# Add to modules/organizations/routes.py


