from .model_loader import ModelLoader
import torch
import torch.nn.functional as F

# modules/ml/sentiment.py – no external models
def analyze_sentiment(text: str) -> dict:
    positive_words = {'good','great','awesome','love','like','interested','yes','excellent','happy'}
    negative_words = {'bad','terrible','hate','no','not','stop','unsubscribe','angry','worst'}
    text_lower = text.lower()
    pos = sum(1 for w in positive_words if w in text_lower)
    neg = sum(1 for w in negative_words if w in text_lower)
    if pos > neg:
        score = min(0.6 + (pos-neg)*0.1, 1.0)
        return {"label": "POSITIVE", "score": score}
    elif neg > pos:
        score = min(0.6 + (neg-pos)*0.1, 1.0)
        return {"label": "NEGATIVE", "score": score}
    return {"label": "NEUTRAL", "score": 0.5}