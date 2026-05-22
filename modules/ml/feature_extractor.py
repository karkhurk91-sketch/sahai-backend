# modules/ml/feature_extractor.py
import numpy as np
from datetime import datetime, timezone

def ensure_aware(dt):
    """Convert naive datetime to UTC‑aware if needed."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def extract_features_for_lead(lead, conversation_messages):
    """
    Extract feature vector for a lead based on conversation history.
    Returns a numpy array of features for scoring.
    Features: [msg_count, avg_response_time, sentiment_score, recency_hours,
               industry_tech, industry_retail, industry_health, industry_other]
    """
    # 1. Message count
    msg_count = len(conversation_messages)

    # 2. Average response time (seconds) between consecutive messages
    if msg_count >= 2:
        resp_times = []
        for i in range(1, len(conversation_messages)):
            current = ensure_aware(conversation_messages[i].created_at)
            previous = ensure_aware(conversation_messages[i-1].created_at)
            delta = (current - previous).total_seconds()
            # Ignore gaps longer than 24 hours
            if 0 < delta < 86400:
                resp_times.append(delta)
        avg_resp_time = float(np.mean(resp_times)) if resp_times else 0.0
    else:
        avg_resp_time = 0.0

    # 3. Sentiment score (stored in lead, default 0.0)
    sentiment = getattr(lead, 'sentiment_score', 0.0) or 0.0

    # 4. Recency (hours since last activity)
    if conversation_messages:
        last_time = ensure_aware(conversation_messages[-1].created_at)
    else:
        last_time = ensure_aware(getattr(lead, 'created_at', None))
    now_aware = datetime.now(timezone.utc)
    recency_hours = (now_aware - last_time).total_seconds() / 3600.0

    # 5. Industry (one‑hot encoding) – default to "other"
    industry = getattr(lead, 'industry', 'other') or 'other'
    industry_map = {"tech": 0, "retail": 1, "health": 2, "other": 3}
    industry_code = industry_map.get(industry, 3)

    features = [msg_count, avg_resp_time, sentiment, recency_hours]
    # Append one‑hot for four industry categories
    for i in range(4):
        features.append(1 if industry_code == i else 0)

    return np.array(features, dtype=np.float32)