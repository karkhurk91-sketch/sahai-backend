# modules/ai/lead_extractor.py
import json
from typing import List, Dict, Any, Optional, Union
from modules.ai.agent import client
from modules.common.logger import get_logger

logger = get_logger(__name__)
DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _normalize_schema_fields(schema_fields: Union[List[Dict], List[str]]) -> List[Dict]:
    """
    Convert schema fields to a unified list of dicts.
    - If list of strings: create dict with 'name' = string, 'type' = 'string', 'required' = False
    - If list of dicts: return as is (assumes already correct)
    """
    normalized = []
    for field in schema_fields:
        if isinstance(field, dict):
            normalized.append(field)
        elif isinstance(field, str):
            normalized.append({
                "name": field,
                "label": field,
                "type": "string",
                "required": False
            })
        else:
            logger.warning(f"Unexpected schema field type: {type(field)}")
    return normalized


def _format_field_description(field: Dict[str, Any]) -> str:
    name = field.get("name") or field.get("field_name") or field.get("key") or "unknown"
    label = field.get("label") or name
    field_type = field.get("type") or field.get("field_type") or "string"
    required = field.get("required", False)
    return f"- {name}: {label} ({field_type}){' required' if required else ''}"


def _normalize_value(value: Any, field_type: str):
    if value is None:
        return None
    if field_type == "number":
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                if "." in value:
                    return float(value)
                return int(value)
            except ValueError:
                return value.strip()
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "y", "1"}:
                return True
            if normalized in {"false", "no", "n", "0"}:
                return False
        return value
    return value


async def extract_lead_from_conversation(
    conversation_history: List[Dict[str, str]],
    schema_fields: Union[List[Dict], List[str]],
    extraction_prompt: Optional[str] = None
) -> Dict[str, Any]:
    """Extract lead field values from conversation history using Groq."""
    if not schema_fields:
        logger.info("No schema fields provided to extract_lead_from_conversation")
        return {}

    # Normalise schema fields to a unified dict format
    normalized_schema = _normalize_schema_fields(schema_fields)
    field_descriptions = "\n".join([_format_field_description(field) for field in normalized_schema])

    system_prompt = extraction_prompt or (
        "You are a lead extraction assistant. "
        "Extract the requested fields from the customer's WhatsApp conversation and return a single JSON object. "
        "Only return valid JSON, with field names exactly as given. "
        "If a field is not present or cannot be determined confidently, return null for that field."
    )
    system_prompt = f"{system_prompt}\n\nSchema fields:\n{field_descriptions}\n\nReturn only a JSON object with the requested keys."

    conversation_text = []
    for message in conversation_history:
        speaker = message.get("role", "user")
        text = message.get("text", "")
        if speaker == "assistant":
            conversation_text.append(f"Agent: {text}")
        else:
            conversation_text.append(f"Customer: {text}")
    user_prompt = (
        "Here is the last part of a WhatsApp conversation. Extract the values from this conversation.\n\n"
        + "\n".join(conversation_text[-10:])
        + "\n\nRespond with only valid JSON."
    )

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        choice = response.choices[0]
        message = getattr(choice, "message", None)
        if not message:
            logger.warning("Lead extractor received no message from Groq response")
            return {}

        content = getattr(message, "content", None)
        if isinstance(content, dict):
            extracted = content
        elif isinstance(content, str):
            extracted = json.loads(content.strip()) if content.strip() else {}
        else:
            logger.warning("Unexpected Groq content type in lead extractor")
            return {}

        if not isinstance(extracted, dict):
            logger.warning("Lead extractor response is not a dict")
            return {}

        normalized: Dict[str, Any] = {}
        for field in normalized_schema:
            name = field.get("name") or field.get("field_name") or field.get("key")
            if not name:
                continue
            field_type = field.get("type") or field.get("field_type") or "string"
            if name in extracted:
                normalized[name] = _normalize_value(extracted[name], field_type)
            elif field.get("required") and name:
                normalized[name] = None

        # Return only fields that have a non‑null, non‑empty value
        return {k: v for k, v in normalized.items() if v is not None and v != ""} or {}

    except Exception as e:
        logger.error(f"Lead extraction failed: {e}", exc_info=True)
        return {}