"""WebSocket management for real-time communication"""

import asyncio
import json
import logging
from typing import Dict, Set, Callable, Any, Optional
from uuid import UUID
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """WebSocket event types"""
    MESSAGE = "message"
    TYPING = "typing"
    STATUS = "status"
    PRESENCE = "presence"
    ASSIGNMENT = "assignment"
    NOTE_CREATED = "note_created"
    TAG_ADDED = "tag_added"
    TAG_REMOVED = "tag_removed"
    ERROR = "error"


class ConnectionManager:
    """Manages WebSocket connections per conversation"""
    
    def __init__(self):
        # Structure: {conversation_id: {connection_id: websocket}}
        self.active_connections: Dict[UUID, Dict[str, Any]] = {}
        # Structure: {connection_id: (conversation_id, user_id, org_id)}
        self.connection_metadata: Dict[str, tuple] = {}
        self.logger = logging.getLogger(__name__)
    
    async def connect(
        self,
        conversation_id: UUID,
        connection_id: str,
        websocket: Any,
        user_id: UUID,
        org_id: UUID
    ) -> None:
        """
        Register new WebSocket connection
        
        Args:
            conversation_id: Conversation ID
            connection_id: Unique connection identifier
            websocket: WebSocket connection object
            user_id: User ID
            org_id: Organization ID
        """
        if conversation_id not in self.active_connections:
            self.active_connections[conversation_id] = {}
        
        self.active_connections[conversation_id][connection_id] = {
            "websocket": websocket,
            "user_id": user_id,
            "org_id": org_id,
            "connected_at": datetime.now()
        }
        
        self.connection_metadata[connection_id] = (conversation_id, user_id, org_id)
        
        self.logger.info(
            "websocket_connected",
            connection_id=connection_id,
            conversation_id=str(conversation_id),
            user_id=str(user_id)
        )
    
    async def disconnect(self, conversation_id: UUID, connection_id: str) -> None:
        """
        Remove WebSocket connection
        
        Args:
            conversation_id: Conversation ID
            connection_id: Connection ID to remove
        """
        if conversation_id in self.active_connections:
            self.active_connections[conversation_id].pop(connection_id, None)
            
            if not self.active_connections[conversation_id]:
                del self.active_connections[conversation_id]
        
        self.connection_metadata.pop(connection_id, None)
        
        self.logger.info(
            "websocket_disconnected",
            connection_id=connection_id,
            conversation_id=str(conversation_id)
        )
    
    async def broadcast_to_conversation(
        self,
        conversation_id: UUID,
        message: dict,
        exclude_connection: Optional[str] = None
    ) -> None:
        """
        Broadcast message to all connected clients in conversation
        
        Args:
            conversation_id: Target conversation
            message: Message to send
            exclude_connection: Optional connection ID to exclude
        """
        if conversation_id not in self.active_connections:
            return
        
        disconnected = []
        for conn_id, conn_data in self.active_connections[conversation_id].items():
            if exclude_connection and conn_id == exclude_connection:
                continue
            
            try:
                await conn_data["websocket"].send_json(message)
            except Exception as e:
                self.logger.error(
                    "broadcast_error",
                    connection_id=conn_id,
                    error=str(e)
                )
                disconnected.append(conn_id)
        
        # Clean up disconnected
        for conn_id in disconnected:
            await self.disconnect(conversation_id, conn_id)
    
    async def broadcast_to_org(
        self,
        org_id: UUID,
        message: dict,
        exclude_user: Optional[UUID] = None
    ) -> None:
        """
        Broadcast message to all users in organization
        
        Args:
            org_id: Organization ID
            message: Message to send
            exclude_user: Optional user ID to exclude
        """
        for conv_id, connections in self.active_connections.items():
            for conn_data in connections.values():
                if conn_data["org_id"] != org_id:
                    continue
                
                if exclude_user and conn_data["user_id"] == exclude_user:
                    continue
                
                try:
                    await conn_data["websocket"].send_json(message)
                except Exception as e:
                    self.logger.error("broadcast_to_org_error", error=str(e))
    
    def get_conversation_connections(self, conversation_id: UUID) -> Dict[str, Any]:
        """Get all connections for conversation"""
        return self.active_connections.get(conversation_id, {})
    
    def get_connection_count(self, conversation_id: UUID) -> int:
        """Get number of active connections in conversation"""
        return len(self.get_conversation_connections(conversation_id))


