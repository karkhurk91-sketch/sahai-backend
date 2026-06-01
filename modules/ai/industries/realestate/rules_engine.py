# modules/ai/industries/realestate/rules_engine.py

import re
import logging
from .state import State

logger = logging.getLogger(__name__)

class RulesEngine:
    """
    Real estate rule engine with intent detection, BANT scoring, and stage transitions.
    """

    # Intent keyword mapping
    INTENTS = {
        "price_request": ["price", "cost", "rate", "kitne ka", "kitne mein", "budget", "₹"],
        "brochure_request": ["brochure", "price list", "rate list", "detail", "specification", "specs", "floor plan"],
        "site_visit_request": ["site visit", "visit", "see", "dekhe", "dikhaye", "tour", "schedule"],
        "loan_request": ["loan", "bank", "emi", "finance", "financing", "home loan"],
        "availability_request": ["available", "vacant", "left", "bache", "stock", "units"],
        "token_request": ["token", "block", "hold", "book", "reserve"],
        "maintenance_query": ["maintenance", "society", "tax", "property tax"],
        "carpet_area_query": ["carpet area", "super area", "sq ft", "sqft"],
        "objection_price": ["too high", "expensive", "bahut zyada", "budget kam", "out of budget"],
        "objection_docs": ["paper", "document", "noc", "registry", "legal"],
        "objection_time": ["not now", "later", "soch raha", "thinking", "not ready"],
        "greeting": ["hi", "hello", "namaste", "hey", "good morning", "good afternoon"],
        "confirmation": ["yes", "haan", "ji", "ok", "theek", "sure", "confirm"],
        "rejection": ["no", "nahi", "not interested", "cancel", "skip"],
        "sell_property": ["sell", "bechna", "listing", "seller", "selling"],
    }

    # Stage transition rules (simple)
    STAGE_FLOW = {
        "greeting": ["qualification"],
        "qualification": ["recommendation", "objection_handling"],
        "recommendation": ["booking", "objection_handling"],
        "booking": ["followup", "closed"],
        "objection_handling": ["qualification", "booking", "closed"],
        "followup": ["closed"],
        "closed": []
    }

    def __init__(self):
        self.extractors = {
            "name": r"(?:my name is|i am|called|name is)\s+([A-Za-z\u0900-\u097F]+)",
            "phone": r"(\d{10})",
            "budget": r"(\d+(?:\.\d+)?)\s*(lac|lakh|cr|crore|लाख|करोड़)",
            "location": r"(?:in|at|near|location)\s+([A-Za-z\u0900-\u097F]+(?:\s+[A-Za-z\u0900-\u097F]+)?)",
            "bhk": r"(\d+)\s*(bhk|bedroom|बीएचके|बेडरूम)",
            "possession": r"(immediate|now|asap|1[- ]month|2[- ]month|3[- ]month|6[- ]month|तुरंत|अभी|जल्दी)",
            "loan_status": r"(cash|pre[- ]approved|preapproved|apply|loan|बिना loan|कैश)",
            "is_decision_maker": r"(i am the decision|sole|myself|i will decide|main decision lunga|alone)",
            "reason": r"(job|relocation|transfer|upgrade|bigger|family|investment|rental income|परिवार|नौकरी)",
        }

    def detect_intent(self, text):
        """Classify user intent based on keywords."""
        text_lower = text.lower()
        for intent, keywords in self.INTENTS.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "unknown"

    def extract_fields(self, text, state):
        """Extract lead fields using regex."""
        text_lower = text.lower()
        for field, pattern in self.extractors.items():
            if getattr(state, field) is None:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1)
                    if field == "budget":
                        unit = match.group(2).lower() if len(match.groups()) > 1 else ""
                        if unit in ["lac", "lakh", "लाख"]:
                            value = f"{value} lakh"
                            state.budget_amount = float(value.split()[0])
                        elif unit in ["crore", "cr", "करोड़"]:
                            value = f"{value} crore"
                            state.budget_amount = float(value.split()[0]) * 100
                    elif field == "possession":
                        if "immediate" in value or "now" in value or "asap" in value or "तुरंत" in value:
                            state.possession = "immediate"
                        elif "1" in value or "2" in value:
                            state.possession = "1-2 months"
                        elif "3" in value or "6" in value:
                            state.possession = "3-6 months"
                        else:
                            state.possession = value
                    elif field == "loan_status":
                        if "cash" in value or "कैश" in value:
                            state.loan_status = "cash"
                        elif "pre" in value:
                            state.loan_status = "pre-approved"
                        elif "apply" in value or "loan" in value:
                            state.loan_status = "apply"
                        else:
                            state.loan_status = "none"
                    elif field == "is_decision_maker":
                        state.is_decision_maker = True
                    elif field == "reason":
                        if "job" in value or "relocation" in value or "transfer" in value:
                            state.reason = "relocation"
                        elif "upgrade" in value or "bigger" in value:
                            state.reason = "upgrade"
                        elif "investment" in value:
                            state.reason = "investment"
                        else:
                            state.reason = value
                    else:
                        setattr(state, field, value)
                    logger.info(f"Extracted {field} = {value}")

    def process(self, user_input, state):
        """
        Main processing loop:
        - Update state with extracted fields.
        - Determine intent.
        - Advance stage if needed.
        - Return action and data for reply generation.
        """
        self.extract_fields(user_input, state)
        intent = self.detect_intent(user_input)
        state.last_intent = intent

        # Stage transition logic (simplified)
        if state.stage == "greeting" and (state.name or intent != "greeting"):
            state.stage = "qualification"
            return {"action": "start_qualification", "data": {}}

        # Handle direct requests based on intent
        if intent == "price_request":
            return {"action": "reply_price", "data": {}}
        if intent == "brochure_request":
            return {"action": "reply_brochure", "data": {}}
        if intent == "site_visit_request":
            return {"action": "offer_site_visit", "data": {}}
        if intent == "loan_request":
            return {"action": "reply_loan", "data": {}}
        if intent == "availability_request":
            return {"action": "reply_availability", "data": {}}
        if intent == "token_request":
            return {"action": "offer_token", "data": {}}
        if intent == "maintenance_query":
            return {"action": "reply_maintenance", "data": {}}
        if intent == "carpet_area_query":
            return {"action": "reply_carpet_area", "data": {}}
        if intent.startswith("objection"):
            return {"action": "handle_objection", "data": {"objection_type": intent.split("_")[1]}}
        if intent == "sell_property":
            return {"action": "seller_prompt", "data": {}}

        # Qualification stage: ask missing BANT fields
        if state.stage == "qualification":
            missing = []
            if not state.budget_amount:
                missing.append("budget")
            if not state.possession:
                missing.append("possession")
            if not state.loan_status:
                missing.append("loan_status")
            if state.is_decision_maker is None:
                missing.append("decision_maker")
            if not state.reason:
                missing.append("reason")

            if missing:
                next_field = missing[0]
                return {"action": f"ask_{next_field}", "data": {}}
            else:
                # All BANT fields collected -> calculate score
                state.calculate_bant_score()
                state.stage = "recommendation"
                return {"action": "recommendation", "data": {"score": state.bant_score, "tag": state.lead_tag}}

        # Default fallback
        return {"action": "fallback", "data": {"intent": intent}}