# modules/orchestration/industries/base.py
from abc import ABC, abstractmethod
from typing import List, Dict

class BaseIndustry(ABC):
    """Abstract base for industry‑specific logic."""
    
    @property
    @abstractmethod
    def required_fields(self) -> List[str]:
        pass
    
    @abstractmethod
    async def get_recommendations(self, lead_data: Dict, limit: int = 5) -> List[Dict]:
        pass
    
    @abstractmethod
    def get_booking_slots(self, lead_data: Dict) -> List[Dict]:
        pass