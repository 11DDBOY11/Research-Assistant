"""
chroma_store.py — ChromaDB wrapper for Stage 3 (store) and Stage 5 (retrieval).

Uses a persistent local ChromaDB at settings.chroma_path.
Embeddings are pre-computed by openai_client.py (text-embedding-3-small)
and passed directly — ChromaDB is used purely as a vector index, not for embedding.
"""
from __future__ import annotations

import logging

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings

logger = logging.getLogger(__name__)

_client: chromadb.PersistentClient | None = None
COLLECTION_NAME = "research_claims"


def _get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection() -> chromadb.Collection:
    c = _get_chroma_client()
    return c.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def store_claims(
    claim_ids: list[str],        # unique string IDs for ChromaDB
    embeddings: list[list[float]],
    texts: list[str],
    metadatas: list[dict],       # {paper_id, page_num, paragraph_id, db_claim_id}
) -> None:
    """
    Upsert claims into the ChromaDB collection.
    Uses upsert to be idempotent (safe to re-run).
    """
    if not claim_ids:
        return
    collection = get_collection()
    collection.upsert(
        ids=claim_ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    logger.info(f"Stored {len(claim_ids)} claims in ChromaDB")


def search_similar(
    query_embedding: list[float],
    top_k: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """
    Find top-k most similar claims to the query embedding.
    Returns list of {id, text, metadata, distance}.
    """
    collection = get_collection()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count() or 1),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    output: list[dict] = []
    if not results["ids"] or not results["ids"][0]:
        return output

    for i, chroma_id in enumerate(results["ids"][0]):
        output.append({
            "chroma_id": chroma_id,
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return output


def reset_collection() -> None:
    """Drop and recreate the collection. Used for fresh sessions."""
    c = _get_chroma_client()
    try:
        c.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    c.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("ChromaDB collection reset")
