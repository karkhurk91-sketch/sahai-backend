import re
from ..base import BaseRulesEngine
from .intent import SalonIntentClassifier
from .state import SalonState
from modules.ai.industries.default.rules import DefaultRulesEngine

class SalonRulesEngine(BaseRulesEngine):
    def __init__(self):
        super().__init__()
        self.available_slots = ["11:00", "14:00", "17:00"]
        self.intent_classifier = SalonIntentClassifier()
        self.default_engine = DefaultRulesEngine()

    def process(self, user_text: str, state: SalonState) -> dict:
        # Detect if this is a booking-related message
        is_booking = (
            state.service or state.time or state.name or state.phone or
            any(word in user_text.lower() for word in ["book", "appointment", "haircut", "facial", "waxing", "threading", "manicure", "pedicure"])
        )

        if not is_booking:
            # Not booking-related – use global default rules
            return self.default_engine.process(user_text, None)

        # --- Booking flow logic (existing) ---
        entities = self.intent_classifier.extract_entities(user_text)
        user_lower = user_text.lower()

        # Update state from entities
        if entities.get("service") and not state.service:
            state.service = entities["service"]
        if entities.get("hour") and not state.time:
            slot_str = f"{entities['hour']:02d}:00"
            if slot_str in self.available_slots:
                state.time = slot_str
            else:
                return {"action": "invalid_time", "data": {"suggestions": self.available_slots}}

        # Extract name (simple heuristic)
        if any(word in user_lower for word in ["name", "naam", "i'm", "am", "mera"]) and not state.name:
            parts = user_text.split()
            for i, p in enumerate(parts):
                if p.lower() in ["name", "naam", "i'm", "am", "mera"] and i+1 < len(parts):
                    state.name = parts[i+1].strip(",.").title()
                    break

        # Extract phone number (10 digits)
        if not state.phone:
            nums = re.findall(r"\b\d{10}\b", user_text)
            if nums:
                state.phone = nums[0]

        # Check for confirmation (base method)
        confirmation_action = self.process_confirmation(user_text, state)
        if confirmation_action:
            return confirmation_action

        # Determine next action based on missing fields
        if not state.service:
            return {"action": "ask_service", "data": {}}
        elif not state.time:
            return {"action": "ask_time", "data": {"suggestions": self.available_slots}}
        elif not state.name:
            return {"action": "ask_name", "data": {}}
        elif not state.phone:
            return {"action": "ask_phone", "data": {}}
        else:
            # All fields collected, waiting for confirmation
            return {"action": "ask_confirmation", "data": {"state": state.to_dict()}}