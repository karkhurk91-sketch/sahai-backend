import httpx
import re
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.common.logger import get_logger
from modules.message.sender import get_whatsapp_config, WhatsAppService
from modules.common.models import Customer, OrganizationChannel
from .models import WhatsAppTemplate
from .schemas import TemplateCreate

logger = get_logger(__name__)

class WhatsAppTemplateService:
    def __init__(self, session: AsyncSession, org_id: UUID):
        self.session = session
        self.org_id = org_id

    async def _get_waba_id(self) -> Optional[str]:
        """Fetch WhatsApp Business Account ID from organization channel config or Meta API."""
        stmt = select(OrganizationChannel).where(
            OrganizationChannel.organization_id == self.org_id,
            OrganizationChannel.channel_type == "whatsapp",
            OrganizationChannel.enabled == True
        )
        result = await self.session.execute(stmt)
        channel = result.scalar_one_or_none()
        if not channel:
            logger.error(f"No WhatsApp channel configured for org {self.org_id}")
            return None
        
        waba_id = channel.config.get("business_account_id")
        if waba_id:
            return waba_id
        
        # Try to fetch from Meta API
        try:
            config = await get_whatsapp_config(str(self.org_id))
            if not config:
                logger.error(f"No WhatsApp config for org {self.org_id}")
                return None
            wa = WhatsAppService(config["access_token"], config["phone_number_id"])
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://graph.facebook.com/v22.0/me/whatsapp_business_accounts",
                    headers={"Authorization": f"Bearer {wa.access_token}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("data"):
                        waba_id = data["data"][0]["id"]
                        # Store it back
                        channel.config["business_account_id"] = waba_id
                        await self.session.commit()
                        return waba_id
        except Exception as e:
            logger.error(f"Failed to fetch WABA ID: {e}")
        return None

    async def _get_whatsapp_service(self) -> Optional[WhatsAppService]:
        config = await get_whatsapp_config(str(self.org_id))
        if not config:
            logger.error(f"No WhatsApp config for org {self.org_id}")
            return None
        return WhatsAppService(config["access_token"], config["phone_number_id"])

    async def sync_templates_from_meta(self) -> int:
        """Fetch all templates from Meta and upsert into local database."""
        wa = await self._get_whatsapp_service()
        if not wa:
            raise ValueError("WhatsApp service unavailable")
        waba_id = await self._get_waba_id()
        if not waba_id:
            raise ValueError("WhatsApp Business Account ID not found")
        
        url = f"https://graph.facebook.com/v22.0/{waba_id}/message_templates"
        headers = {"Authorization": f"Bearer {wa.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params={"limit": 100})
            if resp.status_code != 200:
                raise Exception(f"Meta API error: {resp.text}")
            data = resp.json()
        templates = data.get("data", [])
        count = 0
        for t in templates:
            stmt = select(WhatsAppTemplate).where(
                WhatsAppTemplate.organization_id == self.org_id,
                WhatsAppTemplate.meta_template_id == t["id"]
            )
            existing = (await self.session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.status = t.get("status", "pending").lower()
                existing.components = t.get("components", [])
                existing.name = t["name"]
                existing.language = t["language"]
                existing.category = t.get("category", "UTILITY")
            else:
                new_template = WhatsAppTemplate(
                    organization_id=self.org_id,
                    meta_template_id=t["id"],
                    name=t["name"],
                    language=t["language"],
                    category=t.get("category", "UTILITY"),
                    status=t.get("status", "pending").lower(),
                    components=t.get("components", [])
                )
                self.session.add(new_template)
            count += 1
        await self.session.commit()
        logger.info(f"Synced {count} templates from Meta")
        return count

    async def list_local_templates(self, status: Optional[str] = None) -> List[Dict]:
        stmt = select(WhatsAppTemplate).where(WhatsAppTemplate.organization_id == self.org_id)
        if status:
            stmt = stmt.where(WhatsAppTemplate.status == status)
        result = await self.session.execute(stmt)
        templates = result.scalars().all()
        return [{
            "id": str(t.id),
            "meta_template_id": t.meta_template_id,
            "name": t.name,
            "language": t.language,
            "category": t.category,
            "status": t.status,
            "components": t.components,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat() if t.updated_at else None
        } for t in templates]

    async def create_template_in_meta(self, data: TemplateCreate) -> Dict[str, Any]:
        """Create a new template via Meta API and store locally."""
        wa = await self._get_whatsapp_service()
        if not wa:
            raise ValueError("WhatsApp service unavailable")
        waba_id = await self._get_waba_id()
        if not waba_id:
            raise ValueError("WhatsApp Business Account ID not found")
        
        url = f"https://graph.facebook.com/v22.0/{waba_id}/message_templates"
        headers = {"Authorization": f"Bearer {wa.access_token}", "Content-Type": "application/json"}
        payload = data.dict(exclude={"local_name"})
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise Exception(f"Meta API error: {resp.text}")
            result = resp.json()
        template = WhatsAppTemplate(
            organization_id=self.org_id,
            meta_template_id=result["id"],
            name=data.name,
            language=data.language,
            category=data.category,
            status="pending",
            components=[c.dict() for c in data.components]
        )
        self.session.add(template)
        await self.session.commit()
        return result

    # ---------- Dynamic template helpers (supports both named and numeric placeholders) ----------
    def _extract_placeholders(self, text: str) -> List[Tuple[int, str]]:
        """Extract all placeholders from text, returning list of (position_index, placeholder_name)."""
        if not text:
            return []
        matches = re.findall(r'\{\{([^}]+)\}\}', text)
        seen = {}
        result = []
        for placeholder in matches:
            if placeholder not in seen:
                seen[placeholder] = len(seen) + 1
                result.append((seen[placeholder], placeholder))
        return result

    def _build_send_components(self, template_components: List[Dict], values: Dict[str, str]) -> List[Dict]:
        """Build send-time components with parameter_name for named placeholders."""
        send_comps = []
        for comp in template_components:
            comp_type = comp.get("type")
            if comp_type == "HEADER":
                if comp.get("format") == "TEXT":
                    header_text = comp.get("text", "")
                    placeholders = self._extract_placeholders(header_text)
                    params = []
                    for _, placeholder in placeholders:
                        val = values.get(placeholder) or values.get(str(_)) or ""
                        params.append({
                            "type": "text",
                            "parameter_name": placeholder,
                            "text": val
                        })
                    if params:
                        send_comps.append({"type": "header", "parameters": params})
                    else:
                        send_comps.append({"type": "header"})
                else:
                    send_comps.append({"type": "header"})
            elif comp_type == "BODY":
                body_text = comp.get("text", "")
                placeholders = self._extract_placeholders(body_text)
                params = []
                for _, placeholder in placeholders:
                    val = values.get(placeholder) or values.get(str(_)) or ""
                    params.append({
                        "type": "text",
                        "parameter_name": placeholder,
                        "text": val
                    })
                send_comps.append({"type": "body", "parameters": params})
            elif comp_type == "FOOTER":
                send_comps.append({"type": "footer"})
            elif comp_type == "BUTTONS":
                buttons = comp.get("buttons", [])
                for idx, btn in enumerate(buttons):
                    btn_type = btn.get("type")
                    if btn_type == "URL":
                        url = btn.get("url", "")
                        placeholders = self._extract_placeholders(url)
                        params = []
                        for _, placeholder in placeholders:
                            val = values.get(placeholder) or values.get(str(_)) or ""
                            params.append({
                                "type": "text",
                                "parameter_name": placeholder,
                                "text": val
                            })
                        send_comps.append({
                            "type": "button",
                            "sub_type": "url",
                            "index": idx,
                            "parameters": params
                        })
                    elif btn_type == "COPY_CODE":
                        code_val = values.get("1") or values.get("code") or ""
                        send_comps.append({
                            "type": "button",
                            "sub_type": "copy_code",
                            "index": idx,
                            "parameters": [{
                                "type": "text",
                                "parameter_name": "code",
                                "text": code_val
                            }]
                        })
                    elif btn_type == "QUICK_REPLY":
                        send_comps.append({
                            "type": "button",
                            "sub_type": "quick_reply",
                            "index": idx
                        })
                    elif btn_type == "PHONE_NUMBER":
                        send_comps.append({
                            "type": "button",
                            "sub_type": "phone_number",
                            "index": idx
                        })
        return send_comps

    async def get_template_variables(self, template_id: UUID) -> List[Dict]:
        """Return list of variables required for a template (with friendly labels if possible)."""
        stmt = select(WhatsAppTemplate).where(
            WhatsAppTemplate.id == template_id,
            WhatsAppTemplate.organization_id == self.org_id
        )
        result = await self.session.execute(stmt)
        template = result.scalar_one_or_none()
        if not template:
            raise ValueError("Template not found")
        components = template.components
        # Collect all unique placeholder names in order of first appearance
        placeholders = []
        seen = set()
        for comp in components:
            if comp.get("type") == "HEADER" and comp.get("format") == "TEXT":
                for _, ph in self._extract_placeholders(comp.get("text", "")):
                    if ph not in seen:
                        seen.add(ph)
                        placeholders.append(ph)
            elif comp.get("type") == "BODY":
                for _, ph in self._extract_placeholders(comp.get("text", "")):
                    if ph not in seen:
                        seen.add(ph)
                        placeholders.append(ph)
            elif comp.get("type") == "BUTTONS":
                for btn in comp.get("buttons", []):
                    if btn.get("type") == "URL":
                        for _, ph in self._extract_placeholders(btn.get("url", "")):
                            if ph not in seen:
                                seen.add(ph)
                                placeholders.append(ph)
        # Build response: each variable gets a position index (1-based) and its label (the placeholder name)
        return [{"position": i+1, "label": ph, "example": ""} for i, ph in enumerate(placeholders)]

    async def send_template_dynamic(self, template_id: UUID, recipient_ids: List[UUID], values: Dict[str, str]) -> List[Dict]:
        """
        Send a template dynamically using the stored components and user-provided values.
        Uses _build_send_components to construct the correct send payload.
        """
        # Fetch template
        stmt = select(WhatsAppTemplate).where(
            WhatsAppTemplate.id == template_id,
            WhatsAppTemplate.organization_id == self.org_id
        )
        result = await self.session.execute(stmt)
        template = result.scalar_one_or_none()
        if not template:
            raise ValueError("Template not found")
        
        # Build send components
        send_components = self._build_send_components(template.components, values)
        
        # Get WhatsApp service
        wa = await self._get_whatsapp_service()
        if not wa:
            raise ValueError("WhatsApp service unavailable")
        
        # Fetch customers
        cust_stmt = select(Customer).where(
            Customer.id.in_(recipient_ids),
            Customer.organization_id == self.org_id
        )
        customers = (await self.session.execute(cust_stmt)).scalars().all()
        
        results = []
        for cust in customers:
            phone = cust.phone_number
            success, wamid = await wa.send_template_message(
                to_number=phone,
                template_name=template.name,
                language_code=template.language,
                components=send_components
            )
            results.append({"phone": phone, "success": success, "wamid": wamid})
        return results