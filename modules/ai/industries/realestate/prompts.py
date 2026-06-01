# modules/ai/industries/realestate/prompts.py

class Prompts:
    """Pre‑written replies for each action – natural and bilingual."""

    def __init__(self, org_id):
        self.org_id = org_id

    def get_rule_reply(self, action: str, data: dict, state=None) -> str:
        """Return reply text for the given action."""
        # Confirmation & correction actions
        if action == "ask_confirmation":
            summary = data.get("summary", {})
            return self._confirmation_prompt(summary)
        if action == "ask_confirmation_again":
            summary = data.get("summary", {})
            return self._confirmation_prompt(summary) + " Please reply 'yes' to confirm or 'no' to change something."
        if action == "ask_which_field_to_correct":
            return "Which detail would you like to change? (budget / location / bhk / name / phone)"
        if action == "ask_which_field":
            return "I didn't catch which field. Please say the field name (budget, location, bhk, name, or phone)."
        if action.startswith("ask_new_value_for_"):
            field = data.get("field", "field")
            return f"Please provide the new value for {field}."

        # Greeting
        if action == "greeting":
            return "Hello! I'm your real estate assistant. Are you looking to buy, rent, or sell a property?"

        # Asking for missing fields (basic)
        if action.startswith("ask_"):
            field = action.split("_")[1]
            return self._ask_field_prompt(field, state)

        # Direct responses to user intents
        if action == "reply_price":
            return "Our 2BHK starts at ₹80 lakhs (amenities included). Want to check availability?"
        if action == "reply_brochure":
            return "Sure, sending the brochure and price sheet now. Which floor or unit do you prefer?"
        if action == "offer_site_visit":
            return "We can schedule a site visit – morning or evening works better for you?"
        if action == "reply_loan":
            return "We have home loans available. Should I arrange a call with our loan manager?"
        if action == "reply_availability":
            return "Yes, limited units are available at this price. Should I block one for you?"
        if action == "offer_token":
            return "Yes, we can hold a unit for ₹1 lakh token. Shall I proceed?"
        if action == "reply_maintenance":
            return "Maintenance is ₹2,500 per month and taxes are up‑to‑date. Need more details?"
        if action == "reply_carpet_area":
            return "The carpet area is 1100 sq.ft and price is ₹7,200/sq.ft. Do you want the floor plan?"
        if action == "seller_prompt":
            return "Hi! I see you're planning to sell your property. Could you tell me a bit about it (size, location, condition)?"
        if action == "handle_objection":
            obj = data.get("objection_type", "price")
            return self._objection_reply(obj)
        if action == "lead_complete":
            return self._lead_complete_reply(data, state)
        if action == "recommendation":
            tag = data.get("tag", "warm")
            if tag == "hot":
                return "Great! Based on your requirements, I have a few options. Here are two: one near the metro for ₹48L and another near the park for ₹52L. Would you like to schedule a site visit?"
            else:
                # For warm or unknown, do NOT ask for phone number again
                return "Thank you! I have all your details. Would you like me to send you a list of properties that match your criteria?"

        # Fallback
        if action == "fallback":
            return "I'm here to help with property prices, brochures, site visits, loans, or any other details. Could you please rephrase your question?"

        return "How can I help you with your property needs today?"

    def _ask_field_prompt(self, field: str, state) -> str:
        prompts = {
            "name": "May I know your name?",
            "phone": "Please share your mobile number.",
            "budget": "What is your budget range? (e.g., 50 lakhs, 1 crore)",
            "location": "Which location are you looking for? (e.g., Indore, Rajendra Nagar)",
            "bhk": "How many bedrooms do you need? (1/2/3 BHK)",
            "possession": "When would you like to move in? (immediate, 1-2 months, 3-6 months)",
            "loan_status": "Loan status – cash, pre‑approved, or applying?",
            "decision_maker": "Are you the sole decision‑maker for this purchase?",
            "reason": "What is your primary reason for buying? (e.g., job relocation, upgrade, investment)",
        }
        return prompts.get(field, "Could you please provide that information?")

    def _objection_reply(self, obj_type: str) -> str:
        replies = {
            "price": "I understand. Should I find similar units within your budget?",
            "docs": "Don't worry – we handle all paperwork (NOC, registry, etc.). I'll guide you.",
            "time": "Understood, take your time. I'll follow up in a few days.",
        }
        return replies.get(obj_type, "I'd be happy to address any concerns. Could you tell me more?")

    def _lead_complete_reply(self, data: dict, state) -> str:
        name = data.get("name") or ""
        bhk = data.get("bhk") or ""
        location = data.get("location") or ""
        budget = data.get("budget") or ""
        tag = data.get("lead_tag", "warm")

        if tag == "hot":
            return (
                f"Thanks {name}! We have {bhk} BHK options in {location} within {budget}. "
                "Would you like to schedule a site visit or see photos?"
            )
        else:
            return (
                f"Thank you {name}! I've noted your requirements. "
                "Our agent will get back to you shortly with the best options."
            )

    def _confirmation_prompt(self, summary: dict) -> str:
        name = summary.get("name", "Not provided")
        budget = summary.get("budget", "Not provided")
        location = summary.get("location", "Not provided")
        bhk = summary.get("bhk", "Not provided")
        phone = summary.get("phone", "Not provided")
        possession = summary.get("possession", "Not specified")
        return (
            f"Please confirm your details:\n"
            f"• Name: {name}\n"
            f"• Budget: {budget}\n"
            f"• Location: {location}\n"
            f"• BHK: {bhk}\n"
            f"• Phone: {phone}\n"
            f"• Possession: {possession}\n"
            f"Reply 'yes' to confirm or 'no' to correct something."
        )