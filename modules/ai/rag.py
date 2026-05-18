import os
import uuid
import numpy as np
from fastembed import TextEmbedding
import chromadb
from sqlalchemy import text
from modules.common.database import sync_engine
from modules.common.logger import get_logger

logger = get_logger(__name__)

_client_cache = {}
_embedding_model = None


# ✅ Load embedding model (lazy)
def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")  # 🔥 lighter model
    return _embedding_model


# ✅ Safe cosine similarity
def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)

    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0

    return float(np.dot(a, b) / denom)


# ✅ Chroma client
def get_chroma_client(org_id: str, persist_dir: str = "./chroma_db"):
    if org_id not in _client_cache:
        store_path = os.path.join(persist_dir, str(org_id))
        os.makedirs(store_path, exist_ok=True)
        _client_cache[org_id] = chromadb.PersistentClient(path=store_path)
    return _client_cache[org_id]


# ✅ Smart chunking (prevents huge chunks)
def split_text(content, chunk_size=500):
    words = content.split()
    chunks = []

    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)

    return chunks


# ✅ Index document
def index_document(doc_id: uuid.UUID, org_id: str, file_path: str, file_type: str):
    logger.info(f"Indexing {file_path} for org {org_id}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        chunks = split_text(content)

        if not chunks:
            chunks = [content[:1000]]

        model = get_embedding_model()
        embeddings = list(model.embed(chunks))

        client = get_chroma_client(org_id)

        collection = client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )

        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]

        collection.add(
            documents=chunks,
            embeddings=[e.tolist() for e in embeddings],
            ids=ids,
            metadatas=[
                {"doc_id": str(doc_id), "org_id": str(org_id), "chunk": i}
                for i in range(len(chunks))
            ]
        )

        # Save full content for keyword search
        with sync_engine.connect() as conn:
            conn.execute(
                text("UPDATE knowledge_documents SET content = :content WHERE id = :doc_id"),
                {"content": content, "doc_id": doc_id}
            )
            conn.commit()

        logger.info(f"Indexed {len(chunks)} chunks for doc {doc_id}")

    except Exception as e:
        logger.error(f"Indexing failed: {e}")


# ✅ Hybrid search
def hybrid_search(org_id: str, query: str, k: int = 10):
    chunks = []

    # 🔹 Vector search
    try:
        model = get_embedding_model()
        query_embedding = list(model.embed([query]))[0].tolist()

        client = get_chroma_client(org_id)

        try:
            collection = client.get_collection("documents")
        except Exception:
            return []

        results = collection.query(query_embeddings=[query_embedding], n_results=k)

        if results and results.get("documents"):
            chunks.extend(results["documents"][0])

    except Exception as e:
        logger.error(f"Vector search failed: {e}")

    # 🔹 Keyword search
    try:
        with sync_engine.connect() as conn:
            keyword_results = conn.execute(
                text("""
                    SELECT content
                    FROM knowledge_documents
                    WHERE organization_id = :org_id
                      AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)
                    ORDER BY ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) DESC
                    LIMIT :k
                """),
                {"org_id": org_id, "query": query, "k": k}
            ).fetchall()

            chunks.extend([row.content for row in keyword_results])

    except Exception as e:
        logger.error(f"Keyword search failed: {e}")

    # 🔹 Deduplicate
    seen = set()
    unique_chunks = []

    for chunk in chunks:
        if chunk not in seen:
            seen.add(chunk)
            unique_chunks.append(chunk)

    return unique_chunks[:k]


# ✅ Final search (rerank)
def search_knowledge(org_id: str, query: str, k: int = 3) -> list:
    candidates = hybrid_search(org_id, query, k=k * 3)

    if not candidates:
        return []

    model = get_embedding_model()

    query_embedding = list(model.embed([query]))[0]
    doc_embeddings = list(model.embed(candidates))

    scores = [
        cosine_similarity(query_embedding, emb)
        for emb in doc_embeddings
    ]

    scored = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)

    return [doc for doc, _ in scored[:k]]