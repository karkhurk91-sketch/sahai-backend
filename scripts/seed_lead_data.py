#!/usr/bin/env python3
"""
Seed lead schemas and nurturing sequences for a specific organization.
Usage: python scripts/seed_lead_data.py
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

# Add parent directory to path so that modules can be imported
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in environment or .env file")

# Import models (adjust import path based on your project structure)
from modules.common.models import LeadSchema, LeadNurturingSequence, LeadNurturingStep, User, Organization

# ------------------------------------------------------------
# Data Definitions (same as before)
# ------------------------------------------------------------

INDUSTRIES = [
    {
        "name": "real_estate",
        "schema_fields": [
            {"key": "property_type", "label": "Property Type", "type": "string", "required": True},
            {"key": "budget_range", "label": "Budget Range", "type": "string"},
            {"key": "location", "label": "Location", "type": "string", "required": True},
            {"key": "timeline", "label": "Timeline", "type": "string"},
            {"key": "bedrooms", "label": "Bedrooms", "type": "number"},
            {"key": "urgency", "label": "Urgency", "type": "string"}
        ],
        "extraction_prompt": "Extract property requirements from WhatsApp messages. For urgency, set to 'high' if words like 'urgent', 'asap', 'immediately' are present."
    },
    {
        "name": "banking_personal_loan",
        "schema_fields": [
            {"key": "loan_type", "label": "Loan Type", "type": "string", "required": True},
            {"key": "loan_amount", "label": "Loan Amount", "type": "number"},
            {"key": "employment_type", "label": "Employment Type", "type": "string"},
            {"key": "annual_income", "label": "Annual Income", "type": "number"},
            {"key": "urgency", "label": "Urgency", "type": "string"}
        ],
        "extraction_prompt": "Extract loan requirements. Loan type can be 'personal', 'home', 'car', 'business'. Employment type: 'salaried', 'self-employed', 'business'."
    },
    {
        "name": "ecommerce_lead",
        "schema_fields": [
            {"key": "product_category", "label": "Product Category", "type": "string"},
            {"key": "product_name", "label": "Product Name", "type": "string"},
            {"key": "budget", "label": "Budget", "type": "string"},
            {"key": "quantity", "label": "Quantity", "type": "number"},
            {"key": "urgency", "label": "Urgency", "type": "string"}
        ],
        "extraction_prompt": "Extract product details from shopping‑related queries. Identify product name, category, desired quantity, and budget."
    },
    {
        "name": "insurance_health",
        "schema_fields": [
            {"key": "policy_type", "label": "Policy Type", "type": "string"},
            {"key": "coverage_amount", "label": "Coverage Amount", "type": "string"},
            {"key": "age", "label": "Age", "type": "number"},
            {"key": "existing_policies", "label": "Existing Policies", "type": "string"},
            {"key": "urgency", "label": "Urgency", "type": "string"}
        ],
        "extraction_prompt": "Extract insurance requirements. Policy type: health, life, motor, travel."
    },
    {
        "name": "healthcare_clinic",
        "schema_fields": [
            {"key": "symptom", "label": "Symptom", "type": "string"},
            {"key": "preferred_specialist", "label": "Preferred Specialist", "type": "string"},
            {"key": "appointment_date", "label": "Appointment Date", "type": "string"},
            {"key": "insurance_provider", "label": "Insurance Provider", "type": "string"},
            {"key": "urgency", "label": "Urgency", "type": "string"}
        ],
        "extraction_prompt": "Extract appointment or consultation requests. Identify symptom, desired specialist, and preferred date."
    },
    {
        "name": "coaching_education",
        "schema_fields": [
            {"key": "course_interest", "label": "Course Interest", "type": "string"},
            {"key": "budget", "label": "Budget", "type": "string"},
            {"key": "preferred_timeline", "label": "Preferred Timeline", "type": "string"},
            {"key": "qualification", "label": "Qualification", "type": "string"},
            {"key": "urgency", "label": "Urgency", "type": "string"}
        ],
        "extraction_prompt": "Extract course enrolment intent. Identify course name, budget, preferred start date, and educational background."
    }
]

SEQUENCES = [
    {
        "name": "Real Estate Follow‑up",
        "steps": [
            {"step_order": 1, "delay_days": 0, "custom_message": "Thank you for your interest in properties! Would you like to receive photos of available options in your preferred location?"},
            {"step_order": 2, "delay_days": 2, "condition": {"field": "lead_stage", "operator": "==", "value": "new"}, "custom_message": "We have a new listing that matches your criteria. Click here to see details: [link]"},
            {"step_order": 3, "delay_days": 5, "condition": {"field": "lead_score", "operator": ">", "value": 60}, "custom_message": "Would you like to schedule a site visit this weekend? Reply with YES to confirm."},
            {"step_order": 4, "delay_days": 10, "condition": {"field": "lead_stage", "operator": "==", "value": "new"}, "custom_message": "Last chance! We have a special discount for the property you liked. Call us now to book."}
        ]
    },
    {
        "name": "Personal Loan Follow‑up",
        "steps": [
            {"step_order": 1, "delay_days": 0, "custom_message": "Thank you for your loan enquiry. We will check your eligibility and get back to you shortly."},
            {"step_order": 2, "delay_days": 1, "custom_message": "To proceed, please share your PAN card and last 3 months' bank statements (PDF)."},
            {"step_order": 3, "delay_days": 4, "condition": {"field": "lead_score", "operator": ">", "value": 70}, "custom_message": "Congratulations! You are pre‑approved for a loan of up to ₹10 lakh. Click here to complete the application."},
            {"step_order": 4, "delay_days": 7, "condition": {"field": "lead_stage", "operator": "==", "value": "contacted"}, "custom_message": "Don't miss out! Our special loan offer ends this week. Apply now at 5% interest."}
        ]
    },
    {
        "name": "E‑commerce Follow‑up",
        "steps": [
            {"step_order": 1, "delay_days": 0, "custom_message": "Thanks for your interest! The product you liked is still available. Click here to see it."},
            {"step_order": 2, "delay_days": 1, "condition": {"field": "lead_stage", "operator": "==", "value": "new"}, "custom_message": "Limited stock! Grab your item now with a 10% discount code: SAVE10"},
            {"step_order": 3, "delay_days": 3, "custom_message": "Still thinking? We noticed you haven't completed your purchase. Free shipping on orders above ₹999!"},
            {"step_order": 4, "delay_days": 7, "condition": {"field": "lead_score", "operator": ">", "value": 50}, "custom_message": "Last chance: Use code FINAL20 for 20% off – expires tonight!"}
        ]
    }
]

# ------------------------------------------------------------
# Helper to get organization ID from user email
# ------------------------------------------------------------
async def get_org_id_from_email(email: str, session: AsyncSession) -> UUID:
    """Fetch organization_id from a user's email."""
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User with email '{email}' not found.")
    if not user.organization_id:
        raise ValueError(f"User '{email}' has no organization_id assigned.")
    return user.organization_id

