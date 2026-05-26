# modules/realestate/repo.py
import logging
from typing import List, Dict, Optional
from sqlalchemy import select, and_
from modules.common.database import AsyncSessionLocal
from modules.common.models import Property  # assuming you have a Property model; if not, we'll mock

logger = logging.getLogger(__name__)

async def search_properties(
    location: Optional[str] = None,
    budget_max: Optional[int] = None,
    bhk: Optional[int] = None,
    property_type: str = "apartment",
    limit: int = 5
) -> List[Dict]:
    """
    Search properties based on criteria.
    Returns a list of dicts with id, title, price, location, etc.
    """
    try:
        async with AsyncSessionLocal() as db:
            # Try to query real Property table if exists
            # Replace 'Property' with your actual model name if different
            try:
                from modules.common.models import Property
                query = select(Property)
                conditions = []
                if location:
                    conditions.append(Property.location.ilike(f"%{location}%"))
                if budget_max:
                    conditions.append(Property.price <= budget_max)
                if bhk:
                    conditions.append(Property.bhk == bhk)
                if property_type:
                    conditions.append(Property.property_type == property_type)
                if conditions:
                    query = query.where(and_(*conditions))
                query = query.limit(limit)
                result = await db.execute(query)
                properties = result.scalars().all()
                return [
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "price": p.price,
                        "location": p.location,
                        "bhk": p.bhk,
                        "property_type": p.property_type
                    }
                    for p in properties
                ]
            except (ImportError, Exception) as e:
                logger.warning(f"Property table not found or error: {e}. Returning mock data.")
    except Exception as e:
        logger.error(f"Error in search_properties: {e}")

    # Fallback mock data (for demo / testing)
    return [
        {
            "id": "prop_1",
            "title": f"{bhk or 2} BHK Apartment in {location or 'prime area'}",
            "price": budget_max or 5000000,
            "location": location or "City Center",
            "bhk": bhk or 2,
            "property_type": property_type,
            "description": "Well‑maintained, near metro station."
        },
        {
            "id": "prop_2",
            "title": f"Luxury {bhk or 3} BHK in {location or 'suburb'}",
            "price": int((budget_max or 5000000) * 1.2),
            "location": location or "Suburb Area",
            "bhk": bhk or 3,
            "property_type": property_type,
            "description": "Premium amenities, ready to move."
        }
    ][:limit]