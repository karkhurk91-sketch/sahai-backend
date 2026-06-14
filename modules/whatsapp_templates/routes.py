from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import UUID

from modules.common.database import get_db, AsyncSessionLocal
from modules.auth.jwt import get_current_user
from modules.auth.dependencies import require_permission
from modules.common.logger import get_logger
from modules.common.models import Customer
from .models import WhatsAppTemplate
from .schemas import TemplateCreate, SendTemplateDynamicRequest
from .service import WhatsAppTemplateService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/whatsapp/templates", tags=["WhatsApp Templates"], dependencies=[Depends(require_permission("manage_templates"))])

@router.get("/sync")
async def sync_templates(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    service = WhatsAppTemplateService(db, org_id)
    count = await service.sync_templates_from_meta()
    return {"synced": count}

@router.get("/")
async def list_templates(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    service = WhatsAppTemplateService(db, org_id)
    templates = await service.list_local_templates(status)
    return templates

@router.post("/")
async def create_template(
    data: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    service = WhatsAppTemplateService(db, org_id)
    try:
        result = await service.create_template_in_meta(data)
        return {"meta_template_id": result["id"], "status": "pending"}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get("/{template_id}/variables")
async def get_template_variables(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    service = WhatsAppTemplateService(db, org_id)
    try:
        vars = await service.get_template_variables(template_id)
        return {"variables": vars}
    except ValueError as e:
        raise HTTPException(404, str(e))

@router.post("/send")
async def send_template_dynamic(
    request: SendTemplateDynamicRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = UUID(current_user["org_id"])
    service = WhatsAppTemplateService(db, org_id)
    
    # Fetch template
    stmt = select(WhatsAppTemplate).where(
        WhatsAppTemplate.id == request.template_id,
        WhatsAppTemplate.organization_id == org_id
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(404, "Template not found")
    
    # Build send components using the helper method
    try:
        send_components = service._build_send_components(template.components, request.values)
    except Exception as e:
        raise HTTPException(400, f"Invalid values: {str(e)}")
    
    # Define background task that uses its own database session
    async def send_to_all():
        # Create a new session for the background task
        async with AsyncSessionLocal() as new_session:
            # Create a new service instance with the new session
            bg_service = WhatsAppTemplateService(new_session, org_id)
            wa = await bg_service._get_whatsapp_service()
            if not wa:
                logger.error("WhatsApp service not available")
                return
            # Fetch customers within the new session
            cust_stmt = select(Customer).where(
                Customer.id.in_(request.recipient_ids),
                Customer.organization_id == org_id
            )
            customers = (await new_session.execute(cust_stmt)).scalars().all()
            for cust in customers:
                try:
                    # wa.send_template_message must return (bool, str)
                    success, wamid = await wa.send_template_message(
                        to_number=cust.phone_number,
                        template_name=template.name,
                        language_code=template.language,
                        components=send_components
                    )
                    logger.info(f"Sent to {cust.phone_number}: success={success}, wamid={wamid}")
                except Exception as e:
                    logger.error(f"Failed to send to {cust.phone_number}: {e}")
    
    background_tasks.add_task(send_to_all)
    return {"status": "queued", "recipients": len(request.recipient_ids)}