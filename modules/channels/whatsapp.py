# modules/channels/whatsapp.py
from .base import ChannelAdapter

class WhatsAppAdapter(ChannelAdapter):
    async def send(self, recipient: str, message: dict) -> str:
        # Your existing WhatsApp sending logic
        # For now, raise NotImplementedError
        raise NotImplementedError("WhatsApp adapter should use existing sender.py")
    async def handle_webhook(self, request) -> dict:
        raise NotImplementedError("Webhook handled elsewhere")
    def get_webhook_path(self) -> str:
        return "/webhooks/whatsapp"