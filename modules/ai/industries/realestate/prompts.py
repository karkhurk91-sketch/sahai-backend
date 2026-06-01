# modules/ai/industries/realestate/prompts.py

class Prompts:
    """
    Provides context‑aware replies based on action, state, and intent.
    Implements the bilingual templates from the sales script.
    """

    def __init__(self, org_id):
        self.org_id = org_id

    def get_rule_reply(self, action, data, state=None):
        """Return the appropriate reply text."""
        if action == "start_qualification":
            return self._qualification_prompt(state)

        if action.startswith("ask_"):
            field = action.split("_")[1]
            return self._ask_field_prompt(field, state)

        if action == "reply_price":
            return "Our 2BHK starts at ₹80 lakhs (amenities included). Want to check availability?"
        if action == "reply_brochure":
            return "Sure, sending the brochure and price sheet now. Which floor or unit do you prefer?"
        if action == "offer_site_visit":
            return "We can schedule a site visit – morning or evening works better for you?"
        if action == "reply_loan":
            return "We have bank loans available. Should I arrange a call with our loan manager?"
        if action == "reply_availability":
            return "Yes, limited units are available at this price. Should I block one for you?"
        if action == "offer_token":
            return "Yes, we can hold a unit for ₹1 lakh token. Shall I proceed to block it?"
        if action == "reply_maintenance":
            return "Maintenance is ₹2,500 per month and taxes are up‑to‑date. Need more details?"
        if action == "reply_carpet_area":
            return "The carpet area is 1100 sq.ft and price is ₹7,200/sq.ft. Do you want the floor plan?"
        if action == "seller_prompt":
            return "Hi! I see you're planning to sell your property. Could you tell me a bit about it (size, location, condition)?"
        if action == "handle_objection":
            obj = data.get("objection_type", "price")
            return self._objection_reply(obj)
        if action == "recommendation":
            tag = data.get("tag", "warm")
            if tag == "hot":
                return "Great! Based on your requirements, I have a few options. Here are two: one near the metro for ₹48L and another near the park for ₹52L. Would you like to schedule a site visit?"
            else:
                return "I understand. I'll share the best options with you. Could you share your mobile number so our agent can send you the details?"
        if action == "fallback":
            return "I'm here to help. Could you please rephrase your question? I can assist with prices, brochures, site visits, loans, or property details."

        return "How can I help you with your property needs today?"

    def _ask_field_prompt(self, field, state):
        prompts = {
            "budget": "What is your budget range? (e.g., 50 lakhs, 1 crore)",
            "possession": "When would you like to move? (immediate, 1-2 months, 3-6 months)",
            "loan_status": "Loan status – cash, pre‑approved, or applying?",
            "decision_maker": "Are you the sole decision‑maker for this purchase?",
            "reason": "What is your primary reason for buying? (e.g., job relocation, upgrade, investment)",
        }
        return prompts.get(field, "Could you please provide that information?")

    def _qualification_prompt(self, state):
        # Use name if known, else generic
        name = state.name if state.name else ""
        prefix = f"Thanks {name}! " if name else ""
        return prefix + "To help you better, could you share your budget and preferred possession timeframe?"

    def _objection_reply(self, obj_type):
        replies = {
            "price": "I understand. Should I find similar units within your budget?",
            "docs": "Don't worry – we handle all paperwork (NOC, registry, etc.). I'll guide you.",
            "time": "Understood, take your time. I'll follow up in a few days.",
        }
        return replies.get(obj_type, "I'd be happy to address any concerns. Could you tell me more?")