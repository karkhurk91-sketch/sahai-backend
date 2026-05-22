import re

INTENT_KEYWORDS = {
    "pricing": ["price", "cost", "how much", "pricing", "fee", "subscription"],
    "support": ["help", "issue", "problem", "not working", "support"],
    "sales": ["buy", "purchase", "interested", "demo", "trial", "sign up"],
    "complaint": ["bad", "terrible", "worst", "angry", "frustrated"],
    "interested": ["yes", "please", "tell me more", "interested", "want to"],
    "not_interested": ["no", "not interested", "stop", "unsubscribe", "later"]
}

def simple_intent(text: str) -> str:
    text_lower = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if re.search(rf'\b{re.escape(kw)}\b', text_lower):
                return intent
    return "general"