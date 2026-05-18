import httpx
from sqlalchemy import text
from modules.channels.factory import ChannelFactory
from modules.common.database import sync_engine
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def send_message(org_id: str, channel: str, recipient: str, message: dict):
    """
    Send a message using the appropriate channel adapter.
    """
    # Fetch channel configuration
    with sync_engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT config
                FROM organization_channels
                WHERE organization_id = :org_id
                AND channel_type = :channel
                AND enabled = true
            """),
            {"org_id": org_id, "channel": channel}
        ).fetchone()

    if not row:
        raise ValueError(f"Channel {channel} not enabled for organization {org_id}")

    config = row.config
    adapter = ChannelFactory.get_adapter(channel, org_id, config)
    msg_id = await adapter.send(recipient, message)
    return msg_id