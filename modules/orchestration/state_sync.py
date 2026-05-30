import logging
from typing import Dict, Any
from modules.orchestration.cache_manager import CacheManager
from modules.websocket import ConnectionManager, StateUpdate

logger = logging.getLogger(__name__)

class StateSynchronizer:
    def __init__(self, cache: CacheManager, ws_manager: ConnectionManager):
        self.cache = cache
        self.ws_manager = ws_manager

    async def sync_state(self, conversation_id: str, org_id: str, new_state: Dict[str, Any]) -> None:
        """Update cache and broadcast full state."""
        await self.cache.set_conversation_state(conversation_id, new_state)
        update = StateUpdate(update_type="conversation_state", entity_id=conversation_id, data=new_state)
        await self.ws_manager.broadcast_state_update(org_id, update)

    async def broadcast_new_message(self, conversation_id: str, org_id: str, message_data: dict) -> None:
        """Broadcast a new message to the frontend."""
        update = StateUpdate(update_type="new_message", entity_id=conversation_id, data=message_data)
        await self.ws_manager.broadcast_state_update(org_id, update)