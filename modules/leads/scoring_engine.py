# Reuse existing feature_extractor and rule-based score as fallback
from modules.ml.feature_extractor import extract_features_for_lead
import joblib

MODEL_PATH = "models/lead_scoring_v1.pkl"

async def score_lead(db: AsyncSession, lead_id: str):
    lead = await db.get(Lead, lead_id)
    messages = await get_conversation_messages(db, lead.conversation_id)
    features = extract_features_for_lead(lead, messages)  # already exists
    
    try:
        model = joblib.load(MODEL_PATH)
        prob = model.predict_proba([features])[0][1]
    except:
        # Fallback to rule‑based (already exists in webhook)
        prob = predict_conversion_probability(features)  # your rule function
    
    lead.lead_score = int(prob * 100)
    lead.conversion_probability = prob
    lead.last_scored_at = datetime.utcnow()
    await db.commit()
    return lead