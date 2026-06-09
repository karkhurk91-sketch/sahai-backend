#!/usr/bin/env python3
"""
Seed default bot configurations for various industries.
Run once after migrations.
"""

import asyncio
import uuid
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.common.database import AsyncSessionLocal
from modules.common.models import BotConfig, Organization
from sqlalchemy import select
from datetime import datetime

# ========== INDUSTRY CONFIGURATIONS ==========

REAL_ESTATE_CONFIG = {
    "name": "Real Estate Bot",
    "fields": [
        {"name": "intent", "question": "Are you looking to buy or rent?", "type": "button", "required": True, "options": [{"id": "buy", "title": "Buy"}, {"id": "rent", "title": "Rent"}]},
        {"name": "name", "question": "May I know your name?", "type": "text", "required": True},
        {"name": "phone", "question": "Your mobile number?", "type": "text", "validation": {"regex": "^[6-9][0-9]{9}$", "error_message": "Please enter a valid 10-digit mobile number"}},
        {"name": "budget", "question": "What is your budget (in lakhs)?", "type": "text", "required": True},
        {"name": "location", "question": "Preferred location?", "type": "list", "required": True, "options": [{"id": "north", "title": "North"}, {"id": "south", "title": "South"}, {"id": "east", "title": "East"}, {"id": "west", "title": "West"}]},
        {"name": "property_type", "question": "What type of property?", "type": "button", "required": True, "options": [{"id": "apartment", "title": "Apartment"}, {"id": "villa", "title": "Villa"}, {"id": "plot", "title": "Plot"}]}
    ],
    "confirmation": {
        "enabled": True,
        "message": "Please confirm your details for real estate inquiry:",
        "confirm_label": "Confirm",
        "change_label": "Change"
    },
    "lead_action": {
        "type": "create_lead",
        "service": "real_estate"
    }
}

RESTAURANT_CONFIG = {
    "name": "Restaurant Booking Bot",
    "fields": [
        {"name": "name", "question": "Your name?", "type": "text", "required": True},
        {"name": "phone", "question": "Your phone number?", "type": "text", "validation": {"regex": "^[6-9][0-9]{9}$"}},
        {"name": "party_size", "question": "How many people?", "type": "button", "options": [{"id": "2", "title": "2"}, {"id": "4", "title": "4"}, {"id": "6", "title": "6"}, {"id": "8+", "title": "8+"}]},
        {"name": "date", "question": "Booking date (YYYY-MM-DD)?", "type": "text", "validation": {"regex": "^\\d{4}-\\d{2}-\\d{2}$"}},
        {"name": "time", "question": "Preferred time (e.g., 7:00 PM)?", "type": "text", "required": True}
    ],
    "confirmation": {"enabled": True, "message": "Confirm your table booking:"},
    "lead_action": {"type": "create_lead", "service": "restaurant"}
}

SALON_CONFIG = {
    "name": "Salon Appointment Bot",
    "fields": [
        {"name": "name", "question": "Your name?", "type": "text"},
        {"name": "phone", "question": "Phone number?", "type": "text", "validation": {"regex": "^[6-9][0-9]{9}$"}},
        {"name": "service", "question": "Which service?", "type": "list", "options": [{"id": "haircut", "title": "Haircut"}, {"id": "spa", "title": "Spa"}, {"id": "manicure", "title": "Manicure"}, {"id": "pedicure", "title": "Pedicure"}]},
        {"name": "preferred_date", "question": "Preferred date (YYYY-MM-DD)?", "type": "text"}
    ],
    "confirmation": {"enabled": True, "message": "Confirm your appointment:"},
    "lead_action": {"type": "create_lead", "service": "salon"}
}

ECOMMERCE_CONFIG = {
    "name": "E‑commerce Support Bot",
    "fields": [
        {"name": "name", "question": "Your name?", "type": "text"},
        {"name": "order_id", "question": "Order ID (if any)?", "type": "text"},
        {"name": "issue", "question": "What issue are you facing?", "type": "list", "options": [{"id": "delivery", "title": "Delivery delay"}, {"id": "return", "title": "Return/Refund"}, {"id": "product", "title": "Product issue"}]}
    ],
    "confirmation": {"enabled": True, "message": "Confirm your support request:"},
    "lead_action": {"type": "create_lead", "service": "ecommerce"}
}

HEALTHCARE_CONFIG = {
    "name": "Healthcare Appointment Bot",
    "fields": [
        {"name": "name", "question": "Patient name?", "type": "text"},
        {"name": "phone", "question": "Contact number?", "type": "text", "validation": {"regex": "^[6-9][0-9]{9}$"}},
        {"name": "symptom", "question": "Brief symptoms?", "type": "text"},
        {"name": "preferred_date", "question": "Preferred appointment date?", "type": "text"}
    ],
    "confirmation": {"enabled": True, "message": "Confirm appointment details:"},
    "lead_action": {"type": "create_lead", "service": "healthcare"}
}

EDUCATION_CONFIG = {
    "name": "Education Inquiry Bot",
    "fields": [
        {"name": "student_name", "question": "Student's name?", "type": "text"},
        {"name": "parent_phone", "question": "Parent's phone?", "type": "text", "validation": {"regex": "^[6-9][0-9]{9}$"}},
        {"name": "course", "question": "Course interested in?", "type": "list", "options": [{"id": "engineering", "title": "Engineering"}, {"id": "medical", "title": "Medical"}, {"id": "commerce", "title": "Commerce"}, {"id": "arts", "title": "Arts"}]}
    ],
    "confirmation": {"enabled": True, "message": "Confirm your inquiry:"},
    "lead_action": {"type": "create_lead", "service": "education"}
}

# List of all default configs (for iteration)
DEFAULT_CONFIGS = [
    ("Real Estate", REAL_ESTATE_CONFIG),
    ("Restaurant", RESTAURANT_CONFIG),
    ("Salon", SALON_CONFIG),
    ("Ecommerce", ECOMMERCE_CONFIG),
    ("Healthcare", HEALTHCARE_CONFIG),
    ("Education", EDUCATION_CONFIG),
]

async def seed_bot_configs():
    """Insert default bot configs for all organisations that don't have them."""
    async with AsyncSessionLocal() as db:
        # Get all organisations
        orgs_result = await db.execute(select(Organization.id))
        org_ids = [row[0] for row in orgs_result.fetchall()]

        if not org_ids:
            print("No organisations found. Nothing to seed.")
            return

        print(f"Found {len(org_ids)} organisations. Seeding default configs...")

        inserted = 0
        skipped = 0

        for org_id in org_ids:
            for name, config in DEFAULT_CONFIGS:
                # Check if this organisation already has a bot config with this name and version 1
                existing = await db.execute(
                    select(BotConfig).where(
                        BotConfig.organization_id == org_id,
                        BotConfig.name == name,
                        BotConfig.version == 1
                    )
                )
                if existing.scalar_one_or_none():
                    print(f"⏩ Skipping {name} for org {org_id} (already exists)")
                    skipped += 1
                    continue

                # Insert new config
                new_config = BotConfig(
                    id=uuid.uuid4(),
                    organization_id=org_id,
                    name=name,
                    description=f"Default {name.lower()} bot configuration",
                    config=config,
                    version=1,
                    is_active=False,  # Not active by default
                    created_by=None,
                    created_at=datetime.utcnow()
                )
                db.add(new_config)
                inserted += 1
                print(f"✅ Inserted {name} config for org {org_id}")

        await db.commit()
        print(f"\n🎉 Seeding complete! Inserted: {inserted}, Skipped: {skipped}")

if __name__ == "__main__":
    asyncio.run(seed_bot_configs())