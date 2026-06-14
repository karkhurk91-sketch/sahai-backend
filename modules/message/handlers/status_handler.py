from datetime import datetime, timezone
from sqlalchemy import update
from modules.common.models import Message
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def process_status_updates(value: dict, db):
    if "statuses" not in value:
        return
    for status_data in value["statuses"]:
        wamid = status_data.get("id")
        status = status_data.get("status")
        if not wamid:
            continue
        status_timestamp = status_data.get("timestamp")
        if status_timestamp:
            try:
                status_ts_int = int(status_timestamp)
                status_updated_at = datetime.fromtimestamp(status_ts_int, tz=timezone.utc)
            except (TypeError, ValueError):
                status_updated_at = datetime.now(timezone.utc)
        else:
            status_updated_at = datetime.now(timezone.utc)
        errors = status_data.get("errors")
        if status == "failed" and errors:
            logger.error(f"Message {wamid} failed: {errors}")
        stmt = update(Message).where(Message.whatsapp_message_id == wamid).values(
            status=status,
            status_updated_at=status_updated_at
        )
        await db.execute(stmt)
        await db.commit()
        logger.info(f"Updated message {wamid} status to {status} at {status_updated_at}")
