from langchain.tools import tool

@tool
def add_lead_to_crm(name: str, phone: str, interest: str) -> str:
    """Add a lead to the client's CRM system."""
    return f"Lead {name} ({phone}) interested in {interest} has been added to CRM."

@tool
def check_appointment_slots(date: str) -> str:
    """Check available appointment slots on a given date."""
    return f"Available slots on {date}: 10:00 AM, 2:00 PM, 4:00 PM."

available_tools = [add_lead_to_crm, check_appointment_slots]
