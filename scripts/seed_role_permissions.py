#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from sqlalchemy import select
from modules.common.database import AsyncSessionLocal
from modules.common.models import Role, Permission, RolePermission

ROLE_PERMISSIONS = {
    "super_admin": "*",   # all permissions
    "org_admin": [
        "view_dashboard", "manage_customers", "manage_campaigns", "manage_leads",
        "manage_conversations", "manage_templates", "manage_broadcast", "manage_knowledge_base",
        "manage_bookings", "view_calendar", "view_analytics", "manage_ai_prompts",
        "manage_team", "manage_integrations", "manage_custom_fields", "manage_bot_builder",
        "manage_lead_schemas", "manage_nurturing", "view_audit_logs"
    ],
    "partner": [
        "view_dashboard", "manage_customers", "manage_leads", "manage_conversations",
        "view_analytics", "manage_team"
    ],
    "agent": [
        "view_dashboard", "manage_customers", "manage_leads", "manage_conversations",
        "view_analytics"
    ],
    "viewer": [
        "view_dashboard", "view_analytics"
    ]
}

async def seed():
    async with AsyncSessionLocal() as session:
        # Get all permissions
        perms = await session.execute(select(Permission))
        perm_map = {p.name: p.id for p in perms.scalars()}
        if not perm_map:
            print("No permissions found in database. Run migrations first.")
            return

        # Get all roles
        roles = await session.execute(select(Role))
        role_map = {r.name: r.id for r in roles.scalars()}
        if not role_map:
            print("No roles found. Did you run alembic upgrade head?")
            return

        for role_name, perm_names in ROLE_PERMISSIONS.items():
            role_id = role_map.get(role_name)
            if not role_id:
                continue
            # Clear existing assignments
            await session.execute(RolePermission.__table__.delete().where(RolePermission.role_id == role_id))
            if perm_names == "*":
                perm_names = list(perm_map.keys())
            for pname in perm_names:
                pid = perm_map.get(pname)
                if pid:
                    session.add(RolePermission(role_id=role_id, permission_id=pid))
        await session.commit()
        print("✅ Role permissions seeded successfully.")

if __name__ == "__main__":
    asyncio.run(seed())