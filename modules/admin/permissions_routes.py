from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from modules.common.database import get_db
from modules.common.models import Role, Permission, RolePermission, User, UserPermission, Organization
from modules.auth.jwt import get_current_user, get_current_super_admin
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/api/admin/permissions", tags=["Admin Permissions"])

class RolePermissionUpdate(BaseModel):
    permission_names: List[str]

# ========== Role Permissions (existing) ==========
@router.get("/roles")
async def list_roles(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin only")
    result = await db.execute(select(Role))
    roles = result.scalars().all()
    return [{"id": str(r.id), "name": r.name, "description": r.description} for r in roles]

@router.get("/permissions")
async def list_permissions(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin only")
    result = await db.execute(select(Permission))
    perms = result.scalars().all()
    return [{"id": str(p.id), "name": p.name, "description": p.description} for p in perms]

@router.get("/roles/{role_id}/permissions")
async def get_role_permissions(role_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin only")
    result = await db.execute(select(RolePermission).where(RolePermission.role_id == role_id))
    perm_ids = [rp.permission_id for rp in result.scalars()]
    perms = await db.execute(select(Permission).where(Permission.id.in_(perm_ids)))
    return [p.name for p in perms.scalars()]

@router.put("/roles/{role_id}/permissions")
async def update_role_permissions(role_id: str, data: RolePermissionUpdate, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin only")
    # Get permission ids
    perm_result = await db.execute(select(Permission).where(Permission.name.in_(data.permission_names)))
    perm_ids = [p.id for p in perm_result.scalars()]
    # Delete existing
    await db.execute(RolePermission.__table__.delete().where(RolePermission.role_id == role_id))
    # Insert new
    for pid in perm_ids:
        db.add(RolePermission(role_id=role_id, permission_id=pid))
    await db.commit()
    return {"status": "updated"}

# ========== User Permission Management (Super Admin only) ==========
class UserPermissionUpdate(BaseModel):
    permission_names: List[str]

@router.get("/users")
async def list_users(
    search: Optional[str] = None,
    role: Optional[str] = None,
    org_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """List all users (super admin only)."""
    query = select(User).order_by(User.created_at.desc())
    
    if search:
        query = query.where(
            or_(
                User.email.contains(search),
                User.full_name.contains(search)
            )
        )
    if role:
        query = query.where(User.role == role)
    if org_id:
        query = query.where(User.organization_id == org_id)
    
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.offset(offset).limit(limit))
    users = result.scalars().all()
    
    # Enrich with organization name
    user_list = []
    for u in users:
        org_name = None
        if u.organization_id:
            org_res = await db.execute(select(Organization.name).where(Organization.id == u.organization_id))
            org_name = org_res.scalar_one_or_none()
        user_list.append({
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "organization_id": str(u.organization_id) if u.organization_id else None,
            "organization_name": org_name,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None
        })
    
    return {"data": user_list, "total": total, "offset": offset, "limit": limit}

@router.get("/users/{user_id}/permissions")
async def get_user_permissions(
    user_id: str,
    current_user = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get the list of permission names directly assigned to this user (overrides)."""
    result = await db.execute(
        select(Permission.name)
        .join(UserPermission)
        .where(UserPermission.user_id == user_id)
    )
    permissions = result.scalars().all()
    return {"permissions": list(permissions)}

@router.put("/users/{user_id}/permissions")
async def update_user_permissions(
    user_id: str,
    data: UserPermissionUpdate,
    current_user = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Replace the user's specific permissions with the provided list."""
    # Verify user exists
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    
    # Get permission IDs from names
    perm_result = await db.execute(
        select(Permission).where(Permission.name.in_(data.permission_names))
    )
    perm_ids = [p.id for p in perm_result.scalars()]
    
    # Delete existing user permissions
    await db.execute(UserPermission.__table__.delete().where(UserPermission.user_id == user_id))
    
    # Insert new ones
    for pid in perm_ids:
        db.add(UserPermission(user_id=user_id, permission_id=pid))
    await db.commit()
    return {"status": "updated", "user_id": user_id, "permissions": data.permission_names}