import httpx
from modules.message.sender import get_whatsapp_config, WhatsAppService
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def send_whatsapp_media(to_number: str, media: dict, org_id: str) -> tuple:
    config = await get_whatsapp_config(org_id)
    if not config:
        logger.error(f"No WhatsApp config for org {org_id}")
        return False, None
    wa = WhatsAppService(config['access_token'], config['phone_number_id'])
    media_type = media.get("type")
    url = media.get("url")
    caption = media.get("caption", "")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": media_type,
        media_type: {"link": url, "caption": caption[:1024] if caption else None}
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v18.0/{wa.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {wa.access_token}"},
            json=payload
        )
        if resp.status_code == 201:
            data = resp.json()
            wamid = data.get("messages", [{}])[0].get("id")
            return True, wamid
        else:
            logger.error(f"Media send failed: {resp.status_code} {resp.text}")
            return False, None

async def send_whatsapp_interactive(to_number: str, question: str, options: list, org_id: str) -> tuple:
    config = await get_whatsapp_config(org_id)
    if not config:
        logger.error(f"No WhatsApp config for org {org_id}")
        return False, None
    wa = WhatsAppService(config['access_token'], config['phone_number_id'])
    if len(options) <= 3:
        buttons = [{"type": "reply", "reply": {"id": opt["id"], "title": opt["title"][:20]}} for opt in options]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": question[:1024]},
                "action": {"buttons": buttons}
            }
        }
    else:
        rows = [{"id": opt["id"], "title": opt["title"][:24], "description": opt.get("description", "")[:60]} for opt in options]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": question[:1024]},
                "action": {
                    "button": "Select",
                    "sections": [{"title": "Options", "rows": rows}]
                }
            }
        }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v18.0/{wa.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {wa.access_token}"},
            json=payload
        )
        if resp.status_code == 201:
            data = resp.json()
            wamid = data.get("messages", [{}])[0].get("id")
            return True, wamid
        else:
            logger.error(f"Interactive send failed: {resp.status_code} {resp.text}")
            return False, None
