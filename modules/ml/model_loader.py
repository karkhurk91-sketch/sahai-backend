import gc
import torch
from functools import lru_cache
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from sentence_transformers import SentenceTransformer

class ModelLoader:
    _sentiment_model = None
    _sentiment_tokenizer = None
    _embedding_model = None

    @classmethod
    def get_sentiment_model(cls):
        if cls._sentiment_model is None:
            model_name = "lxyuan/distilbert-base-multilingual-cased-sentiments-student" 
            cls._sentiment_tokenizer = AutoTokenizer.from_pretrained(model_name)
            cls._sentiment_model = AutoModelForSequenceClassification.from_pretrained(model_name)
            cls._sentiment_model.eval()
            cls._sentiment_model.to('cpu')
        return cls._sentiment_model, cls._sentiment_tokenizer

    @classmethod
    def get_embedding_model(cls):
        if cls._embedding_model is None:
            cls._embedding_model = SentenceTransformer('all-MiniLM-L12-v2', device='cpu')
        return cls._embedding_model

    @classmethod
    def unload_sentiment(cls):
        cls._sentiment_model = None
        cls._sentiment_tokenizer = None
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    @classmethod
    def unload_embedding(cls):
        cls._embedding_model = None
        gc.collect()