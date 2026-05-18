from ..base import BasePrompts

class RestaurantPrompts(BasePrompts):
    def __init__(self, org_id: str = None):
        self.org_id = org_id
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

    def get_system_prompt(self) -> str:
        from modules.ai.agent import get_system_prompt_sync
        base = get_system_prompt_sync(self.org_id)
        return base

    def get_action_prompt(self, action: str, data: dict) -> str:
        # LLM prompts (for AI mode) – you can keep your existing longer version
        if action == "greet":
            return "Namaste! Welcome to our restaurant. Would you like to see the menu or place an order?"
        else:
            return "How can I help you with your order?"

    def get_rule_reply(self, action: str, data: dict) -> str | None:
        # Static replies for rule mode
        if action == "greet":
            return "Namaste! Welcome to our restaurant. Would you like to see the menu or place an order?"
        if action == "ask_menu":
            menu_lines = ["Here is our menu:"]
            for item, price in self.menu_items.items():
                menu_lines.append(f"• {item.title()} – ₹{price}")
            menu_lines.append("\nWhat would you like to order?")
            return "\n".join(menu_lines)
        if action == "ask_price":
            return "Our prices are listed in the menu. Which dish are you interested in?"
        if action == "ask_hours":
            return "We are open from 11 AM to 11 PM, Tuesday to Sunday."
        if action == "ask_location":
            return "We are located at [Your Address]. Would you like Google Maps directions?"
        if action == "ask_contact":
            return "You can reach us at +91 12345 67890."
        if action == "ask_item":
            return "What would you like to order? Just say the dish name."
        if action == "ask_name":
            return "May I know your name for the order?"
        if action == "ask_phone":
            return "Please share your phone number for order confirmation."
        if action == "ask_delivery_preference":
            return "Would you like delivery or takeaway?"
        if action == "ask_confirmation":
            order = data.get("order", {})
            total = data.get("total", 0)
            items = ", ".join(f"{qty}x {item}" for item, qty in order.items())
            return f"Your order: {items}. Total ₹{total}. Say 'yes' to place order."
        if action == "order_confirmed":
            return "Thank you! Your order has been placed. We'll keep you updated."
        if action == "already_confirmed":
            return "Your order is already confirmed. Would you like anything else?"
        if action == "handle_feedback":
            return "Thank you for your response!"
        if action == "fallback":
            return "I'm sorry, I didn't understand. Could you please rephrase?"
        return None