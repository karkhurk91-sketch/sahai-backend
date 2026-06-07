# modules/ai/flow_service.py

import json
import logging
import uuid
from typing import List, Dict, Optional, Any, Tuple
from sqlalchemy import select
from modules.common.database import AsyncSessionLocal
from modules.common.models import OrganizationConversationFlow
from modules.interactive.config_loader import get_default_conversation_flow

logger = logging.getLogger(__name__)

# In-memory cache for flows (organization_id + flow_type -> steps)
# Use a simple dict with TTL or async cache in production.
# For now, a simple dict with no expiration is fine (flows rarely change).
_FLOW_CACHE: Dict[str, List[Dict]] = {}

def _get_cache_key(org_id: str, flow_type: str) -> str:
    return f"{org_id}:{flow_type}"

async def get_org_conversation_flow(org_id: str, flow_type: str = "buyer", industry: str = "realestate", return_seeded: bool = False) -> Optional[List[Dict]] | Tuple[Optional[List[Dict]], bool]:
    """
    Fetch the conversation flow steps for an organization from the database.
    If no active flow exists, seed the default flow and return it.
    """
    cache_key = _get_cache_key(org_id, flow_type)
    if cache_key in _FLOW_CACHE:
        logger.debug(f"Returning cached flow for {cache_key}")
        if return_seeded:
            return _FLOW_CACHE[cache_key], False
        return _FLOW_CACHE[cache_key]

    # normalize org_id to UUID for DB comparisons
    try:
        org_uuid = uuid.UUID(org_id) if isinstance(org_id, str) else org_id
    except Exception:
        org_uuid = org_id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OrganizationConversationFlow.steps)
            .where(
                OrganizationConversationFlow.organization_id == org_uuid,
                OrganizationConversationFlow.flow_type == flow_type,
                OrganizationConversationFlow.is_active == True
            )
        )
        steps = result.scalar_one_or_none()
        if steps:
            if not isinstance(steps, list):
                steps = []
            _FLOW_CACHE[cache_key] = steps
            logger.info(f"Loaded flow for org {org_id}, flow_type={flow_type}, steps={len(steps)}")
            if return_seeded:
                return steps, False
            return steps

    logger.info(f"No active flow found for org {org_id}, flow_type={flow_type}")
    default_steps = get_default_conversation_flow(industry, flow_type)
    if default_steps:
        seeded = await _seed_default_flow(org_id, flow_type, default_steps)
        if return_seeded:
            return default_steps, seeded
        return default_steps

    # If no configured flow exists for the requested type, try any active flow for the organization.
    if flow_type == "buyer":
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(OrganizationConversationFlow.steps)
                .where(
                    OrganizationConversationFlow.organization_id == org_uuid,
                    OrganizationConversationFlow.is_active == True
                )
                .limit(1)
            )
            steps = result.scalar_one_or_none()
            if steps:
                if not isinstance(steps, list):
                    steps = []
                _FLOW_CACHE[cache_key] = steps
                logger.info(f"Loaded fallback active flow for org {org_id} with flow_type={flow_type}")
                if return_seeded:
                    return steps, False
                return steps

    if return_seeded:
        return None, False
    return None

def invalidate_flow_cache(org_id: str, flow_type: str = None):
    """
    Invalidate the cache for a specific organization and flow type.
    If flow_type is None, invalidate all flows for the organization.
    """
    if flow_type:
        cache_key = _get_cache_key(org_id, flow_type)
        _FLOW_CACHE.pop(cache_key, None)
        logger.info(f"Invalidated cache for {cache_key}")
    else:
        keys_to_remove = [k for k in _FLOW_CACHE.keys() if k.startswith(f"{org_id}:")]
        for k in keys_to_remove:
            _FLOW_CACHE.pop(k, None)
        logger.info(f"Invalidated all flow caches for org {org_id}")

# Optional: Function to set/update flow (for admin API)
async def _seed_default_flow(org_id: str, flow_type: str, steps: List[Dict]) -> bool:
    """Insert or reactivate a default flow record for the organization."""
    try:
        org_uuid = uuid.UUID(org_id) if isinstance(org_id, str) else org_id
    except Exception:
        org_uuid = org_id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OrganizationConversationFlow)
            .where(
                OrganizationConversationFlow.organization_id == org_uuid,
                OrganizationConversationFlow.flow_type == flow_type
            )
        )
        flow = result.scalar_one_or_none()
        if flow:
            flow.steps = steps
            flow.is_active = True
            logger.info(f"Reactivated default flow for org {org_id}, flow_type={flow_type}")
        else:
            flow = OrganizationConversationFlow(
                organization_id=org_id,
                flow_type=flow_type,
                steps=steps,
                is_active=True
            )
            db.add(flow)
            logger.info(f"Seeded default flow for org {org_id}, flow_type={flow_type}")
        await db.commit()
    invalidate_flow_cache(org_id, flow_type)
    return True

async def set_org_conversation_flow(org_id: str, flow_type: str, steps: List[Dict], is_active: bool = True) -> OrganizationConversationFlow:
    """
    Update or insert the conversation flow for an organization.
    Returns the updated flow record.
    """
    try:
        org_uuid = uuid.UUID(org_id) if isinstance(org_id, str) else org_id
    except Exception:
        org_uuid = org_id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OrganizationConversationFlow)
            .where(
                OrganizationConversationFlow.organization_id == org_uuid,
                OrganizationConversationFlow.flow_type == flow_type
            )
        )
        flow = result.scalar_one_or_none()
        if flow:
            flow.steps = steps
            flow.is_active = is_active
        else:
            flow = OrganizationConversationFlow(
                organization_id=org_id,
                flow_type=flow_type,
                steps=steps,
                is_active=is_active
            )
            db.add(flow)
        await db.commit()
        await db.refresh(flow)
    invalidate_flow_cache(org_id, flow_type)
    return flow

async def delete_org_conversation_flow(org_id: str, flow_type: str) -> bool:
    """Soft delete the active conversation flow for an organization."""
    try:
        org_uuid = uuid.UUID(org_id) if isinstance(org_id, str) else org_id
    except Exception:
        org_uuid = org_id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OrganizationConversationFlow)
            .where(
                OrganizationConversationFlow.organization_id == org_uuid,
                OrganizationConversationFlow.flow_type == flow_type,
                OrganizationConversationFlow.is_active == True
            )
        )
        flow = result.scalar_one_or_none()
        if not flow:
            return False
        flow.is_active = False
        await db.commit()
    invalidate_flow_cache(org_id, flow_type)
    return True
