import uuid
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert as pg_insert
from modules.common.models import Message
from modules.common.logger import get_logger
from modules.message.services.transcription import transcribe_voice_note
from modules.message.sender import get_whatsapp_config, WhatsAppService

logger = get_logger(__name__)

async def parse_incoming_message(msg_data: dict, value: dict):
    from_number = msg_data["from"]
    timestamp = int(msg_data["timestamp"])
    wamid = msg_data.get("id")
    business_phone_number = value["metadata"]["display_phone_number"]

    msg_type = msg_data.get("type")
    caption = ""
    media_whatsapp_id = None
    media_file_name = None
    media_content_type = None
    content = ""
    message_type = "text"

    if "interactive" in msg_data:
        interactive = msg_data["interactive"]
        if interactive["type"] == "button_reply":
            content = interactive["button_reply"]["id"]
        elif interactive["type"] == "list_reply":
            content = interactive["list_reply"]["id"]
        else:
            content = ""
        message_type = "text"
    else:
        if msg_type == "text":
            content = msg_data["text"]["body"]
            message_type = "text"
        elif msg_type in {"image", "video", "audio", "document"}:
            payload = msg_data.get(msg_type, {}) or {}
            media_whatsapp_id = payload.get("id")
            caption = payload.get("caption") or ""
            media_file_name = payload.get("filename")
            media_content_type = payload.get("mime_type")
            message_type = msg_type
            content = caption or f"{msg_type} attachment"
        else:
            content = msg_data.get("text", {}).get("body") or msg_data.get(msg_type, {}).get("caption") or f"Unsupported message type: {msg_type}"
            message_type = msg_type or "text"

    return {
        "from_number": from_number,
        "timestamp": timestamp,
        "wamid": wamid,
        "business_phone_number": business_phone_number,
        "content": content,
        "message_type": message_type,
        "media_whatsapp_id": media_whatsapp_id,
        "media_file_name": media_file_name,
        "media_content_type": media_content_type,
        "caption": caption,
    }

async def save_incoming_message(db, conv_id, org_id, message_data, media_whatsapp_id=None):
    new_message_id = uuid.uuid4()
    sort_ts = datetime.fromtimestamp(message_data["timestamp"], tz=timezone.utc)
    insert_stmt = pg_insert(Message).values(
        id=new_message_id,
        conversation_id=conv_id,
        organization_id=org_id,
        direction="inbound",
        mode="user",
        content=message_data["content"],
        message_type=message_data["message_type"],
        media_whatsapp_id=media_whatsapp_id,
        media_file_name=message_data.get("media_file_name"),
        media_content_type=message_data.get("media_content_type"),
        media_url=f"/api/conversations/media/{new_message_id}" if media_whatsapp_id else None,
        is_ai_generated=False,
        status="delivered",
        created_at=datetime.now(timezone.utc),
        whatsapp_message_id=message_data["wamid"],
        whatsapp_timestamp=message_data["timestamp"],
        sort_timestamp=sort_ts,
        status_updated_at=datetime.now(timezone.utc)
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=['whatsapp_message_id'],
        set_={
            'status': 'delivered',
            'status_updated_at': datetime.now(timezone.utc),
            'content': message_data["content"],
            'message_type': message_data["message_type"],
            'media_whatsapp_id': media_whatsapp_id,
            'media_file_name': message_data.get("media_file_name"),
            'media_content_type': message_data.get("media_content_type")
        }
    )
    await db.execute(upsert_stmt)
    return new_message_id
