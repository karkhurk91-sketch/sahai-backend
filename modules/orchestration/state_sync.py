# modules/orchestration/state_sync.py
import logging
from typing import Dict, Any
from .cache_manager import CacheManager
from modules.websocket import ConnectionManager, StateUpdate

logger = logging.getLogger(__name__)

class StateSynchronizer:
    def __init__(self, cache: CacheManager, ws_manager: ConnectionManager):
        self.cache = cache
        self.ws = ws_manager
    
    async def sync_state(self, conversation_id: str, org_id: str, new_state: Dict[str, Any]) -> None:
        await self.cache.set_conversation_state(conversation_id, new_state)
        update = StateUpdate(update_type="conversation_state", entity_id=conversation_id, data=new_state)
        await self.ws_manager.broadcast_state_update(org_id, update)
        # Also broadcast individual field completions for UI to update incrementally
        if "completed_fields" in new_state and "completed_fields" in self._previous_state:
            for field, value in new_state["completed_fields"].items():
                if field not in self._previous_state.get("completed_fields", {}):
                    field_update = StateUpdate(update_type="field_completed", entity_id=conversation_id, data={field: value})
                    await self.ws_manager.broadcast_state_update(org_id, field_update)