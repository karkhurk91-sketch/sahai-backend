import asyncio
import json
import httpx
from uuid import UUID
from typing import Optional, Tuple, Dict, Any   # added Dict, Any
from sqlalchemy import text
from modules.common.logger import get_logger
from modules.common.database import sync_engine
from concurrent.futures import ThreadPoolExecutor

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


# ---------- Helper: synchronous DB fetch of WhatsApp config ----------
def _get_whatsapp_config_sync(org_id: str):
    with sync_engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT config
                FROM organization_channels
                WHERE organization_id = :org_id
                  AND channel_type = 'whatsapp'
                  AND enabled = TRUE
                LIMIT 1
            """),
            {"org_id": org_id}
        )
        row = result.fetchone()
        if not row:
            return None
        config_data = row[0]
        if isinstance(config_data, bytes):
            config_data = config_data.decode('utf-8')
        if isinstance(config_data, str):
            config = json.loads(config_data)
        else:
            config = config_data
        return config


async def get_whatsapp_config(org_id: str):
    """Fetch WhatsApp credentials for an organization."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _get_whatsapp_config_sync, org_id)


# ---------- Message counting ----------
async def increment_message_count(org_id: str, category: str):
    """Increment marketing/utility message count."""
    if not org_id:
        return
    col = "marketing_message_count" if category.upper() == "MARKETING" else "utility_message_count"

    def _update():
        with sync_engine.connect() as conn:
            conn.execute(
                text(f"UPDATE organizations SET {col} = {col} + 1, last_count_reset = CURRENT_DATE WHERE id = :org_id"),
                {"org_id": org_id}
            )
            conn.commit()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _update)


# ---------- WhatsApp Service Class ----------
class WhatsAppService:
    """Service for WhatsApp Cloud API interactions."""

    def __init__(self, access_token: str, phone_number_id: str):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = "v21.0"
        self.base_url = "https://graph.facebook.com"

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an authenticated request to WhatsApp API."""
        url = f"{self.base_url}/{self.api_version}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            if response.status_code not in (200, 201):
                error_detail = response.text
                logger.error(f"WhatsApp API error: {response.status_code} - {error_detail}")
                raise Exception(f"WhatsApp API error: {error_detail}")
            return response.json()

    async def upload_media(self, filename: str, mime_type: str, file_bytes: bytes) -> str:
        # Ensure filename is a string (not bytes)
        if isinstance(filename, bytes):
            filename = filename.decode('utf-8')
        filename = str(filename)
        
        url = f"{self.base_url}/{self.api_version}/{self.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        files = {
            "file": (filename, file_bytes, mime_type),
            "messaging_product": (None, "whatsapp"),
            "type": (None, mime_type),
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, files=files)
            if response.status_code != 200:
                raise Exception(f"WhatsApp upload failed: {response.text}")
            data = response.json()
            media_id = data.get("id")
            if not media_id:
                raise Exception("No 'id' in upload response")  
            return media_id

    async def send_text_message(self, to_number: str, text: str) -> Tuple[bool, Optional[str]]:
        """Send a free‑form text message (only within 24h session). Returns (success, whatsapp_message_id)."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": text}
        }
        try:
            result = await self._request("POST", f"{self.phone_number_id}/messages", json=payload)
            wamid = result.get("messages", [{}])[0].get("id")
            return True, wamid
        except Exception as e:
            logger.error(f"Failed to send text message: {e}")
            return False, None

    async def send_media_message(
        self, to_number: str, media_id: str, media_type: str, caption: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Send a media message (image, video, audio, document)."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": media_type,
            media_type: {"id": media_id}
        }
        if caption and media_type != "audio":
            payload[media_type]["caption"] = caption
        
        try:
            result = await self._request("POST", f"{self.phone_number_id}/messages", json=payload)
            wamid = result.get("messages", [{}])[0].get("id")
            return True, wamid
        except Exception as e:
            logger.error(f"Failed to send media message: {e}")
            return False, None

    async def send_template_message(self, to_number: str, template_name: str, language_code: str, components: list = None) -> tuple[bool, Optional[str]]:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code}
            }
        }
        if components:
            payload["template"]["components"] = components
        try:
            result = await self._request("POST", f"{self.phone_number_id}/messages", json=payload)
            wamid = result.get("messages", [{}])[0].get("id")
            return True, wamid
        except Exception as e:
            logger.error(f"Failed to send template message: {e}")
            return False, None

    async def get_media_url(self, media_id: str) -> Optional[str]:
        """Retrieve the download URL for a media file."""
        try:
            result = await self._request("GET", f"{media_id}")
            return result.get("url")
        except Exception as e:
            logger.error(f"Failed to get media URL for {media_id}: {e}")
            return None


# ---------- Standalone convenience functions (backward compatibility) ----------
async def send_whatsapp_template(
    to_number: str,
    template_name: str,
    language_code: str = "en",
    components: list = None,
    category: str = None,
    org_id: str = None
) -> bool:
    config = await get_whatsapp_config(org_id)
    if not config:
        logger.error(f"No WhatsApp config for org {org_id}")
        return False
    service = WhatsAppService(config["access_token"], config["phone_number_id"])
    return await service.send_template_message(to_number, template_name, language_code, components, category, org_id)


async def send_whatsapp_text(to_number: str, text: str, org_id: str = None) -> Tuple[bool, Optional[str]]:
    config = await get_whatsapp_config(org_id)
    if not config:
        logger.error(f"No WhatsApp config for org {org_id}")
        return False, None
    service = WhatsAppService(config["access_token"], config["phone_number_id"])
    return await service.send_text_message(to_number, text)