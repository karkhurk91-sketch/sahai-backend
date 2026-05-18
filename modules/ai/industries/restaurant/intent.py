import re
from difflib import get_close_matches
from ..base import BaseIntentClassifier

class RestaurantIntentClassifier(BaseIntentClassifier):
    def __init__(self):
        self.intents = {
            "greeting": ["hi", "hello", "namaste", "hey"],
            "menu": ["menu", "show menu", "what do you have", "options", "list"],
            "price": ["price", "cost", "rate", "kitne", "daam"],
            "confirm": ["yes", "haan", "confirm", "theek", "ok", "place order"],
            "cancel": ["no", "nahi", "cancel", "remove"],
            "add_item": ["add", "extra", "also"],
            "remove_item": ["remove", "hatao"],
        }
        self.menu_items = {
            "paneer butter masala": 250,
            "butter chicken": 320,
            "dal makhani": 180,
            "veg biryani": 200,
            "chicken biryani": 280,
            "garlic naan": 40,
            "butter naan": 35,
            "jeera rice": 120,
            "gulab jamun": 60,
            "ice cream": 80,
            "tandoori roti": 25,
            "mix veg": 160,
            "chicken tikka": 300,
        }
        self.item_names = list(self.menu_items.keys())

    def classify(self, text: str) -> str:
        text_lower = text.lower()
        for intent, keywords in self.intents.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "unknown"

    def extract_entities(self, text: str) -> dict:
        entities = {}
        text_lower = text.lower()
        # Find dish name – exact or fuzzy match
        found = None
        for dish in self.item_names:
            if dish in text_lower:
                found = dish
                break
        if not found:
            words = text_lower.split()
            for word in words:
                match = get_close_matches(word, self.item_names, n=1, cutoff=0.7)
                if match:
                    found = match[0]
                    break
        if found:
            entities["item"] = found
        # Extract name
        name_match = re.search(r"(?:my name is|i am|i'm|name is)\s+([a-zA-Z]+)", text_lower)
        if name_match:
            entities["name"] = name_match.group(1).title()
        # Extract phone number
        phone_match = re.search(r"\b(\d{10})\b", text)
        if phone_match:
            entities["phone"] = phone_match.group(1)
        return entities