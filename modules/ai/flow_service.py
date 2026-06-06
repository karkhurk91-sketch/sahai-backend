import uuid
from sqlalchemy import text
from modules.common.database import AsyncSessionLocal


async def get_org_conversation_flow(org_id: str, flow_type: str = "buyer"):
    """Load active conversation flow steps for an organization."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT steps
                FROM organization_conversation_flows
                WHERE organization_id = :org_id
                  AND flow_type = :flow_type
                  AND is_active = true
                LIMIT 1
                """
            ),
            {"org_id": uuid.UUID(org_id), "flow_type": flow_type},
        )
        return result.scalar_one_or_none()
