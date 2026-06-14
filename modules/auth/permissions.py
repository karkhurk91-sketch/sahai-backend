from modules.common.config import ENABLE_ROLE_PERMISSIONS
from modules.common.models import Role, Permission, UserPermission
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List
import logging

logger = logging.getLogger(__name__)

async def get_effective_permissions(user, db):
    """Return a list of permission strings for the given user."""
    if not ENABLE_ROLE_PERMISSIONS:
        logger.debug("ENABLE_ROLE_PERMISSIONS=false – returning empty permissions")
        return []

    user_role = user.role
    logger.info(f"Fetching permissions for role: '{user_role}'")

    # Try to get the role with its permissions eagerly loaded
    role_result = await db.execute(
        select(Role)
        .where(Role.name == user_role)
        .options(selectinload(Role.permissions))
    )
    role = role_result.scalar_one_or_none()

    perms = set()
    if role:
        for rp in role.permissions:
            perms.add(rp.name)
        logger.info(f"Permissions from role '{user_role}': {perms}")
    else:
        logger.warning(f"Role '{user_role}' not found in roles table – only user‑specific permissions will be used")

    # Add any user‑specific permissions (from the user_permissions table)
    user_perms = await db.execute(
        select(Permission).join(UserPermission).where(UserPermission.user_id == user.id)
    )
    for up in user_perms.scalars():
        perms.add(up.name)
        logger.debug(f"Added user‑specific permission: {up.name}")

    return list(perms)