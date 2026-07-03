"""
knowledge.py — Stage 3: Embed claims into ChromaDB.

Retrieves all claims from DB, generates embeddings via OpenAI text-embedding-3-small,
stores in ChromaDB with full provenance metadata (paper_id, page_num, paragraph_id).
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import Claim, get_db
from services.openai_client import embed_texts
from services.chroma_store import store_claims, search_similar
from services.openai_client import embed_single

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


@router.post("/embed")
def embed_all_claims(db: Session = Depends(get_db)):
    """Embed all extracted claims into ChromaDB. Stage 3."""
    claims = db.query(Claim).filter(Claim.chroma_id == None).all()  # noqa: E711
    if not claims:
        already = db.query(Claim).count()
        return {"message": f"All {already} claims already embedded", "newly_embedded": 0}

    texts = [c.claim_text for c in claims]
    embeddings = embed_texts(db, texts)

    chroma_ids = [f"claim_{c.id}" for c in claims]
    metadatas = [
        {
            "paper_id": str(c.paper_id),
            "page_num": c.page_num,
            "paragraph_id": c.paragraph_id,
            "db_claim_id": c.id,
        }
        for c in claims
    ]

    store_claims(
        claim_ids=chroma_ids,
        embeddings=embeddings,
        texts=texts,
        metadatas=metadatas,
    )

    # Update chroma_id in DB
    for claim, chroma_id in zip(claims, chroma_ids):
        claim.chroma_id = chroma_id
    db.commit()

    logger.info(f"Embedded {len(claims)} claims into ChromaDB")
    return {"newly_embedded": len(claims), "total": db.query(Claim).count()}


@router.get("/search")
def search_claims(q: str, top_k: int = 5, db: Session = Depends(get_db)):
    """Search for similar claims by query text. Used in Stage 5."""
    query_embedding = embed_single(q)
    results = search_similar(query_embedding, top_k=top_k)
    return {"query": q, "results": results}


@router.get("/status")
def knowledge_status(db: Session = Depends(get_db)):
    """Return embedding status."""
    total = db.query(Claim).count()
    embedded = db.query(Claim).filter(Claim.chroma_id != None).count()  # noqa: E711
    return {"total_claims": total, "embedded": embedded, "pending": total - embedded}
