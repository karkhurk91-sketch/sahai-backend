import re
from difflib import get_close_matches
from ..base import BaseIntentClassifier

class SalonIntentClassifier(BaseIntentClassifier):
    def __init__(self):
        self.intents = {
            "greeting": ["hi", "hello", "namaste", "hey"],
            "book": ["book", "appointment", "want", "need", "chahiye", "lana", "aana"],
            "price": ["price", "kitne", "cost", "rate", "paise"],
            "hours": ["hours", "timing", "khula", "open", "close", "time"],
            "location": ["location", "address", "kahan", "where"],
            "offer": ["offer", "discount", "cheap", "sasta", "deal"],
            "name": ["my name is", "i am", "mera naam", "name is"],
            "phone": ["my number is", "phone", "mobile", "call"],
            "affirm": ["haan", "yes", "theek", "ok", "okay", "ha"],
            "negate": ["nahi", "no", "not", "matlab"],
        }
        self.services = ["haircut", "facial", "waxing", "threading", "manicure", "pedicure", "makeup", "hair color", "straightening", "keratin"]

    def classify(self, text: str) -> str:
        text_lower = text.lower()
        for intent, keywords in self.intents.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "unknown"

    def extract_entities(self, text: str) -> dict:
        entities = {}
        text_lower = text.lower()
        # Fuzzy match service
        for service in self.services:
            if service in text_lower:
                entities["service"] = service
                break
        else:
            # try close matches
            words = text_lower.split()
            for word in words:
                match = get_close_matches(word, self.services, n=1, cutoff=0.7)
                if match:
                    entities["service"] = match[0]
                    break
        # Time extraction
        time_match = re.search(r"(\d{1,2})\s*(am|pm|baje)", text_lower)
        if time_match:
            hour = int(time_match.group(1))
            period = time_match.group(2)
            if period == "pm" and hour != 12:
                hour += 12
            entities["hour"] = hour
        # Date extraction (simple)
        if "aaj" in text_lower or "today" in text_lower:
            entities["date"] = "today"
        elif "kal" in text_lower or "tomorrow" in text_lower:
            entities["date"] = "tomorrow"
        return entities