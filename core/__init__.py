"""Core application infrastructure and patterns"""

from .service_layer import BaseService
from .repository import BaseRepository
from .websocket_manager import WebSocketManager, ConnectionManager
from .event_bus import EventBus
#from .dependency_injection import DIContainer

__all__ = [
    "BaseService",
    "BaseRepository",
    "WebSocketManager",
    "ConnectionManager",
    "EventBus",
#    "DIContainer",
]
