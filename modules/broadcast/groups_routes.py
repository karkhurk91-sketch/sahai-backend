from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from uuid import UUID
from typing import List
from pydantic import BaseModel

from modules.common.database import get_db
from modules.auth.jwt import get_current_user
from modules.common.models import CustomerGroup, CustomerGroupMember, Customer
from modules.common.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/broadcast/groups", tags=["Broadcast Groups"])

class GroupCreate(BaseModel):
    name: str
    customer_ids: List[UUID] = []

@router.post("/")
async def create_group(
    data: GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    group = CustomerGroup(organization_id=org_id, name=data.name)
    db.add(group)
    await db.flush()
    for cid in data.customer_ids:
        member = CustomerGroupMember(group_id=group.id, customer_id=cid)
        db.add(member)
    await db.commit()
    await db.refresh(group)
    return {"id": str(group.id), "name": group.name, "customer_count": len(data.customer_ids)}

@router.get("/")
async def list_groups(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    stmt = select(CustomerGroup).where(CustomerGroup.organization_id == org_id).order_by(CustomerGroup.name)
    result = await db.execute(stmt)
    groups = result.scalars().all()
    output = []
    for g in groups:
        # Count members using func.count()
        count_stmt = select(func.count()).select_from(CustomerGroupMember).where(CustomerGroupMember.group_id == g.id)
        count = (await db.execute(count_stmt)).scalar() or 0
        output.append({"id": str(g.id), "name": g.name, "customer_count": count})
    return output

@router.get("/{group_id}/customers")
async def get_group_customers(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    # Verify group belongs to org
    group_stmt = select(CustomerGroup).where(CustomerGroup.id == group_id, CustomerGroup.organization_id == org_id)
    group = (await db.execute(group_stmt)).scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")
    stmt = select(Customer).join(CustomerGroupMember, Customer.id == CustomerGroupMember.customer_id).where(CustomerGroupMember.group_id == group_id)
    result = await db.execute(stmt)
    customers = result.scalars().all()
    return [{"id": str(c.id), "name": c.name, "phone_number": c.phone_number, "email": c.email} for c in customers]

@router.post("/{group_id}/members")
async def add_members_to_group(
    group_id: UUID,
    customer_ids: List[UUID],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    group_stmt = select(CustomerGroup).where(CustomerGroup.id == group_id, CustomerGroup.organization_id == org_id)
    group = (await db.execute(group_stmt)).scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")
    for cid in customer_ids:
        # Optional: verify customer belongs to organization
        member = CustomerGroupMember(group_id=group_id, customer_id=cid)
        db.add(member)
    await db.commit()
    return {"status": "added"}

@router.delete("/{group_id}")
async def delete_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    stmt = delete(CustomerGroup).where(CustomerGroup.id == group_id, CustomerGroup.organization_id == org_id)
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Group not found")
    return {"status": "deleted"}