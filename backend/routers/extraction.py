"""
extraction.py — Stage 2 (literature) and Stage 4 (project) extraction.

Stage 2: One Claude call per literature paper → PaperExtraction JSON.
         Pydantic retry loop: retry once on failure, then drop only bad claims.
Stage 4: Same schema applied to the project file.
         Missing fields → clarification_requests (never inferred silently).
"""
from __future__ import annotations

import json
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import (
    Paper, Page, PaperMetadata, Claim, ClarificationRequest, get_db
)
from models.schemas import PaperRole, json_list_dumps
from services.claude_client import extract_paper

router = APIRouter(prefix="/extract", tags=["extraction"])
logger = logging.getLogger(__name__)


def _build_paper_text(db: Session, paper_id: int) -> str:
    """Assemble page blocks into a single annotated text string for the LLM."""
    pages = (
        db.query(Page)
        .filter(Page.paper_id == paper_id)
        .order_by(Page.page_num, Page.id)
        .all()
    )
    parts = []
    for page in pages:
        parts.append(f"[{page.paragraph_id}] {page.text}")
    return "\n\n".join(parts)


def _store_extraction(db: Session, paper_id: int, extraction, dropped_claims: list[dict]) -> None:
    """Persist extracted metadata, claims, and any dropped claim logs."""
    # Remove existing metadata/claims if re-running
    db.query(PaperMetadata).filter(PaperMetadata.paper_id == paper_id).delete()
    db.query(Claim).filter(Claim.paper_id == paper_id).delete()
    db.query(ClarificationRequest).filter(
        ClarificationRequest.paper_id == paper_id,
        ClarificationRequest.field_name.like("claim_%"),
    ).delete()
    db.flush()

    # Store metadata
    meta = PaperMetadata(
        paper_id=paper_id,
        title=extraction.title or "",
        authors_json=json_list_dumps(extraction.authors),
        year=extraction.year,
        problem_statement=extraction.problem_statement or "",
        objectives_json=json_list_dumps(extraction.objectives),
        methodology=extraction.methodology or "",
        algorithms_json=json_list_dumps(extraction.algorithms),
        datasets_json=json_list_dumps(extraction.datasets),
        results=extraction.results or "",
        limitations_json=json_list_dumps(extraction.limitations),
        future_work_json=json_list_dumps(extraction.future_work),
        claims_json=json_list_dumps([c.model_dump() for c in extraction.claims]),
    )
    db.add(meta)
    db.flush()

    # Store individual claims
    for claim in extraction.claims:
        db.add(Claim(
            paper_id=paper_id,
            page_num=claim.page,
            paragraph_id=claim.paragraph_id,
            claim_text=claim.text,
        ))

    # Log dropped claims as clarification requests
    for i, dropped in enumerate(dropped_claims):
        db.add(ClarificationRequest(
            paper_id=paper_id,
            field_name=f"claim_dropped_{i}",
            prompt=(
                f"A claim could not be validated and was dropped: "
                f"\"{dropped.get('claim', {}).get('text', 'unknown')[:200]}\". "
                f"Reason: {dropped.get('reason', 'unknown')}"
            ),
        ))

    db.commit()

    # Update paper status
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if paper:
        paper.status = "extracted"
        db.commit()


@router.post("/literature/{paper_id}")
def extract_literature_paper(paper_id: int, db: Session = Depends(get_db)):
    """Extract structured data from one literature paper. Stage 2."""
    paper = db.query(Paper).filter(
        Paper.id == paper_id,
        Paper.role == PaperRole.LITERATURE.value,
    ).first()
    if not paper:
        raise HTTPException(404, f"Literature paper {paper_id} not found")

    paper_text = _build_paper_text(db, paper_id)
    extraction, dropped = extract_paper(db, paper_text, paper_id)
    _store_extraction(db, paper_id, extraction, dropped)

    return {
        "paper_id": paper_id,
        "title": extraction.title,
        "claims_extracted": len(extraction.claims),
        "claims_dropped": len(dropped),
        "status": "extracted",
    }


@router.post("/literature/all")
def extract_all_literature(db: Session = Depends(get_db)):
    """Extract all literature papers. Called by pipeline orchestrator."""
    papers = db.query(Paper).filter(Paper.role == PaperRole.LITERATURE.value).all()
    results = []
    for paper in papers:
        paper_text = _build_paper_text(db, paper.id)
        extraction, dropped = extract_paper(db, paper_text, paper.id)
        _store_extraction(db, paper.id, extraction, dropped)
        results.append({
            "paper_id": paper.id,
            "title": extraction.title,
            "claims_extracted": len(extraction.claims),
            "claims_dropped": len(dropped),
        })
    return {"papers_processed": len(results), "results": results}


@router.post("/project")
def extract_project(db: Session = Depends(get_db)):
    """Extract structured data from the project file. Stage 4."""
    project = db.query(Paper).filter(Paper.role == PaperRole.PROJECT.value).first()
    if not project:
        raise HTTPException(404, "No project file uploaded")

    paper_text = _build_paper_text(db, project.id)
    extraction, dropped = extract_paper(db, paper_text, project.id)

    # For project: surface missing fields as clarification requests
    missing_fields = []
    if not extraction.problem_statement.strip():
        missing_fields.append(("problem_statement", "What is the main problem your project addresses?"))
    if not extraction.methodology.strip():
        missing_fields.append(("methodology", "Describe the methodology or approach you used."))
    if not extraction.results.strip():
        missing_fields.append(("results", "What were the main results or outcomes of your project?"))
    if not extraction.title.strip():
        missing_fields.append(("title", "What is the title of your project?"))

    # Remove old clarifications for this project
    db.query(ClarificationRequest).filter(
        ClarificationRequest.paper_id == project.id
    ).delete()
    db.flush()

    for field_name, prompt in missing_fields:
        db.add(ClarificationRequest(
            paper_id=project.id,
            field_name=field_name,
            prompt=prompt,
        ))

    _store_extraction(db, project.id, extraction, dropped)

    return {
        "paper_id": project.id,
        "title": extraction.title,
        "claims_extracted": len(extraction.claims),
        "clarification_requests": len(missing_fields),
        "missing_fields": [f[0] for f in missing_fields],
        "status": "extracted",
    }


@router.get("/clarifications")
def get_clarifications(db: Session = Depends(get_db)):
    """Return all unresolved clarification requests."""
    items = db.query(ClarificationRequest).filter(
        ClarificationRequest.resolved == False
    ).all()
    return {
        "count": len(items),
        "clarifications": [
            {
                "id": c.id,
                "paper_id": c.paper_id,
                "field_name": c.field_name,
                "prompt": c.prompt,
                "user_response": c.user_response,
                "resolved": c.resolved,
            }
            for c in items
        ],
    }


@router.post("/clarifications/{clarification_id}")
def submit_clarification(
    clarification_id: int,
    response: str,
    db: Session = Depends(get_db),
):
    """Submit a user response to a clarification request."""
    item = db.query(ClarificationRequest).filter(
        ClarificationRequest.id == clarification_id
    ).first()
    if not item:
        raise HTTPException(404, "Clarification request not found")

    item.user_response = response
    item.resolved = True

    # If it's a core field, update the metadata record too
    meta = db.query(PaperMetadata).filter(PaperMetadata.paper_id == item.paper_id).first()
    if meta:
        field_map = {
            "problem_statement": "problem_statement",
            "methodology": "methodology",
            "results": "results",
            "title": "title",
        }
        if item.field_name in field_map:
            setattr(meta, field_map[item.field_name], response)

    db.commit()
    return {"status": "resolved", "clarification_id": clarification_id}
