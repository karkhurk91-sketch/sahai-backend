# modules/ai/industries/realestate/state.py

class State:
    """
    Stores conversation state for real estate rule mode.
    Tracks collected lead info, stage, and scores.
    """
    def __init__(self):
        # Lead fields
        self.name = None
        self.phone = None
        self.budget = None          # raw budget string
        self.budget_amount = None   # numeric in lakhs
        self.location = None
        self.bhk = None
        self.property_type = None
        self.possession = None      # "immediate", "3-6 months", etc.
        self.intent = None          # "buy", "rent", "sell"
        self.loan_status = None     # "cash", "pre-approved", "apply", "none"
        self.is_decision_maker = None  # True/False
        self.reason = None          # "relocation", "upgrade", "investment", etc.

        # BANT scoring
        self.bant_score = 0          # 0-100
        self.lead_tag = None         # "hot", "warm", "cold"

        # Conversation stage
        self.stage = "greeting"      # greeting, qualification, recommendation, booking, followup, closed
        self.last_intent = None

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    def from_dict(self, data):
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def calculate_bant_score(self):
        """Compute BANT score based on collected fields."""
        score = 0
        # Budget: >50 lakh = 25, 20-50 = 15, <20 = 5
        if self.budget_amount:
            if self.budget_amount > 50:
                score += 25
            elif self.budget_amount >= 20:
                score += 15
            else:
                score += 5
        # Timeline: within 1-2 months = 25, 3-6 = 15, 6+ = 5
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
            score += 15 if self.is_decision_maker else (10 if self.is_decision_maker == "partner" else 5)
        # Reason: relocation/urgent = 10, upgrade/first = 5, browsing = 0
        if self.reason:
            if self.reason in ["relocation", "job change", "urgent"]:
                score += 10
            elif self.reason in ["upgrade", "first home"]:
                score += 5
            # else 0
        self.bant_score = score
        if score >= 70:
            self.lead_tag = "hot"
        elif score >= 40:
            self.lead_tag = "warm"
        else:
            self.lead_tag = "cold"
        return score