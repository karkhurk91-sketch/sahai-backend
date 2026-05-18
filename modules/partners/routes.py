from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from uuid import UUID
from pydantic import BaseModel, EmailStr
from typing import List, Optional

from modules.common.database import get_db
from modules.common.models import Partner, Organization, User
from modules.auth.jwt import get_current_user, get_password_hash
from modules.common.logger import get_logger
from datetime import datetime


logger = get_logger(__name__)
router = APIRouter(prefix="/api/partners", tags=["Partners"])

class PartnerCreate(BaseModel):
    name: str
    email: str
    password: str 

class PartnerUpdate(BaseModel):
    name: str

class PartnerResponse(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    class Config:
        from_attributes = True

class OrganizationCreate(BaseModel):
    name: str
    business_type: Optional[str] = None
    whatsapp_phone_number: Optional[str] = None
    plan: Optional[str] = "basic"
    admin_email: EmailStr
    admin_password: str
    enable_lead_capture: bool = True   # add this field

# Helper to check super admin
async def require_super_admin(current_user):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")

async def require_partner(current_user):
    if current_user.get("role") != "partner":
        raise HTTPException(403, "Partner access required")

@router.get("/", response_model=List[PartnerResponse])
async def list_partners(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    await require_super_admin(current_user)
    result = await db.execute(select(Partner).order_by(Partner.created_at.desc()))
    partners = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None
        }
        for p in partners
    ]

