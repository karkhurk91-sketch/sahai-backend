# modules/channels/telegram.py
import httpx
from .base import ChannelAdapter

class TelegramAdapter(ChannelAdapter):
    async def send(self, recipient: str, message: dict) -> str:
        token = self.config["bot_token"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": recipient, "text": message["content"]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return str(resp.json()["result"]["message_id"])

    async def handle_webhook(self, request) -> dict:
        data = await request.json()
        msg = data.get("message") or data.get("edited_message")
        if not msg:
            return None
        return {
            "channel": "telegram",
            "external_id": str(msg["message_id"]),
            "from": str(msg["from"]["id"]),
            "text": msg.get("text", ""),
            "timestamp": msg["date"],
        }

    def get_webhook_path(self) -> str:
        return "/webhooks/telegram"