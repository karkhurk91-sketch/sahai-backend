import json
import uuid
import importlib
from sqlalchemy import text
from modules.common.database import AsyncSessionLocal
from modules.common.models import Conversation
from modules.ai.lead_capture import create_lead
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def get_rule_reply(org_id: str, conversation_id: str, user_input: str):
    """
    Returns (reply_text, updated_state) or (None, None) if no rule matched.
    Also creates a lead when action is 'order_confirmed'.
    """
    # 1. Get organization's business_type
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT business_type FROM organizations WHERE id = :org_id"),
            {"org_id": uuid.UUID(org_id)}
        )
        row = result.fetchone()
        if not row:
            logger.warning(f"Organization {org_id} not found")
            return None, None
        industry = row[0] or "default"
        industry = industry.lower()

        # 2. Load current rule state from conversation
        conv_result = await db.execute(
            text("SELECT rule_state FROM conversations WHERE id = :conv_id"),
            {"conv_id": uuid.UUID(conversation_id)}
        )
        state_json = conv_result.scalar_one_or_none() or {}
        if isinstance(state_json, str):
            state_json = json.loads(state_json)

    # 3. Dynamically import the industry module (or default)
    try:
        mod = importlib.import_module(f"modules.ai.industries.{industry}")
    except ImportError:
        mod = importlib.import_module("modules.ai.industries.default")
        logger.info(f"Using default industry module for org {org_id} (industry={industry})")

    # 4. Create state object and restore from JSON
    state_cls = mod.State
    state = state_cls()
    if state_json:
        if hasattr(state, 'from_dict'):
            state.from_dict(state_json)
        else:
            for k, v in state_json.items():
                setattr(state, k, v)

    # 5. Run rules engine
    rules_engine = mod.RulesEngine()
    try:
        action_data = rules_engine.process(user_input, state)
        action = action_data["action"]
    except Exception as e:
        logger.error(f"Rules engine error: {e}")
        return None, None

    # 6. Get static reply from prompts
    prompts = mod.Prompts(org_id)
    reply = prompts.get_rule_reply(action, action_data.get("data", {}))

    if reply is None:
        logger.info(f"No rule reply for action {action} (org {org_id})")
        return None, None

    # 7. If action is order_confirmed, create a lead (for restaurant)
    if action == "order_confirmed":
        customer_phone = getattr(state, 'phone', None)
        customer_name = getattr(state, 'name', '')
        order_items = getattr(state, 'order_items', {})
        interest = f"Order: {', '.join(f'{qty}x {item}' for item, qty in order_items.items())}" if order_items else "Placed an order"
        if customer_phone:
            await create_lead(
                org_id=org_id,
                customer_phone=customer_phone,
                interest=interest,
                service="restaurant",
                customer_name=customer_name,
                lead_score=85
            )
            logger.info(f"Lead created for order confirmation: {customer_phone}")
        else:
            logger.warning(f"No customer phone in state, cannot create lead for conversation {conversation_id}")

    # 8. Save updated state back to conversation
    new_state_dict = state.to_dict() if hasattr(state, 'to_dict') else state.__dict__
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE conversations SET rule_state = :state WHERE id = :conv_id"),
            {"state": json.dumps(new_state_dict), "conv_id": uuid.UUID(conversation_id)}
        )
        await db.commit()

    logger.info(f"Rule mode reply generated: {reply[:50]}...")
    return reply, new_state_dict