@router.post("/", response_model=PartnerResponse)
async def create_partner(
    data: PartnerCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    
    # Check if email is already used
    existing_user = await db.execute(select(User).where(User.email == data.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    
    # Create user
    hashed_pw = get_password_hash(data.password)
    user = User(
        email=data.email,
        password_hash=hashed_pw,
        full_name=data.name,
        role="partner",
        is_active=True,
        email_verified=False
    )
    db.add(user)
    await db.flush()  # to get user.id
    
    # Create partner linked to user
    partner = Partner(
        name=data.name,
        created_by=UUID(current_user["user_id"]),
        user_id=user.id
    )
    db.add(partner)
    await db.commit()
    await db.refresh(partner)
    
    # Also create an initial welcome message? optional
    return partner


@router.post("/{partner_id}/organizations", response_model=dict)
async def create_organization_for_partner(
    partner_id: UUID,
    data: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Ensure the current user is a partner and owns this partner_id
    if current_user.get("role") != "partner":
        raise HTTPException(403, "Only partners can create organizations")
    if current_user.get("partner_id") != str(partner_id):
        raise HTTPException(403, "You can only create organizations under your own partner account")
    
    # Check if admin email already used
    existing_user = await db.execute(select(User).where(User.email == data.admin_email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(400, "Admin email already registered")
    
    # Create organization
    org = Organization(
        name=data.name,
        business_type=data.business_type,
        whatsapp_phone_number=data.whatsapp_phone_number,
        plan=data.plan,
        partner_id=partner_id,
        status="active"   # or "pending" – you can decide
    )
    db.add(org)
    await db.flush()
    
    # Create admin user for this organization
    hashed_pw = get_password_hash(data.admin_password)
    admin_user = User(
        email=data.admin_email,
        password_hash=hashed_pw,
        full_name=data.name,
        role="org_admin",
        organization_id=org.id,
        is_active=True,
        email_verified=True   # or False if you want email verification later
    )
    db.add(admin_user)
    await db.commit()
    await db.refresh(org)
    
    # Optionally, create AI config entry with default enable_lead_capture = True
    # (if you have an AI config model)
    # ai_config = AIConfig(organization_id=org.id, enable_lead_capture=True)
    # db.add(ai_config)
    # await db.commit()
    
    return {"id": str(org.id), "name": org.name}
@router.get("/{partner_id}/organizations")
async def list_organizations_for_partner(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Super admin or partner himself can see
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(partner_id):
        raise HTTPException(403, "Not authorized")
    result = await db.execute(select(Organization).where(Organization.partner_id == partner_id))
    return result.scalars().all()

@router.get("/my")
async def get_my_partner_info(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    partner_id = current_user.get("partner_id")
    if not partner_id:
        raise HTTPException(400, "User is not associated with a partner")
    result = await db.execute(select(Partner).where(Partner.id == partner_id))
    partner = result.scalar_one_or_none()
    if not partner:
        raise HTTPException(404, "Partner not found")
    return partner

from pydantic import BaseModel
from uuid import UUID
from fastapi import HTTPException

class PartnerUpdate(BaseModel):
    name: str

@router.put("/{partner_id}")
async def update_partner(
    partner_id: UUID,
    data: PartnerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    
    result = await db.execute(select(Partner).where(Partner.id == partner_id))
    partner = result.scalar_one_or_none()
    if not partner:
        raise HTTPException(404, "Partner not found")
    
    partner.name = data.name
    await db.commit()
    await db.refresh(partner)
    return partner

@router.delete("/{partner_id}")
async def delete_partner(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    
    result = await db.execute(select(Partner).where(Partner.id == partner_id))
    partner = result.scalar_one_or_none()
    if not partner:
        raise HTTPException(404, "Partner not found")
    
    await db.delete(partner)
    await db.commit()
    return {"status": "deleted"}

class UserEmailUpdate(BaseModel):
    email_verified: bool

# ---------- Additional partner endpoints for full organization management ----------
class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    business_type: Optional[str] = None
    whatsapp_phone_number: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None

class AIConfigUpdate(BaseModel):
    enable_lead_capture: Optional[bool] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

@router.get("/organizations/{org_id}")
async def get_organization_details(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Check ownership: must be super_admin or partner who owns this org
    org = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    
    # Get admin email
    admin_email = await db.execute(select(User.email).where(User.organization_id == org_id, User.role == "org_admin"))
    admin_email = admin_email.scalar_one_or_none()
    
    # Get counts
    from modules.common.models import Customer, Conversation, Lead
    customers = await db.execute(select(func.count(Customer.id)).where(Customer.organization_id == org_id, Customer.deleted_at.is_(None)))
    conversations = await db.execute(select(func.count(Conversation.id)).where(Conversation.organization_id == org_id))
    leads = await db.execute(select(func.count(Lead.id)).where(Lead.organization_id == org_id))
    
    return {
        "id": org.id,
        "name": org.name,
        "business_type": org.business_type,
        "whatsapp_phone_number": org.whatsapp_phone_number,
        "status": org.status,
        "plan": org.plan,
        "created_at": org.created_at.isoformat(),
        "admin_email": admin_email,
        "stats": {
            "customers": customers.scalar() or 0,
            "conversations": conversations.scalar() or 0,
            "leads": leads.scalar() or 0
        }
    }

@router.put("/organizations/{org_id}")
async def update_organization(
    org_id: UUID,
    data: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(org, key, value)
    await db.commit()
    return {"status": "updated"}

@router.patch("/organizations/{org_id}/status")
async def update_org_status(
    org_id: UUID,
    data: OrganizationUpdate,  # has status field
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    if data.status:
        org.status = data.status
        await db.commit()
    return {"status": "updated"}

@router.delete("/organizations/{org_id}")
async def delete_organization(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    # Delete associated users first
    await db.execute(delete(User).where(User.organization_id == org_id))
    await db.execute(delete(Organization).where(Organization.id == org_id))
    await db.commit()
    return {"status": "deleted"}

@router.get("/organizations/{org_id}/users")
async def get_org_users(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    users = await db.execute(select(User).where(User.organization_id == org_id))
    return [
        {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "email_verified": u.email_verified}
        for u in users.scalars().all()
    ]

@router.patch("/users/{user_id}/verify-email")
async def verify_user_email(
    user_id: UUID,
    data: UserEmailUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user = await db.execute(select(User).where(User.id == user_id))
    user = user.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    # Check that the user belongs to an organization that the partner owns
    org = await db.execute(select(Organization).where(Organization.id == user.organization_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    user.email_verified = data.email_verified
    await db.commit()
    return {"status": "updated"}

@router.get("/organizations/{org_id}/ai-config")
async def get_org_ai_config(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    from modules.common.models import AIConfig
    config = await db.execute(select(AIConfig).where(AIConfig.organization_id == org_id))
    config = config.scalar_one_or_none()
    if not config:
        return {
            "enable_lead_capture": True,
            "system_prompt": "You are a helpful AI assistant.",
            "temperature": 0.7,
            "max_tokens": 500
        }
    return config

@router.put("/organizations/{org_id}/ai-config")
async def update_org_ai_config(
    org_id: UUID,
    data: AIConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    if current_user.get("role") != "super_admin" and current_user.get("partner_id") != str(org.partner_id):
        raise HTTPException(403, "Not authorized")
    from modules.common.models import AIConfig
    config = await db.execute(select(AIConfig).where(AIConfig.organization_id == org_id))
    config = config.scalar_one_or_none()
    if not config:
        config = AIConfig(organization_id=org_id)
        db.add(config)
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    await db.commit()
    return config
