# modules/ai/intent_detector.py
import re
from typing import Dict, Tuple

class IntentDetector:
    INTENT_PATTERNS = {
        "greeting": r"(hi|hello|hey|good morning|good afternoon|good evening|नमस्ते|हेलो)",
        "qualification": r"(budget|looking for|requirement|size|bhk|bedroom|location|area|city|बजट|लोकेशन|शहर|बीएचके)",
        "booking_request": r"(book|appointment|schedule|visit|meet|tomorrow|next week|बुक|अपॉइंटमेंट|विज़िट)",
        "recommendation_request": r"(recommend|suggest|show me|options|available|सुझाव|दिखाओ|ऑप्शन)",
        "confirmation": r"(yes|ok|sure|please|confirm|agree|हाँ|ठीक है|करें)",
        "objection": r"(no|not interested|too expensive|maybe later|cancel|नहीं|महंगा|बाद में)"
    }

    @classmethod
    def detect(cls, user_message: str) -> Tuple[str, Dict]:
        user_message = user_message.lower().strip()
        entities = cls._extract_entities(user_message)
        for intent, pattern in cls.INTENT_PATTERNS.items():
            if re.search(pattern, user_message, re.IGNORECASE):
                return intent, entities
        return "unknown", entities

    @classmethod
    def _extract_entities(cls, message: str) -> Dict:
        entities = {}

        # Budget extraction (lakh, lakhs, lac, crore, etc.)
        budget_match = re.search(r'(\d+(?:\.\d+)?)\s*(lac|lakh|cr|crore|लाख|करोड़)', message, re.IGNORECASE)
        if budget_match:
            amount = float(budget_match.group(1))
            unit = budget_match.group(2).lower()
            if unit in ['lac', 'lakh', 'लाख']:
                entities['budget'] = f"{int(amount)} lakh"
            elif unit in ['crore', 'cr', 'करोड़']:
                entities['budget'] = f"{int(amount)} crore"
            else:
                entities['budget'] = f"{amount} {unit}"

        # BHK extraction
        bhk_match = re.search(r'(\d+)\s*(bhk|bedroom|बीएचके|बेडरूम)', message, re.IGNORECASE)
        if bhk_match:
            entities['bhk'] = int(bhk_match.group(1))

        # Location extraction
        loc_match = re.search(r'(?:in|at|near|location|लोकेशन|में)\s+([a-zA-Z\u0900-\u097F]+(?:\s+[a-zA-Z\u0900-\u097F]+)?)', message, re.IGNORECASE)
        if loc_match:
            entities['location'] = loc_match.group(1).strip()
        else:
            cities = ['indore', 'mumbai', 'delhi', 'bangalore', 'pune', 'chennai', 'kolkata', 'hyderabad', 'ahmedabad']
            for city in cities:
                if city in message:
                    entities['location'] = city
                    break

        # Name extraction
        name_match = re.search(r'(?:my name is|i am|called|name is)\s+([A-Za-z\u0900-\u097F]+)', message, re.IGNORECASE)
        if name_match:
            entities['name'] = name_match.group(1).strip()

        # Phone extraction (10 digits)
        phone_match = re.search(r'(\d{10})', message)
        if phone_match:
            entities['phone'] = phone_match.group(1)

        return entities