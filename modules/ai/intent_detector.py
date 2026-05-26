import re
from typing import Dict, Tuple

class IntentDetector:
    """
    Uses regex patterns to classify user intent and extract entities.
    This is a deterministic alternative to using an LLM for this task.
    """
    INTENT_PATTERNS = {
        "greeting": r"(hi|hello|hey|good morning|good afternoon|good evening)",
        "qualification": r"(budget|looking for|requirement|size|bhk|bedroom)",
        "booking_request": r"(book|appointment|schedule|visit|meet|tomorrow|next week)",
        "recommendation_request": r"(recommend|suggest|show me|options|available)",
        "confirmation": r"(yes|ok|sure|please|confirm|agree)",
        "objection": r"(no|not interested|too expensive|maybe later|cancel)"
    }

    @classmethod
    def detect(cls, user_message: str) -> Tuple[str, Dict]:
        user_message = user_message.lower()
        for intent, pattern in cls.INTENT_PATTERNS.items():
            if re.search(pattern, user_message):
                entities = cls._extract_entities(user_message, intent)
                return intent, entities
        return "unknown", {}

    @classmethod
    def _extract_entities(cls, message: str, intent: str) -> Dict:
        entities = {}
        # Add regex to pull out specific details like budget or location from a message.
        budget_match = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(lac|crore|k|million|billion)', message)
        if budget_match:
            entities["budget"] = f"{budget_match.group(1)} {budget_match.group(2)}"

        date_match = re.search(r'(tomorrow|next week|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)', message)
        if date_match:
            entities["date"] = date_match.group(1)
        return entities