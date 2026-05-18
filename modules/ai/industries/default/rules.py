from ..base import BaseRulesEngine
from .intent import DefaultIntentClassifier

class DefaultRulesEngine(BaseRulesEngine):
    def __init__(self):
        super().__init__()
        self.intent_classifier = DefaultIntentClassifier()

    def process(self, user_text: str, state) -> dict:
        intent = self.intent_classifier.classify(user_text)
        if intent == "greeting":
            return {"action": "greet", "data": {}}
        elif intent == "menu":
            return {"action": "ask_menu", "data": {}}
        elif intent == "price":
            return {"action": "ask_price", "data": {}}
        elif intent == "hours":
            return {"action": "ask_hours", "data": {}}
        elif intent == "location":
            return {"action": "ask_location", "data": {}}
        elif intent == "contact":
            return {"action": "ask_contact", "data": {}}
        elif intent == "offer":
            return {"action": "ask_offer", "data": {}}
        elif intent in ("affirm", "negate"):
            return {"action": "handle_feedback", "data": {}}
        else:
            return {"action": "fallback", "data": {}}