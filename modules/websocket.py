from fastapi import WebSocket
from typing import List
import asyncio

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

    def broadcast_message_update(self, message_data: dict):
        """Broadcast message update (creation or status change) to all connected clients."""
        asyncio.create_task(self.broadcast({
            "type": "message_event",
            **message_data
        }))

manager = ConnectionManager()

def send_alert(lead_id: int, lead_name: str, probability: float):
    # This runs from non-async context; we need to run in background
    asyncio.create_task(manager.broadcast({
        "type": "high_score_lead",
        "lead_id": lead_id,
        "name": lead_name,
        "probability": probability
    }))