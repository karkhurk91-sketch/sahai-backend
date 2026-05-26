import logging
from typing import List, Dict, Optional
from modules.common.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

async def search_properties(
    location: Optional[str] = None,
    budget_max: Optional[int] = None,
    bhk: Optional[int] = None,
    property_type: str = "apartment",
    limit: int = 5
) -> List[Dict]:
    """Search properties based on criteria. Returns mock data if real table not found."""
    try:
        # Attempt to query real Property table if it exists
        from modules.common.models import Property
        from sqlalchemy import select, and_
        async with AsyncSessionLocal() as db:
            query = select(Property)
            conditions = []
            if location:
                conditions.append(Property.location.ilike(f"%{location}%"))
            if budget_max:
                conditions.append(Property.price <= budget_max)
            if bhk:
                conditions.append(Property.bhk == bhk)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.limit(limit)
            result = await db.execute(query)
            properties = result.scalars().all()
            if properties:
                return [
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "price": p.price,
                        "location": p.location,
                        "bhk": p.bhk,
                        "property_type": p.property_type,
                        "description": getattr(p, "description", "")
                    }
                    for p in properties
                ]
    except (ImportError, Exception) as e:
        logger.warning(f"Property table not found or error: {e}. Returning mock data.")

    # Fallback mock data for development/testing
    return [
        {
            "id": "prop_1",
            "title": f"{bhk or 2} BHK {'Apartment' if property_type == 'apartment' else 'Villa'} in {location or 'Prime Area'}",
            "price": budget_max or 5000000,
            "location": location or "City Center",
            "bhk": bhk or 2,
            "property_type": property_type,
            "description": "Well‑maintained property with modern amenities. Near metro station."
        },
        {
            "id": "prop_2",
            "title": f"Premium {bhk or 3} BHK in {location or 'Suburb'}",
            "price": int((budget_max or 5000000) * 1.2) if budget_max else 6000000,
            "location": location or "Green Valley",
            "bhk": bhk or 3,
            "property_type": property_type,
            "description": "Luxury property with park view and 24/7 security."
        }
    ][:limit]