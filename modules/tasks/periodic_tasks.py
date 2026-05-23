from celery import shared_task
from modules.leads.scoring_engine import rescore_all_active_leads
from modules.leads.nurturing_engine import run_due_nurturing_steps

@shared_task
def rescore_leads_task():
    asyncio.run(rescore_all_active_leads())

@shared_task
def run_nurturing_task():
    asyncio.run(run_due_nurturing_steps())