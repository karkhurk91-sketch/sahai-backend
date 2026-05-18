"""Event bus for pub/sub communication between services"""

import asyncio
import logging
from typing import Dict, Set, Callable, Any, Optional
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class EventCategory(str, Enum):
    """Event categories for organization"""
    MESSAGE = "message"
    CONVERSATION = "conversation"
    USER = "user"
    BROADCAST = "broadcast"
    LEAD = "lead"
    CAMPAIGN = "campaign"
    ORGANIZATION = "organization"


@dataclass
class Event:
    """Represents a domain event"""
    category: EventCategory
    action: str  # e.g., "created", "updated", "deleted"
    aggregate_id: str  # ID of affected entity
    aggregate_type: str  # Type of entity (Message, Conversation, etc.)
    organization_id: str
    user_id: Optional[str]
    payload: dict
    timestamp: datetime
    
    @property
    def event_key(self) -> str:
        """Unique event identifier"""
        return f"{self.category.value}.{self.action}"


class EventBus:
    """
    Central event bus for decoupled communication between services
    
    Usage:
        bus = EventBus()
        
        # Subscribe
        @bus.subscribe(EventCategory.MESSAGE, "created")
        async def on_message_created(event: Event):
            await handle_message(event)
        
        # Publish
        await bus.publish(Event(
            category=EventCategory.MESSAGE,
            action="created",
            ...
        ))
    """
    
    def __init__(self):
        self.subscribers: Dict[str, Set[Callable]] = {}
        self.logger = logging.getLogger(__name__)
        self.event_history: list[Event] = []
        self._max_history = 1000
    
    def subscribe(
        self,
        category: EventCategory,
        action: str
    ) -> Callable:
        """
        Decorator to subscribe to events
        
        Args:
            category: Event category
            action: Event action (or "*" for all actions in category)
        
        Returns:
            Decorator function
        """
        def decorator(func: Callable) -> Callable:
            event_key = f"{category.value}.{action}"
            
            if event_key not in self.subscribers:
                self.subscribers[event_key] = set()
            
            self.subscribers[event_key].add(func)
            
            self.logger.info(
                "event_subscriber_registered",
                event_key=event_key,
                handler=func.__name__
            )
            
            return func
        
        return decorator
    
    def unsubscribe(
        self,
        category: EventCategory,
        action: str,
        func: Callable
    ) -> None:
        """Unsubscribe from events"""
        event_key = f"{category.value}.{action}"
        self.subscribers.get(event_key, set()).discard(func)
    
    async def publish(self, event: Event) -> None:
        """
        Publish event to all subscribers
        
        Args:
            event: Event to publish
        """
        # Store in history
        self.event_history.append(event)
        if len(self.event_history) > self._max_history:
            self.event_history.pop(0)
        
        # Get subscribers
        event_key = event.event_key
        subscribers = self.subscribers.get(event_key, set())
        wildcard_key = f"{event.category.value}.*"
        subscribers.update(self.subscribers.get(wildcard_key, set()))
        
        if not subscribers:
            self.logger.debug(
                "event_published_no_subscribers",
                event_key=event_key
            )
            return
        
        self.logger.info(
            "event_published",
            event_key=event_key,
            subscriber_count=len(subscribers)
        )
        
        # Call subscribers in parallel
        tasks = [subscriber(event) for subscriber in subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(
                    "event_subscriber_error",
                    event_key=event_key,
                    error=str(result),
                    subscriber_index=i
                )
    
    async def publish_many(self, events: list[Event]) -> None:
        """Publish multiple events"""
        tasks = [self.publish(event) for event in events]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_history(
        self,
        category: Optional[EventCategory] = None,
        limit: int = 100
    ) -> list[Event]:
        """
        Get event history
        
        Args:
            category: Filter by category (optional)
            limit: Maximum events to return
        
        Returns:
            List of events
        """
        if category:
            events = [e for e in self.event_history if e.category == category]
        else:
            events = self.event_history
        
        return events[-limit:]


class EventFactory:
    """Factory for creating domain events"""
    
    @staticmethod
    def message_created(
        message_id: str,
        conversation_id: str,
        organization_id: str,
        user_id: str,
        content: str,
        message_type: str = "text"
    ) -> Event:
        """Create message created event"""
        return Event(
            category=EventCategory.MESSAGE,
            action="created",
            aggregate_id=message_id,
            aggregate_type="Message",
            organization_id=organization_id,
            user_id=user_id,
            payload={
                "conversation_id": conversation_id,
                "content": content,
                "message_type": message_type
            },
            timestamp=datetime.now()
        )
    
    @staticmethod
    def message_sent(
        message_id: str,
        conversation_id: str,
        organization_id: str,
        whatsapp_message_id: Optional[str] = None
    ) -> Event:
        """Create message sent event"""
        return Event(
            category=EventCategory.MESSAGE,
            action="sent",
            aggregate_id=message_id,
            aggregate_type="Message",
            organization_id=organization_id,
            user_id=None,
            payload={
                "conversation_id": conversation_id,
                "whatsapp_message_id": whatsapp_message_id
            },
            timestamp=datetime.now()
        )
    
    @staticmethod
    def conversation_assigned(
        conversation_id: str,
        organization_id: str,
        assigned_to_user_id: str,
        assigned_by_user_id: Optional[str] = None
    ) -> Event:
        """Create conversation assigned event"""
        return Event(
            category=EventCategory.CONVERSATION,
            action="assigned",
            aggregate_id=conversation_id,
            aggregate_type="Conversation",
            organization_id=organization_id,
            user_id=assigned_by_user_id,
            payload={
                "assigned_to": assigned_to_user_id
            },
            timestamp=datetime.now()
        )
    
    @staticmethod
    def conversation_closed(
        conversation_id: str,
        organization_id: str,
        closed_by_user_id: Optional[str] = None
    ) -> Event:
        """Create conversation closed event"""
        return Event(
            category=EventCategory.CONVERSATION,
            action="closed",
            aggregate_id=conversation_id,
            aggregate_type="Conversation",
            organization_id=organization_id,
            user_id=closed_by_user_id,
            payload={},
            timestamp=datetime.now()
        )
    
    @staticmethod
    def lead_scored(
        lead_id: str,
        organization_id: str,
        score: int,
        reason: str
    ) -> Event:
        """Create lead scored event"""
        return Event(
            category=EventCategory.LEAD,
            action="scored",
            aggregate_id=lead_id,
            aggregate_type="Lead",
            organization_id=organization_id,
            user_id=None,
            payload={
                "score": score,
                "reason": reason
            },
            timestamp=datetime.now()
        )
    
    @staticmethod
    def broadcast_created(
        broadcast_id: str,
        organization_id: str,
        created_by_user_id: str,
        recipient_count: int
    ) -> Event:
        """Create broadcast created event"""
        return Event(
            category=EventCategory.BROADCAST,
            action="created",
            aggregate_id=broadcast_id,
            aggregate_type="Broadcast",
            organization_id=organization_id,
            user_id=created_by_user_id,
            payload={
                "recipient_count": recipient_count
            },
            timestamp=datetime.now()
        )
