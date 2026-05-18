from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.common.models import AuditLog
from modules.common.logger import get_logger
from modules.common.database import get_db
from typing import Dict, Any, Optional
from uuid import UUID
import json

logger = get_logger(__name__)

class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_action(
        self,
        organization_id: UUID,
        user_id: Optional[UUID],
        action: str,
        resource_type: str,
        resource_id: Optional[UUID] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log an auditable action."""
        try:
            audit_log = AuditLog(
                organization_id=organization_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                old_values=old_values,
                new_values=new_values,
                ip_address=ip_address,
                user_agent=user_agent,
                extra_metadata=metadata
            )

            self.session.add(audit_log)
            await self.session.commit()

            logger.info(f"AUDIT: {action} {resource_type} by user {user_id} in org {organization_id}")

        except Exception as e:
            logger.error(f"Failed to log audit action: {e}")
            # Don't fail the main operation if audit logging fails
            await self.session.rollback()

    async def get_audit_logs(
        self,
        organization_id: UUID,
        resource_type: Optional[str] = None,
        user_id: Optional[UUID] = None,
        action: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ):
        """Retrieve audit logs with filtering."""
        query = select(AuditLog).where(AuditLog.organization_id == organization_id)

        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if action:
            query = query.where(AuditLog.action == action)

        query = query.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)

        result = await self.session.execute(query)
        return result.scalars().all()

# Dependency injection function
async def get_audit_service(session: Any = Depends(get_db)) -> AuditService:
    return AuditService(session)