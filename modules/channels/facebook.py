# modules/channels/facebook.py
import httpx
from .base import ChannelAdapter

class FacebookAdapter(ChannelAdapter):
    async def send(self, recipient: str, message: dict) -> str:
        token = self.config.get("page_access_token")
        url = "https://graph.facebook.com/v21.0/me/messages"
        payload = {
            "recipient": {"id": recipient},
            "message": {"text": message["content"]},
            "messaging_type": "RESPONSE"
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, params={"access_token": token})
            resp.raise_for_status()
            return resp.json()["message_id"]

    async def handle_webhook(self, request) -> dict:
        data = await request.json()
        for entry in data.get("entry", []):
            for msg in entry.get("messaging", []):
                if "message" in msg and "text" in msg["message"]:
                    return {
                        "channel": "facebook",
                        "external_id": msg["message"]["mid"],
                        "from": msg["sender"]["id"],
                        "text": msg["message"]["text"],
                        "timestamp": entry["time"],
                    }
        return None

    def get_webhook_path(self) -> str:
        return "/webhooks/facebook"