import json
import uuid
import importlib
from sqlalchemy import text
from modules.common.database import AsyncSessionLocal
from modules.common.models import Conversation
from modules.ai.flow_service import get_org_conversation_flow
from modules.ai.lead_capture import create_lead
from modules.common.logger import get_logger
from modules.interactive.config_loader import get_default_conversation_flow

logger = get_logger(__name__)

async def get_rule_reply(org_id: str, conversation_id: str, user_input: str, customer_phone: str = None):
    """
    Returns (reply_text, updated_state) or (None, None) if no rule matched.
    Also creates a lead when action is 'order_confirmed' (restaurant) or 'lead_complete' (real estate).
    customer_phone is required for sending interactive messages.
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

    # 5. Load per-organization conversation flow if not already present in state
    # (Avoid reloading if the state already has a flow, e.g., from a previous message)
    if not hasattr(state, 'flow_steps') or not state.flow_steps:
        flow_type = getattr(state, 'flow_type', None) or "buyer"
        org_flow = await get_org_conversation_flow(org_id, flow_type=flow_type)
        if not org_flow and flow_type != "buyer":
            # If a non-buyer flow is configured but missing, fallback to buyer.
            org_flow = await get_org_conversation_flow(org_id, flow_type="buyer")
            if org_flow:
                flow_type = "buyer"
        if org_flow:
            state.flow_steps = org_flow
            state.flow_type = flow_type
            state.flow_source = "db"
        else:
            default_flow = get_default_conversation_flow(industry, flow_type=flow_type)
            if default_flow:
                state.flow_steps = default_flow
                state.flow_type = flow_type
                state.flow_source = "default"

    # 6. Run rules engine
    rules_engine = mod.RulesEngine()
    # If the state already has an interactive map, give it to the engine
    if hasattr(state, 'interactive_map') and state.interactive_map:
        rules_engine.id_value_map = state.interactive_map
    try:
        action_data = rules_engine.process(user_input, state)
        action = action_data["action"]
        logger.info(
            f"Rule engine action={action}, intent={state.last_intent}, stage={state.stage}, pending_confirmation={state.confirmation_pending}"
        )
    except Exception as e:
        logger.error(f"Rules engine error: {e}")
        return None, None

    # 7. Get static reply from prompts (pass state for dynamic replies)
    prompts = mod.Prompts(org_id)
    reply = prompts.get_rule_reply(action, action_data.get("data", {}), state=state)

    # 8. Save updated state back to conversation (MUST be done before returning)
    new_state_dict = state.to_dict() if hasattr(state, 'to_dict') else state.__dict__
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE conversations SET rule_state = :state WHERE id = :conv_id"),
            {"state": json.dumps(new_state_dict), "conv_id": uuid.UUID(conversation_id)}
        )
        await db.commit()

    # ----- Handle interactive replies -----
    if isinstance(reply, dict) and reply.get("type") == "interactive":
        interactive_data = reply.get("interactive")
        value_map = reply.get("value_map", {})
        # Store the value_map in the state for future mapping of button/list replies
        state.interactive_map = value_map
        rules_engine.id_value_map = value_map
        # Also save the map into the conversation state (will be persisted on next message)
        updated_state_dict = state.to_dict() if hasattr(state, 'to_dict') else state.__dict__
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE conversations SET rule_state = :state WHERE id = :conv_id"),
                {"state": json.dumps(updated_state_dict), "conv_id": uuid.UUID(conversation_id)}
            )
            await db.commit()
        # Send interactive message
        if customer_phone:
            from modules.message.sender import send_whatsapp_interactive
            success, wamid = await send_whatsapp_interactive(customer_phone, interactive_data, org_id)
            if success:
                logger.info(f"Interactive message sent to {customer_phone}, wamid={wamid}")
        else:
            logger.error("Cannot send interactive message: customer_phone missing")
        # Return special marker to indicate interactive was sent (no text reply)
        return "__INTERACTIVE__", updated_state_dict

    if reply is None:
        logger.info(f"No rule reply for action {action} (org {org_id})")
        return None, new_state_dict

    # 9. Handle lead creation for different actions
    if action == "order_confirmed":
        # Restaurant order confirmation
        customer_phone_state = getattr(state, 'phone', None)
        customer_name = getattr(state, 'name', '')
        order_items = getattr(state, 'order_items', {})
        interest = f"Order: {', '.join(f'{qty}x {item}' for item, qty in order_items.items())}" if order_items else "Placed an order"
        if customer_phone_state:
            await create_lead(
                org_id=org_id,
                customer_phone=customer_phone_state,
                interest=interest,
                service="restaurant",
                customer_name=customer_name,
                lead_score=85
            )
            logger.info(f"Lead created for order confirmation: {customer_phone_state}")
        else:
            logger.warning(f"No customer phone in state, cannot create lead for conversation {conversation_id}")

    elif action == "lead_complete":
        # Real estate lead completion (all fields collected)
        lead_data = action_data.get("data", {})
        # Fallback to state attributes if not in action_data
        phone = lead_data.get("phone") or getattr(state, 'phone', None)
        name = lead_data.get("name") or getattr(state, 'name', '')
        budget = lead_data.get("budget") or getattr(state, 'budget', '')
        location = lead_data.get("location") or getattr(state, 'location', '')
        bhk = lead_data.get("bhk") or getattr(state, 'bhk', '')
        lead_tag = getattr(state, 'lead_tag', None)
        lead_score = getattr(state, 'bant_score', 70)
        if phone:
            await create_lead(
                org_id=org_id,
                customer_phone=phone,
                customer_name=name,
                extracted_data={
                    "name": name,
                    "phone": phone,
                    "budget": budget,
                    "location": location,
                    "bhk": bhk,
                    "lead_tag": lead_tag,
                },
                lead_score=lead_score,
                interest=f"{bhk} BHK in {location}",
                service="real_estate",
                intent="buy",
                rule_state=state.to_dict()
            )
            logger.info(f"Lead created from rule mode (real estate) for {phone}, lead_tag={lead_tag}, score={lead_score}")
        else:
            logger.warning(f"Cannot create lead: no phone number in state")

    logger.info(f"Rule mode reply generated: {reply[:50]}...")
    return reply, new_state_dict