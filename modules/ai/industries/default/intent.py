import re
from ..base import BaseIntentClassifier

class DefaultIntentClassifier(BaseIntentClassifier):
    def __init__(self):
        self.intents = {
            "greeting": ["hi", "hello", "namaste", "hey", "greetings"],
            "price": ["price", "cost", "rate", "kitne", "daam", "how much"],
            "hours": ["hours", "timing", "khula", "open", "close", "time"],
            "location": ["location", "address", "kahan", "where"],
            "contact": ["contact", "phone", "number", "call", "mobile"],
            "offer": ["offer", "discount", "cheap", "sasta", "deal", "promotion"],
            "menu": ["menu", "services", "list", "what you offer"],
            "affirm": ["yes", "haan", "theek", "ok", "okay", "confirm"],
            "negate": ["no", "nahi", "cancel", "not"],
        }

    def classify(self, text: str) -> str:
        text_lower = text.lower()
        for intent, keywords in self.intents.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "unknown"

    def extract_entities(self, text: str) -> dict:
        entities = {}
        # Simple name extraction
        name_match = re.search(r"(?:my name is|i am|i'm|name is)\s+([a-zA-Z]+)", text.lower())
        if name_match:
            entities["name"] = name_match.group(1).title()
        # Phone extraction
        phone_match = re.search(r"\b(\d{10})\b", text)
        if phone_match:
            entities["phone"] = phone_match.group(1)
        return entities