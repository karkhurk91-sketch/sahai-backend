# modules/channels/email.py
import aiosmtplib
from email.mime.text import MIMEText
from .base import ChannelAdapter

class EmailAdapter(ChannelAdapter):
    async def send(self, recipient: str, message: dict) -> str:
        msg = MIMEText(message["content"])
        msg["Subject"] = message.get("subject", "Message from SahAI")
        msg["From"] = self.config["smtp_user"]
        msg["To"] = recipient
        async with aiosmtplib.SMTP(
            hostname=self.config["smtp_host"],
            port=self.config["smtp_port"],
            use_tls=True
        ) as smtp:
            await smtp.login(self.config["smtp_user"], self.config["smtp_password"])
            await smtp.send_message(msg)
        return "email_sent"

    async def handle_webhook(self, request):
        raise NotImplementedError("Use IMAP polling for incoming emails.")

    def get_webhook_path(self) -> str:
        return None