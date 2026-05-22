from .model_loader import ModelLoader
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

def get_embedding(text: str) -> np.ndarray:
    model = ModelLoader.get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True)
    # Optionally unload after use, but we may need for multiple checks – keep for batch
    return embedding

def find_duplicates(lead_data: dict, existing_embeddings: list, threshold=0.85):
    """
    lead_data: {'name': str, 'email': str, 'phone': str}
    existing_embeddings: list of (lead_id, embedding_vector)
    Returns list of matching lead_ids
    """
    # Combine fields into a single string
    text = f"{lead_data.get('name','')} {lead_data.get('email','')} {lead_data.get('phone','')}"
    query_emb = get_embedding(text).reshape(1, -1)
    matches = []
    for lead_id, emb in existing_embeddings:
        sim = cosine_similarity(query_emb, emb.reshape(1, -1))[0][0]
        if sim > threshold:
            matches.append((lead_id, sim))
    # Unload model after batch
    ModelLoader.unload_embedding()
    return sorted(matches, key=lambda x: x[1], reverse=True)