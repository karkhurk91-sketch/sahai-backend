# modules/channels/base.py
from abc import ABC, abstractmethod

class ChannelAdapter(ABC):
    def __init__(self, org_id: str, config: dict):
        self.org_id = org_id
        self.config = config

    @abstractmethod
    async def send(self, recipient: str, message: dict) -> str:
        """Send message → return external message ID."""
        pass

    @abstractmethod
    async def handle_webhook(self, request) -> dict:
        """Convert external webhook payload to internal format."""
        pass

    @abstractmethod
    def get_webhook_path(self) -> str:
        """Return unique URL path for this channel's webhook."""
        pass