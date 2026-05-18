from ..base import BaseRulesEngine
from .state import RestaurantState
from .intent import RestaurantIntentClassifier
from modules.ai.industries.default.rules import DefaultRulesEngine

class RestaurantRulesEngine(BaseRulesEngine):
    def __init__(self):
        super().__init__()
        self.intent = RestaurantIntentClassifier()
        self.default_engine = DefaultRulesEngine()

    def process(self, user_text: str, state: RestaurantState) -> dict:
        # Detect dish names from user input
        entities = self.intent.extract_entities(user_text)
        dish = entities.get("item")

        # If a dish is mentioned, add it to order (or update quantity)
        if dish:
            if state.order_items is None:
                state.order_items = {}
            # Default quantity 1; we can add quantity extraction later
            state.order_items[dish] = state.order_items.get(dish, 0) + 1
            # Mark that we are in ordering flow
            state.ordering_flow = True

        # Determine if we are in ordering flow
        is_ordering = state.ordering_flow or bool(state.order_items) or dish is not None

        if is_ordering:
            # Check missing fields (order is now automatically filled by adding items)
            missing = []
            # order_items can be non‑empty, so only missing if no items added yet
            if not state.order_items:
                missing.append("order")
            if not state.name:
                missing.append("name")
            if not state.phone:
                missing.append("phone")
            if not state.delivery_preference:
                missing.append("delivery")

            if missing:
                # Ask for the first missing field
                if "order" in missing:
                    return {"action": "ask_item", "data": {}}
                if "name" in missing:
                    return {"action": "ask_name", "data": {}}
                if "phone" in missing:
                    return {"action": "ask_phone", "data": {}}
                if "delivery" in missing:
                    return {"action": "ask_delivery_preference", "data": {}}
            else:
                # All fields present – handle confirmation
                confirmation_action = self.process_confirmation(user_text, state)
                if confirmation_action:
                    return confirmation_action
                if state.confirmed:
                    return {"action": "already_confirmed", "data": {"state": state.to_dict()}}
                # Ask for confirmation if not yet confirmed
                total = sum(state.menu_prices.get(item, 0) * qty for item, qty in state.order_items.items())
                return {"action": "ask_confirmation", "data": {"order": state.order_items, "total": total}}
        else:
            # Not ordering – use global default rules (greeting, menu, price, hours, etc.)
            return self.default_engine.process(user_text, state)