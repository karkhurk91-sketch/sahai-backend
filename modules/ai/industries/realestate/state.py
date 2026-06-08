# modules/ai/industries/realestate/state.py

class State:
    def __init__(self):
        # Basic lead fields
        self.name = None
        self.phone = None
        self.budget = None          
        self.budget_amount = None   
        self.location = None
        self.bhk = None
        self.property_type = None
        self.possession = None
        self.intent = None
        self.loan_status = None
        self.is_decision_maker = None
        self.reason = None

        # BANT scoring
        self.bant_score = 0
        self.lead_tag = None

        # Conversation stage
        self.stage = "greeting"
        self.last_intent = None

        # Organization-specific flow configuration
        self.flow_type = "buyer"
        self.flow_steps = []
        self.flow_source = None
        self.current_step_index = 0

        # Confirmation & correction
        self.confirmation_pending = False
        self.pending_summary = {}
        self.pending_correction_field = None
        self.awaiting_field = None
        self.previous_lead_summary = None

        self.budget_confirmed = False
        self.interactive_map = {}
        self.expecting_field_selection = False
        self.awaiting_field_name = False
        self.last_action = None
        self.correction_pending = False



    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    def from_dict(self, data):
        for k, v in data.items():
            if k.startswith('_'):
                continue
            setattr(self, k, v)

    def calculate_bant_score(self):
        """Compute BANT score and lead tag based on collected fields."""
        score = 0
        # Budget: >50 lakh = 25, 20-50 = 15, <20 = 5
        if self.budget_amount:
            if self.budget_amount > 50:
                score += 25
            elif self.budget_amount >= 20:
                score += 15
            else:
                score += 5

        # Timeline: immediate/1-2 months = 25, 3-6 = 15, 6+ = 5
        if self.possession:
            pos_lower = self.possession.lower()
            if "immediate" in pos_lower or "1-2" in pos_lower or "1 month" in pos_lower:
                score += 25
            elif "3-6" in pos_lower or "3 month" in pos_lower:
                score += 15
            else:
                score += 5

        # Loan status: cash/pre-approved = 25, applying = 15, not planning = 5
        if self.loan_status:
            if self.loan_status in ["cash", "pre-approved"]:
                score += 25
            elif self.loan_status == "apply":
                score += 15
            else:
                score += 5

        # Decision maker: yes = 15, partner = 10, exploring = 5
        if self.is_decision_maker is not None:
            if self.is_decision_maker is True:
                score += 15
            elif self.is_decision_maker == "partner":
                score += 10
            else:
                score += 5

        # Reason: relocation/urgent = 10, upgrade/first = 5, browsing = 0
        if self.reason:
            if self.reason in ["relocation", "job change", "urgent"]:
                score += 10
            elif self.reason in ["upgrade", "first home"]:
                score += 5

        self.bant_score = score
        if score >= 70:
            self.lead_tag = "hot"
        elif score >= 40:
            self.lead_tag = "warm"
        else:
            self.lead_tag = "cold"
        return score