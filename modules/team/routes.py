from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from uuid import UUID
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import secrets
import string

from modules.common.database import get_db
from modules.common.models import User, Organization
from modules.auth.jwt import get_current_user, get_password_hash
from modules.common.logger import get_logger
from modules.common.email import send_email
from modules.common.config import FRONTEND_URL

logger = get_logger(__name__)
router = APIRouter(prefix="/api/team", tags=["Team Management"])

def generate_temp_password(length=10):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

class TeamMemberCreate(BaseModel):
    email: EmailStr
    full_name: str
    role: str   # 'org_admin', 'agent', 'viewer'

class TeamMemberResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool

async def require_org_admin(current_user, db: AsyncSession, org_id: UUID):
    if current_user.get("role") != "org_admin":
        raise HTTPException(403, "Only organization admin can manage team")
    user_id = current_user.get("user_id")
    result = await db.execute(select(User).where(User.id == user_id, User.organization_id == org_id))
    if not result.scalar_one_or_none():
        raise HTTPException(403, "Not a member of this organization")
    return True

@router.get("/{org_id}", response_model=List[TeamMemberResponse])
async def list_team_members(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    await require_org_admin(current_user, db, org_id)
    result = await db.execute(select(User).where(User.organization_id == org_id))
    users = result.scalars().all()
    return users

@router.post("/{org_id}/invite")
async def invite_team_member(
    org_id: UUID,
    data: TeamMemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    await require_org_admin(current_user, db, org_id)

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == data.email))
    user = existing.scalar_one_or_none()
    if user:
        if user.organization_id == org_id:
            raise HTTPException(400, "User already belongs to this organization")
        else:
            raise HTTPException(400, "This email is already registered with another organization. Please use a different email.")
    
    # Get organization name for email
    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "the organization"

    temp_password = generate_temp_password()
    hashed_pw = get_password_hash(temp_password)
    new_user = User(
        email=data.email,
        full_name=data.full_name,
        role=data.role,
        organization_id=org_id,
        is_active=True,
        password_hash=hashed_pw,
        email_verified=True
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    reset_link = f"{FRONTEND_URL}/reset-password?email={data.email}"
    email_body = f"""
    <h2>Welcome to {org_name}</h2>
    <p>You have been invited as a <strong>{data.role}</strong>.</p>
    <p>Your temporary password is: <strong>{temp_password}</strong></p>
    <p>Please log in and change your password immediately.</p>
    <a href="{reset_link}">Click here to set your password</a>
    """
    #await send_email(data.email, f"Invitation to join {org_name}", email_body)
    print(reset_link);
    return {"message": f"Invitation sent to {data.email}"}

@router.delete("/{org_id}/{user_id}")
async def remove_team_member(
    org_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    await require_org_admin(current_user, db, org_id)
    if current_user.get("user_id") == str(user_id):
        raise HTTPException(400, "You cannot remove yourself")
    result = await db.execute(delete(User).where(User.id == user_id, User.organization_id == org_id))
    if result.rowcount == 0:
        raise HTTPException(404, "User not found in this organization")
    await db.commit()
    return {"status": "removed"}