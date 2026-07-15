import json
import asyncio
from typing import Dict, List, Set
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
        # NEW: Map conversation_id -> set of WebSocket connections (for rooms)
        self.rooms: Dict[str, Set[WebSocket]] = {}

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
        # Also remove from any room
        for room in list(self.rooms.keys()):
            if websocket in self.rooms[room]:
                self.rooms[room].discard(websocket)
                if not self.rooms[room]:
                    del self.rooms[room]

    # ---------- Room subscription ----------
    def subscribe_to_room(self, websocket: WebSocket, room_id: str):
        """Add a WebSocket to a conversation room."""
        if room_id not in self.rooms:
            self.rooms[room_id] = set()
        self.rooms[room_id].add(websocket)

    def unsubscribe_from_room(self, websocket: WebSocket, room_id: str):
        """Remove a WebSocket from a conversation room."""
        if room_id in self.rooms:
            self.rooms[room_id].discard(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    # ---------- Broadcast to room ----------
    async def broadcast_to_room(self, message: dict, room_id: str):
        """Broadcast a message to all WebSocket connections in a specific room."""
        if room_id in self.rooms:
            for connection in self.rooms[room_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception as e:
                    # Log error but don't break the loop
                    pass

    # ---------- Original broadcast methods ----------
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

    async def send_typing_start(self, org_id: str, conversation_id: str, agent_name: str = "Agent"):
        await self.broadcast_state_update(org_id, StateUpdate(
            update_type="typing_start",
            entity_id=conversation_id,
            data={"agent_name": agent_name}
        ))

    async def send_typing_stop(self, org_id: str, conversation_id: str):
        await self.broadcast_state_update(org_id, StateUpdate(
            update_type="typing_stop",
            entity_id=conversation_id,
            data={}
        ))

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

    # ====== NEW: Pin update broadcasting ======
    async def broadcast_pin_update(self, conversation_id: str, pins: list):
        """Broadcast a pin_updated event to all users in the conversation room."""
        message = {
            "type": "pin_updated",
            "conversation_id": conversation_id,
            "pins": pins
        }
        await self.broadcast_to_room(message, room_id=conversation_id)


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