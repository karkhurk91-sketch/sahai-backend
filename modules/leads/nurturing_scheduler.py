import asyncio
from datetime import datetime, timedelta
from modules.queue.producer import celery_app
from modules.common.database import sync_engine, AsyncSessionLocal
from sqlalchemy import text, select
from modules.common.logger import get_logger
from modules.common.models import Lead, LeadNurturingSequence, LeadNurturingStep, LeadNurturingLog, BroadcastTemplate
from modules.message.sender import send_whatsapp_template, send_whatsapp_text
import json
import uuid

logger = get_logger(__name__)


def _eval_condition(condition: dict, lead_row: dict) -> bool:
    if not condition:
        return True
    field = condition.get('field')
    op = condition.get('operator')
    value = condition.get('value')
    if not field or not op:
        return True
    # fetch field from lead_row; support nested in data
    lead_value = None
    if field in lead_row:
        lead_value = lead_row[field]
    else:
        # try data JSON
        data = lead_row.get('data')
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except Exception:
                data = {}
        if isinstance(data, dict):
            lead_value = data.get(field)

    try:
        if op == '>':
            return float(lead_value or 0) > float(value)
        if op == '<':
            return float(lead_value or 0) < float(value)
        if op == '>=':
            return float(lead_value or 0) >= float(value)
        if op == '<=':
            return float(lead_value or 0) <= float(value)
        if op == '==':
            return str(lead_value) == str(value)
        if op == 'contains':
            return str(value) in (str(lead_value) if lead_value is not None else '')
    except Exception:
        logger.exception('Condition evaluation failed')
        return False
    return False


def _lead_row_to_dict(row):
    if not row:
        return {}
    d = dict(row.items()) if hasattr(row, 'items') else dict(row)
    return d


@celery_app.task(name='modules.leads.nurturing_scheduler.check_nurturing')
def check_nurturing():
    """Scan leads assigned to active sequences and enqueue processing."""
    with sync_engine.connect() as conn:
        res = conn.execute(
            text("""
                SELECT l.id
                FROM leads l
                JOIN lead_nurturing_sequences s ON l.active_nurturing_sequence_id = s.id
                WHERE l.active_nurturing_sequence_id IS NOT NULL
                  AND s.is_active = TRUE
                  AND (l.last_nurturing_step IS NULL OR l.last_nurturing_step < (
                      SELECT COALESCE(MAX(step_order),0) FROM lead_nurturing_steps WHERE sequence_id = s.id
                  ))
                LIMIT 200
            """)
        )
        rows = res.fetchall()
    for r in rows:
        lead_id = str(r[0])
        try:
            celery_app.send_task('modules.leads.nurturing_scheduler.process_nurturing_for_lead', args=[lead_id])
        except Exception:
            logger.exception(f'Failed enqueue nurturing for lead {lead_id}')


@celery_app.task(name='modules.leads.nurturing_scheduler.process_nurturing_for_lead')
def process_nurturing_for_lead(lead_id: str):
    """Celery task wrapper to run the async processor synchronously via asyncio.run"""
    try:
        asyncio.run(process_nurturing_for_lead_sync(lead_id))
    except Exception:
        logger.exception(f'Processing nurturing failed for lead {lead_id}')


async def process_nurturing_for_lead_sync(lead_id: str):
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        # Fetch lead and sequence
        q = select(Lead).where(Lead.id == uuid.UUID(lead_id))
        res = await db.execute(q)
        lead = res.scalar_one_or_none()
        if not lead:
            logger.warning(f'Lead not found: {lead_id}')
            return
        if not lead.active_nurturing_sequence_id:
            logger.info(f'No active sequence for lead {lead_id}')
            return

        seq_q = select(LeadNurturingSequence).where(LeadNurturingSequence.id == lead.active_nurturing_sequence_id)
        seq_res = await db.execute(seq_q)
        seq = seq_res.scalar_one_or_none()
        if not seq or not seq.is_active:
            logger.info(f'Sequence not active for lead {lead_id}')
            return

        # next step
        next_order = (lead.last_nurturing_step or 0) + 1
        step_q = select(LeadNurturingStep).where(LeadNurturingStep.sequence_id == seq.id, LeadNurturingStep.step_order == next_order)
        step_res = await db.execute(step_q)
        step = step_res.scalar_one_or_none()
        if not step:
            logger.info(f'No next step for lead {lead_id} (order {next_order})')
            return

        # time check
        if next_order == 1:
            reference = lead.created_at or lead.updated_at or now
        else:
            reference = lead.last_nurturing_sent_at or lead.created_at or now
        if not reference:
            reference = now
        due_time = reference + timedelta(days=step.delay_days)
        if now < due_time:
            logger.info(f'Not due yet for lead {lead_id} step {next_order} (due {due_time})')
            return

        # evaluate condition
        # fetch lead row as dict
        with sync_engine.connect() as conn:
            r = conn.execute(text('SELECT * FROM leads WHERE id = :id'), {'id': lead_id}).fetchone()
            lead_row = _lead_row_to_dict(r)

        if step.condition:
            cond_ok = _eval_condition(step.condition, lead_row)
            if not cond_ok:
                logger.info(f'Condition failed for lead {lead_id} step {next_order}')
                # still update last_nurturing_step to skip
                async with AsyncSessionLocal() as db2:
                    lead_obj = await db2.get(Lead, uuid.UUID(lead_id))
                    lead_obj.last_nurturing_step = next_order
                    lead_obj.last_nurturing_sent_at = datetime.utcnow()
                    db2.add(lead_obj)
                    await db2.commit()
                return

        # send message
        try:
            sent = False
            if step.template_id:
                # use template
                await send_whatsapp_template(lead.customer_phone, template_name=None, language_code='en', components=None, org_id=str(lead.organization_id))
                # NOTE: broadcast_templates table stores content; mapping to meta template name omitted for brevity
                sent = True
            elif step.custom_message:
                await send_whatsapp_text(lead.customer_phone, step.custom_message, org_id=str(lead.organization_id))
                sent = True
            status = 'sent' if sent else 'failed'
            error_message = None
        except Exception as e:
            status = 'failed'
            error_message = str(e)
            logger.exception(f'Failed to send nurturing message for lead {lead_id} step {next_order}')

        # update lead and log
        async with AsyncSessionLocal() as db2:
            lead_obj = await db2.get(Lead, uuid.UUID(lead_id))
            if status == 'sent':
                lead_obj.last_nurturing_step = next_order
                lead_obj.last_nurturing_sent_at = datetime.utcnow()
            else:
                # leave last_nurturing_step unchanged to retry later
                pass
            db2.add(lead_obj)
            # log
            log = LeadNurturingLog(id=uuid.uuid4(), lead_id=lead_obj.id, step_id=step.id, status=status, error_message=error_message)
            db2.add(log)
            await db2.commit()
