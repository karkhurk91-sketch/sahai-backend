# modules/channels/factory.py
from .whatsapp import WhatsAppAdapter
from .facebook import FacebookAdapter
from .telegram import TelegramAdapter
from .email import EmailAdapter

class ChannelFactory:
    @staticmethod
    def get_adapter(channel: str, org_id: str, config: dict):
        if channel == "whatsapp":
            return WhatsAppAdapter(org_id, config)
        if channel == "facebook":
            return FacebookAdapter(org_id, config)
        if channel == "telegram":
            return TelegramAdapter(org_id, config)
        if channel == "email":
            return EmailAdapter(org_id, config)
        raise ValueError(f"Unsupported channel: {channel}")