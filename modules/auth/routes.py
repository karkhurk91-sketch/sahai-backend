from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from modules.common.database import get_db
from modules.common.models import User, Organization, Partner, Permission, UserPermission
from modules.auth.jwt import hash_password, verify_password, create_access_token, get_current_user, get_password_hash, blacklist_token
from modules.common.config import SECRET_KEY, ALGORITHM, FRONTEND_URL, ENABLE_ROLE_PERMISSIONS
from modules.common.email import send_email
from modules.auth.permissions import get_effective_permissions
from pydantic import BaseModel, EmailStr
from typing import Optional
import uuid
import secrets
from datetime import timedelta
from jose import jwt
from datetime import datetime

logger = None

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# ---------- Pydantic models ----------
class SignupRequest(BaseModel):
    name: str
    business_type: Optional[str] = None
    gst: Optional[str] = None
    description: Optional[str] = None
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.get("/me/permissions")
async def get_my_permissions(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    role = current_user.get("role")
    if role in ("super_admin", "partner"):
        return {"role": role, "permissions": []}
    user_id = current_user.get("user_id")
    stmt = select(Permission.name).join(UserPermission).where(UserPermission.user_id == user_id)
    result = await db.execute(stmt)
    perms = result.scalars().all()
    return {"role": role, "permissions": list(perms)}

@router.post("/logout")
async def logout(
    request: Request,
    credentials = Depends(get_current_user)
):
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        await blacklist_token(token)
    return {"message": "Logged out successfully"}

# ---------- Public signup with email verification ----------
@router.post("/signup")
async def public_signup(
    req: SignupRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == req.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(400, "Email already registered")
    new_org = Organization(
        name=req.name,
        business_type=req.business_type,
        status="pending",
        settings={"gst": req.gst, "description": req.description}
    )
    db.add(new_org)
    await db.flush()
    hashed = hash_password(req.password)
    verification_token = secrets.token_urlsafe(32)
    new_user = User(
        email=req.email,
        password_hash=hashed,
        full_name=req.name,
        role="org_admin",
        organization_id=new_org.id,
        is_active=True,
        email_verified=False,
        verification_token=verification_token
    )
    db.add(new_user)
    await db.commit()
    verification_link = f"{FRONTEND_URL}/verify-email?token={verification_token}"
    email_body = f"""
    <h2>Welcome to WAAI!</h2>
    <p>Please verify your email by clicking the link below:</p>
    <a href="{verification_link}">Verify Email</a>
    <p>This link will expire in 24 hours.</p>
    """
    background_tasks.add_task(send_email, req.email, "Verify your email", email_body)
    return {"message": "Registration successful. Please check your email to verify your account."}

@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.verification_token == token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(400, "Invalid or expired token")
    user.email_verified = True
    user.verification_token = None
    await db.commit()
    return {"message": "Email verified. You can now log in."}

# ---------- Login (checks email verification) ----------
@router.post("/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(401, "Account disabled")
    if not user.email_verified:
        raise HTTPException(401, "Email not verified. Please check your inbox.")
    
    if user.role in ["org_admin", "agent", "viewer"]:
        org_result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
        org = org_result.scalar_one_or_none()
        if not org or org.status != "active":
            raise HTTPException(401, "Organization not approved or suspended")
    
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    
    user.last_login = datetime.utcnow()
    await db.commit()
    
    # Build base token data (without permissions claim)
    if user.role == "partner":
        partner = await db.execute(select(Partner).where(Partner.user_id == user.id))
        partner = partner.scalar_one_or_none()
        partner_id = str(partner.id) if partner else None
        token_data = {
            "sub": str(user.id),
            "user_id": str(user.id),
            "email": user.email,
            "role": user.role,
            "org_id": None,
            "partner_id": partner_id,
        }
    elif user.role in ["org_admin", "agent", "viewer"]:
        token_data = {
            "sub": str(user.id),
            "user_id": str(user.id),
            "email": user.email,
            "role": user.role,
            "org_id": str(user.organization_id) if user.organization_id else None,
        }
    else:  # super_admin
        token_data = {
            "sub": str(user.id),
            "user_id": str(user.id),
            "email": user.email,
            "role": user.role,
            "org_id": None,
        }
    
    # Only add permissions claim if feature flag is enabled
    if ENABLE_ROLE_PERMISSIONS:
        permissions = await get_effective_permissions(user, db)
        token_data["permissions"] = permissions
    
    access_token = create_access_token(token_data)
    return {"access_token": access_token, "token_type": "bearer"}

# ---------- Forgot password (sends reset link) ----------
@router.post("/forgot-password")
async def forgot_password(
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        return {"message": "If an account exists, a reset link has been sent."}
    reset_token = create_access_token(
        data={"sub": str(user.id), "purpose": "reset"},
        expires_delta=timedelta(minutes=30)
    )
    reset_link = f"{FRONTEND_URL}/reset-password?token={reset_token}"
    email_body = f"""
    <h2>Password Reset Request</h2>
    <p>Click the link below to reset your password. This link expires in 30 minutes.</p>
    <a href="{reset_link}">Reset Password</a>
    """
    print(reset_link)
    background_tasks.add_task(send_email, user.email, "Reset your password", email_body)
    return {"message": "If an account exists, a reset link has been sent."}

# ---------- Reset password ----------
@router.post("/reset-password")
async def reset_password(
    req: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        payload = jwt.decode(req.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "reset":
            raise HTTPException(400, "Invalid token")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(400, "Invalid token")
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(400, "Invalid token")
        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(400, "User not found")
        new_hash = hash_password(req.new_password)
        user.password_hash = new_hash
        await db.commit()
        return {"message": "Password updated. You can now log in."}
    except jwt.PyJWTError:
        raise HTTPException(400, "Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error during password reset: {e}")
        raise HTTPException(500, "Internal server error")

# ========== TEMPORARY: Create super admin (remove after first use) ==========
@router.post("/setup-first-admin")
async def setup_first_admin(
    email: str,
    password: str,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User))
    if result.first():
        raise HTTPException(403, "Setup already completed. Admin user exists.")
    hashed = hash_password(password)
    new_user = User(
        email=email,
        password_hash=hashed,
        full_name="Super Admin",
        role="super_admin",
        is_active=True,
        email_verified=True
    )
    db.add(new_user)
    await db.commit()
    return {"message": "Super admin created successfully. Please login."}

# ========== SUPER ADMIN SIGNUP (one-time) ==========
class SuperAdminSignup(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: str   

@router.post("/signup-super-admin")
async def signup_super_admin(
    req: SuperAdminSignup,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.role == "super_admin"))
    if result.first():
        raise HTTPException(400, "Super admin already exists. Please contact support.")
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    hashed = hash_password(req.password)
    new_user = User(
        email=req.email,
        password_hash=hashed,
        full_name=req.full_name,
        role="super_admin",
        is_active=True,
        email_verified=True,
        settings={"mobile": req.phone}
    )
    db.add(new_user)
    await db.commit()
    return {"message": "Super admin created. Please login."}

class PartnerSignupRequest(BaseModel):
    email: EmailStr
    password: str
    business_name: str

@router.post("/partner-signup")
async def partner_signup(
    data: PartnerSignupRequest,
    db: AsyncSession = Depends(get_db)
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    hashed = get_password_hash(data.password)
    user = User(
        email=data.email,
        password_hash=hashed,
        full_name=data.business_name,
        role="partner",
        is_active=True,
        email_verified=True
    )
    db.add(user)
    await db.flush()
    partner = Partner(
        name=data.business_name,
        user_id=user.id,
        status="active"
    )
    db.add(partner)
    await db.commit()
    await db.refresh(partner)
    
    # Build base token data for partner
    token_data = {
        "sub": str(user.id),
        "user_id": str(user.id),
        "email": user.email,
        "role": "partner",
        "org_id": None,
        "partner_id": str(partner.id),
    }
    
    # Only add permissions claim if feature flag is enabled
    if ENABLE_ROLE_PERMISSIONS:
        permissions = await get_effective_permissions(user, db)
        token_data["permissions"] = permissions
    
    access_token = create_access_token(token_data)
    return {"access_token": access_token, "token_type": "bearer", "partner_id": str(partner.id)}