# ------------------------------------------------------------
# Seed functions
# ------------------------------------------------------------
async def seed_lead_schemas(org_id: UUID, session: AsyncSession):
    for industry in INDUSTRIES:
        stmt = select(LeadSchema).where(
            LeadSchema.organization_id == org_id,
            LeadSchema.name == industry["name"]
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Lead schema '{industry['name']}' already exists, skipping.")
            continue
        schema = LeadSchema(
            id=uuid4(),
            organization_id=org_id,
            name=industry["name"],
            schema_fields=industry["schema_fields"],
            extraction_prompt=industry.get("extraction_prompt"),
            is_active=True
        )
        session.add(schema)
        print(f"Added lead schema: {industry['name']}")
    await session.commit()

async def seed_nurturing_sequences(org_id: UUID, session: AsyncSession):
    for seq_data in SEQUENCES:
        stmt = select(LeadNurturingSequence).where(
            LeadNurturingSequence.organization_id == org_id,
            LeadNurturingSequence.name == seq_data["name"]
        )
        result = await session.execute(stmt)
        existing_seq = result.scalar_one_or_none()
        if existing_seq:
            print(f"Nurturing sequence '{seq_data['name']}' already exists, skipping.")
            continue
        sequence = LeadNurturingSequence(
            id=uuid4(),
            organization_id=org_id,
            name=seq_data["name"],
            is_active=True
        )
        session.add(sequence)
        await session.flush()
        for step_data in seq_data["steps"]:
            step = LeadNurturingStep(
                id=uuid4(),
                sequence_id=sequence.id,
                step_order=step_data["step_order"],
                delay_days=step_data["delay_days"],
                custom_message=step_data.get("custom_message"),
                template_id=None,
                condition=step_data.get("condition", {})
            )
            session.add(step)
        print(f"Added nurturing sequence: {seq_data['name']} with {len(seq_data['steps'])} steps")
    await session.commit()

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
async def main():
    print("Starting seed script...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    email = input("Enter user email (e.g., gurukripa@wabot.com): ").strip()
    if not email:
        print("No email provided. Exiting.")
        return

    async with async_session() as session:
        try:
            org_id = await get_org_id_from_email(email, session)
            print(f"Found organization ID: {org_id}")
        except ValueError as e:
            print(f"Error: {e}")
            return

        await seed_lead_schemas(org_id, session)
        await seed_nurturing_sequences(org_id, session)

    print("Seeding completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())