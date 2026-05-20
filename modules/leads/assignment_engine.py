import re
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select, update
from modules.common.database import AsyncSessionLocal
from modules.common.models import User, Lead, Conversation
from modules.common.logger import get_logger

logger = get_logger(__name__)

URGENT_KEYWORDS = [
    "urgent", "asap", "immediately", "right away", "today", "soon", "need now", "emergency", "priority"
]
POSITIVE_KEYWORDS = [
    "yes", "sure", "definitely", "absolutely", "thanks", "thank you", "great", "love", "excited", "ready"
]
NEGATIVE_KEYWORDS = [
    "no", "not", "don't", "dont", "later", "maybe", "cancel", "problem", "issue", "delay", "stop"
]
PURCHASE_KEYWORDS = [
    "buy", "purchase", "order", "book", "reserve", "schedule", "close", "sign up", "subscribe"
]
PRICE_KEYWORDS = [
    "price", "cost", "quote", "estimate", "budget", "fee", "pricing"
]
SUPPORT_KEYWORDS = [
    "help", "support", "issue", "problem", "question", "need assistance", "assist"
]
REGIONAL_LANGUAGE_MAP = {
    "namaste": "hi",
    "hola": "es",
    "bonjour": "fr",
    "hallo": "de",
    "salaam": "ar",
    "salaam aleikum": "ar",
    "mashallah": "ar",
    "你好": "zh",
    "नमस्ते": "hi",
    "こんにちは": "ja",
    "สวัสดี": "th",
    "cześć": "pl",
}


def _normalize_text(conversation_history, extracted_data):
    fragments = []
    if isinstance(extracted_data, dict):
        fragments.extend([str(v) for v in extracted_data.values() if v is not None])
    for item in conversation_history or []:
        if isinstance(item, dict):
            fragments.append(str(item.get("text", "")))
        else:
            fragments.append(str(item))
    return " ".join(fragments).lower()


def _contains_any(text: str, keywords):
    return any(keyword in text for keyword in keywords)


def detect_language(text: str) -> str:
    for phrase, code in REGIONAL_LANGUAGE_MAP.items():
        if phrase in text:
            return code
    return "en"


def determine_intent(text: str, extracted_data: dict) -> str:
    intent = extracted_data.get("intent") if isinstance(extracted_data, dict) else None
    if intent:
        return str(intent).strip().lower()

    if _contains_any(text, PURCHASE_KEYWORDS):
        return "purchase"
    if _contains_any(text, PRICE_KEYWORDS):
        return "pricing"
    if _contains_any(text, SUPPORT_KEYWORDS):
        return "support"
    return "inquiry"


def determine_urgency(text: str, extracted_data: dict) -> str:
    if _contains_any(text, URGENT_KEYWORDS):
        return "high"
    if _contains_any(text, ["soon", "quick", "fast", "priority", "important"]):
        return "medium"
    return "low"


def determine_sentiment(text: str) -> str:
    if _contains_any(text, POSITIVE_KEYWORDS):
        return "positive"
    if _contains_any(text, NEGATIVE_KEYWORDS):
        return "negative"
    return "neutral"


def determine_lead_stage(text: str, extracted_data: dict) -> str:
    stage = extracted_data.get("lead_stage") if isinstance(extracted_data, dict) else None
    if stage:
        return str(stage).strip().lower()
    if _contains_any(text, ["ready to buy", "ready to purchase", "let's move", "book now", "sign up", "close deal"]):
        return "qualified"
    if _contains_any(text, ["maybe", "later", "not sure", "thinking", "considering", "keep in touch"]):
        return "nurture"
    return "new"


def determine_conversion_probability(extracted_data: dict, urgency: str, lead_stage: str) -> float:
    base = 0.5
    score = extracted_data.get("lead_score") if isinstance(extracted_data, dict) else None
    if score is not None:
        try:
            base = min(max(float(score) / 100.0, 0.05), 0.95)
        except Exception:
            base = 0.5

    if urgency == "high":
        base += 0.15
    elif urgency == "low":
        base -= 0.05

    if lead_stage == "qualified":
        base += 0.1
    elif lead_stage == "nurture":
        base -= 0.05

    return min(max(base, 0.05), 0.98)


def determine_follow_up_window(urgency: str) -> timedelta:
    if urgency == "high":
        return timedelta(hours=6)
    if urgency == "medium":
        return timedelta(hours=24)
    return timedelta(hours=72)


async def determine_lead_intelligence(conversation_history: list, extracted_data: dict) -> dict:
    normalized_text = _normalize_text(conversation_history, extracted_data)
    urgency = determine_urgency(normalized_text, extracted_data)
    sentiment = determine_sentiment(normalized_text)
    stage = determine_lead_stage(normalized_text, extracted_data)
    intent = determine_intent(normalized_text, extracted_data)
    conversion_probability = determine_conversion_probability(extracted_data, urgency, stage)
    follow_up_at = datetime.utcnow() + determine_follow_up_window(urgency)
    language = detect_language(normalized_text)

    return {
        "urgency": urgency,
        "intent": intent,
        "sentiment": sentiment,
        "conversion_probability": conversion_probability,
        "follow_up_scheduled_at": follow_up_at,
        "lead_stage": stage,
        "rule_state": {
            "source": "ai_intelligence",
            "stage": stage,
            "intent": intent,
            "urgency": urgency,
            "sentiment": sentiment,
            "language": language,
            "updated_at": datetime.utcnow().isoformat(),
        },
    }


async def auto_assign_lead(org_id: str, conversation_id: str, extracted_lead_data: dict):
    if not conversation_id:
        return

    # Prefer a regional or role-specific sales agent if the extracted lead suggests a specific vertical.
    target_roles = ["sales", "agent"]
    if extracted_lead_data and isinstance(extracted_lead_data.get("property_type"), str):
        if "commercial" in extracted_lead_data.get("property_type", "").lower():
            target_roles.insert(0, "commercial_sales")

    try:
        async with AsyncSessionLocal() as db:
            user = None
            for role in target_roles:
                result = await db.execute(
                    select(User)
                    .where(User.organization_id == uuid.UUID(org_id), User.role == role, User.is_active == True)
                    .limit(1)
                )
                user = result.scalars().first()
                if user:
                    break

            if not user:
                result = await db.execute(
                    select(User)
                    .where(User.organization_id == uuid.UUID(org_id), User.is_active == True)
                    .limit(1)
                )
                user = result.scalars().first()

            if not user:
                logger.info(f"No available agent found for auto-assignment org={org_id}")
                return

            await db.execute(
                update(Conversation)
                .where(Conversation.id == uuid.UUID(conversation_id))
                .values(assigned_agent_id=user.id)
            )
            await db.execute(
                update(Lead)
                .where(Lead.conversation_id == uuid.UUID(conversation_id), Lead.organization_id == uuid.UUID(org_id))
                .values(assigned_to=user.id)
            )
            await db.commit()
            logger.info(f"Auto-assigned conversation {conversation_id} and lead to user {user.id}")
    except Exception as e:
        logger.error(f"Auto-assignment failed for conversation {conversation_id}: {e}", exc_info=True)
