# modules/websocket.py
import json
import asyncio
from typing import Dict, List
from fastapi import WebSocket
from dataclasses import dataclass
from datetime import datetime

@dataclass
class StateUpdate:
    update_type: str
    entity_id: str
    data: Dict
    timestamp: datetime = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow()

    def to_dict(self):
        return {
            "type": self.update_type,
            "entity_id": self.entity_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }


class ConnectionManager:
    def __init__(self):
        # Map organisation_id -> list of WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, org_id: str, websocket: WebSocket):
        """Accept WebSocket and store by organisation ID."""
        await websocket.accept()
        if org_id not in self.active_connections:
            self.active_connections[org_id] = []
        self.active_connections[org_id].append(websocket)

    def disconnect(self, org_id: str, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if org_id in self.active_connections:
            try:
                self.active_connections[org_id].remove(websocket)
                if not self.active_connections[org_id]:
                    del self.active_connections[org_id]
            except ValueError:
                pass

    async def broadcast_state_update(self, org_id: str, update: StateUpdate):
        """Send a state update to all connections of an organisation."""
        if org_id not in self.active_connections:
            return
        message = json.dumps(update.to_dict())
        for connection in self.active_connections[org_id]:
            try:
                await connection.send_text(message)
            except:
                pass

    # --- Typing indicator methods (NEW) ---
    async def send_typing_start(self, org_id: str, conversation_id: str, agent_name: str = "Agent"):
        """Notify that an agent/AI is typing in a conversation."""
        await self.broadcast_state_update(org_id, StateUpdate(
            update_type="typing_start",
            entity_id=conversation_id,
            data={"agent_name": agent_name}
        ))

    async def send_typing_stop(self, org_id: str, conversation_id: str):
        """Notify that typing has stopped."""
        await self.broadcast_state_update(org_id, StateUpdate(
            update_type="typing_stop",
            entity_id=conversation_id,
            data={}
        ))

    # --- Existing broadcast methods (kept unchanged) ---
    async def broadcast(self, message: dict):
        """Broadcast a raw JSON message to all connected clients."""
        for org_id, connections in self.active_connections.items():
            for conn in connections:
                try:
                    await conn.send_json(message)
                except:
                    pass

    def broadcast_message_update(self, message_data: dict):
        """Legacy method: broadcast message events to all clients."""
        asyncio.create_task(self.broadcast({
            "type": "message_event",
            **message_data
        }))


# Global manager instance
manager = ConnectionManager()

def send_alert(lead_id: int, lead_name: str, probability: float):
    """Send high‑score lead alert (non‑async safe)."""
    asyncio.create_task(manager.broadcast({
        "type": "high_score_lead",
        "lead_id": lead_id,
        "name": lead_name,
        "probability": probability
    }))