class WebSocketManager:
    """Higher-level WebSocket event management"""
    
    def __init__(self, connection_manager: ConnectionManager):
        self.connections = connection_manager
        self.event_handlers: Dict[EventType, Set[Callable]] = {
            event_type: set() for event_type in EventType
        }
        self.logger = logging.getLogger(__name__)
    
    def register_handler(self, event_type: EventType, handler: Callable) -> None:
        """Register event handler"""
        self.event_handlers[event_type].add(handler)
    
    def unregister_handler(self, event_type: EventType, handler: Callable) -> None:
        """Unregister event handler"""
        self.event_handlers[event_type].discard(handler)
    
    async def emit_event(
        self,
        event_type: EventType,
        conversation_id: UUID,
        data: dict,
        exclude_connection: Optional[str] = None
    ) -> None:
        """
        Emit event to conversation
        
        Args:
            event_type: Type of event
            conversation_id: Target conversation
            data: Event payload
            exclude_connection: Optional connection to exclude
        """
        message = {
            "type": event_type.value,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        # Broadcast to connected clients
        await self.connections.broadcast_to_conversation(
            conversation_id,
            message,
            exclude_connection=exclude_connection
        )
        
        # Call registered handlers
        tasks = [
            handler(conversation_id, data)
            for handler in self.event_handlers[event_type]
        ]
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def send_message_event(
        self,
        conversation_id: UUID,
        message: dict
    ) -> None:
        """Send message event"""
        await self.emit_event(
            EventType.MESSAGE,
            conversation_id,
            message
        )
    
    async def send_typing_indicator(
        self,
        conversation_id: UUID,
        user_id: UUID,
        user_name: str,
        exclude_connection: Optional[str] = None
    ) -> None:
        """Send typing indicator"""
        await self.emit_event(
            EventType.TYPING,
            conversation_id,
            {
                "user_id": str(user_id),
                "user_name": user_name
            },
            exclude_connection=exclude_connection
        )
    
    async def send_presence_update(
        self,
        conversation_id: UUID,
        org_id: UUID,
        status: str
    ) -> None:
        """Send presence/online status update"""
        await self.connections.broadcast_to_org(
            org_id,
            {
                "type": EventType.PRESENCE.value,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "conversation_id": str(conversation_id),
                    "status": status,
                    "active_connections": self.connections.get_connection_count(conversation_id)
                }
            }
        )
    
    async def send_assignment_update(
        self,
        conversation_id: UUID,
        org_id: UUID,
        assigned_to: Optional[dict]
    ) -> None:
        """Notify of conversation assignment change"""
        await self.connections.broadcast_to_org(
            org_id,
            {
                "type": EventType.ASSIGNMENT.value,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "conversation_id": str(conversation_id),
                    "assigned_to": assigned_to
                }
            }
        )
    
    async def send_error(
        self,
        conversation_id: UUID,
        error_code: str,
        error_message: str
    ) -> None:
        """Send error event"""
        await self.emit_event(
            EventType.ERROR,
            conversation_id,
            {
                "error_code": error_code,
                "error_message": error_message
            }
        )


class WebSocketEventBuilder:
    """Helper for building WebSocket events"""
    
    @staticmethod
    def message_event(
        message_id: UUID,
        conversation_id: UUID,
        content: str,
        sender_id: UUID,
        sender_name: str,
        message_type: str = "text",
        media_url: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ) -> dict:
        """Build message event payload"""
        return {
            "type": EventType.MESSAGE.value,
            "timestamp": (timestamp or datetime.now()).isoformat(),
            "data": {
                "message_id": str(message_id),
                "conversation_id": str(conversation_id),
                "content": content,
                "sender_id": str(sender_id),
                "sender_name": sender_name,
                "message_type": message_type,
                "media_url": media_url
            }
        }
    
    @staticmethod
    def typing_event(
        user_id: UUID,
        user_name: str,
        conversation_id: UUID
    ) -> dict:
        """Build typing indicator event"""
        return {
            "type": EventType.TYPING.value,
            "timestamp": datetime.now().isoformat(),
            "data": {
                "user_id": str(user_id),
                "user_name": user_name,
                "conversation_id": str(conversation_id)
            }
        }
    
    @staticmethod
    def delivery_status_event(
        message_id: UUID,
        status: str,
        delivery_time: Optional[datetime] = None
    ) -> dict:
        """Build message delivery status event"""
        return {
            "type": EventType.STATUS.value,
            "timestamp": datetime.now().isoformat(),
            "data": {
                "message_id": str(message_id),
                "status": status,
                "delivered_at": (delivery_time or datetime.now()).isoformat()
            }
        }
