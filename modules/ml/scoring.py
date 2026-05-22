import numpy as np
from datetime import datetime, timezone

def predict_conversion_probability(features: np.ndarray) -> float:
    """
    Lightweight rule‑based scoring (no XGBoost).
    Features: [msg_count, avg_resp_time, sentiment, recency_hours, industry_onehot...]
    """
    msg_count = features[0]
    avg_resp_time = features[1]
    sentiment = features[2]
    recency_hours = features[3]
    
    # Higher score for more messages, positive sentiment, recent activity
    score = 0.0
    if msg_count >= 5:
        score += 0.3
    elif msg_count >= 2:
        score += 0.15
    
    if avg_resp_time < 60:  # responds within 1 minute
        score += 0.2
    elif avg_resp_time < 300:
        score += 0.1
    
    if sentiment > 0.5:
        score += 0.3
    elif sentiment > 0:
        score += 0.1
    
    if recency_hours < 1:
        score += 0.2
    elif recency_hours < 24:
        score += 0.1
    
    # Industry bonus (if tech)
    if len(features) > 4 and features[4] == 1:  # industry_tech
        score += 0.1
    
    return min(score, 1.0)

def load_scoring_model():
    # No model to load – dummy function
    return None

def train_initial_model():
    # No training needed
    pass