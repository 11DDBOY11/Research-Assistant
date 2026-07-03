"""
comparison.py — Stage 5: Compare project claims against literature.

For each project claim:
1. Embed the claim text → search Chroma for top-5 similar literature claims
2. Batch up to 10 claims per Claude call → classify: matches_existing /
   partial_overlap / not_found_in_corpus

Avoids all-vs-all combinatorial explosion by doing per-claim top-5 search first.
"""
from __future__ import annotations

import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import Claim, Paper, ProjectClaim, get_db
from models.schemas import PaperRole, json_list_dumps
from services.chroma_store import search_similar
from services.claude_client import compare_claims_batch
from services.openai_client import embed_single

router = APIRouter(prefix="/compare", tags=["comparison"])
logger = logging.getLogger(__name__)


@router.post("/run")
def run_comparison(db: Session = Depends(get_db)):
    """
    Stage 5: Compare all project claims against literature corpus.
    Uses batched Claude calls (up to 10 claims per call).
    """
    # Get project paper
    project = db.query(Paper).filter(Paper.role == PaperRole.PROJECT.value).first()
    if not project:
        raise HTTPException(404, "No project file found")

    # Get project claims (stored in Claim table with project paper_id)
    project_claims = db.query(Claim).filter(Claim.paper_id == project.id).all()
    if not project_claims:
        raise HTTPException(400, "No project claims found. Run Stage 4 extraction first.")

    # Clear existing project_claims
    db.query(ProjectClaim).filter(ProjectClaim.paper_id == project.id).delete()
    db.flush()

    # Step 1: For each project claim, get top-5 similar literature claims
    evidence_map: dict[int, list[dict]] = {}  # claim.id → similar results
    for claim in project_claims:
        query_embedding = embed_single(claim.claim_text)
        similar = search_similar(query_embedding, top_k=5)
        evidence_map[claim.id] = similar

    # Step 2: Batch Claude comparison calls (up to 10 claims per call)
    batch_size = settings.stage5_batch_size
    all_results = []

    for i in range(0, len(project_claims), batch_size):
        batch = project_claims[i:i + batch_size]
        claims_payload = [{"id": c.id, "text": c.claim_text} for c in batch]
        evidence_payload = [
            {
                "project_claim_id": c.id,
                "similar": [
                    {
                        "claim_text": r["text"],
                        "paper_id": r["metadata"].get("paper_id", "unknown"),
                        "page_num": r["metadata"].get("page_num"),
                        "paragraph_id": r["metadata"].get("paragraph_id"),
                    }
                    for r in evidence_map.get(c.id, [])
                ],
            }
            for c in batch
        ]

        batch_output = compare_claims_batch(db, claims_payload, evidence_payload)
        all_results.extend(batch_output.comparisons)

    # Step 3: Store results
    for comp in all_results:
        db.add(ProjectClaim(
            paper_id=project.id,
            claim_text=next(
                (c.claim_text for c in project_claims if c.id == comp.project_claim_id),
                "",
            ),
            comparison_result=comp.result.value,
            matched_paper_ids=json_list_dumps(comp.matched_paper_ids),
            reasoning=comp.reasoning,
        ))

    db.commit()
    logger.info(f"Stage 5 complete: {len(all_results)} project claims compared")

    # Summary
    from models.schemas import ComparisonResult
    counts = {r.value: 0 for r in ComparisonResult}
    for r in all_results:
        counts[r.result.value] += 1

    return {
        "total_compared": len(all_results),
        "matches_existing": counts.get("matches_existing", 0),
        "partial_overlap": counts.get("partial_overlap", 0),
        "not_found_in_corpus": counts.get("not_found_in_corpus", 0),
    }


@router.get("/results")
def get_comparison_results(db: Session = Depends(get_db)):
    """Return all project claim comparison results."""
    results = db.query(ProjectClaim).all()
    return {
        "count": len(results),
        "results": [
            {
                "id": r.id,
                "claim_text": r.claim_text[:200],
                "comparison_result": r.comparison_result,
                "matched_paper_ids": json.loads(r.matched_paper_ids or "[]"),
                "reasoning": r.reasoning,
            }
            for r in results
        ],
    }
