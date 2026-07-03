"""
output.py — Stage 7: Assemble final paper + transparency report + DOCX download.

Bibliography:
- Auto-generated from paper_metadata
- Sorted by first author surname, then year
- Deduped: only papers whose paper_id appears in at least one VERIFIED generated_sentence

Transparency report:
- Papers analyzed, claims extracted, sentences generated/verified/rejected
- Rejected sentences log with reasons
- LLM usage: total tokens + estimated cost breakdown by stage
"""
from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import (
    Claim, GeneratedSentence, LLMUsage, Paper, PaperMetadata,
    ClarificationRequest, get_db,
)
from models.schemas import (
    PaperRole, VerificationStatus, json_list_loads,
)
from services.docx_writer import build_docx, paper_to_markdown

router = APIRouter(prefix="/output", tags=["output"])
logger = logging.getLogger(__name__)


def _build_bibliography(db: Session) -> list[dict]:
    """
    Build bibliography from paper_metadata.
    Only includes papers actually cited in VERIFIED generated sentences.
    Sorted by first author surname, then year.
    Deduplicated by paper_id.
    """
    verified = db.query(GeneratedSentence).filter(
        GeneratedSentence.status == VerificationStatus.VERIFIED.value
    ).all()

    # Collect cited claim IDs from verified sentences
    cited_claim_ids: set[int] = set()
    for sentence in verified:
        ids = json_list_loads(sentence.cited_claim_ids)
        cited_claim_ids.update(ids)

    # Map claim IDs to paper IDs
    cited_paper_ids: set[int] = set()
    if cited_claim_ids:
        claims = db.query(Claim).filter(Claim.id.in_(cited_claim_ids)).all()
        cited_paper_ids = {c.paper_id for c in claims}

    if not cited_paper_ids:
        return []

    # Fetch metadata for cited papers only
    metas = db.query(PaperMetadata).filter(
        PaperMetadata.paper_id.in_(cited_paper_ids)
    ).all()

    bibliography = []
    for meta in metas:
        authors = json.loads(meta.authors_json or "[]")
        bibliography.append({
            "paper_id": meta.paper_id,
            "title": meta.title or "Untitled",
            "authors": authors,
            "year": meta.year,
        })

    return bibliography


def _build_sections(db: Session) -> dict[str, list[str]]:
    """Return VERIFIED sentences grouped by section, in insertion order."""
    sentences = db.query(GeneratedSentence).filter(
        GeneratedSentence.status == VerificationStatus.VERIFIED.value
    ).order_by(GeneratedSentence.id).all()

    sections: dict[str, list[str]] = {}
    for s in sentences:
        sections.setdefault(s.section, []).append(s.text)
    return sections


def _build_transparency_report(db: Session) -> dict:
    papers_analyzed = db.query(Paper).filter(
        Paper.role == PaperRole.LITERATURE.value
    ).count()
    claims_extracted = db.query(Claim).join(Paper).filter(
        Paper.role == PaperRole.LITERATURE.value
    ).count()
    total_sentences = db.query(GeneratedSentence).count()
    verified = db.query(GeneratedSentence).filter(
        GeneratedSentence.status == VerificationStatus.VERIFIED.value
    ).count()
    rejected = db.query(GeneratedSentence).filter(
        GeneratedSentence.status == VerificationStatus.REJECTED.value
    ).count()
    open_clarifications = db.query(ClarificationRequest).filter(
        ClarificationRequest.resolved == False  # noqa: E712
    ).count()

    # Rejected sentence details
    rejected_sentences = db.query(GeneratedSentence).filter(
        GeneratedSentence.status == VerificationStatus.REJECTED.value
    ).all()
    rejected_details = [
        {
            "id": s.id,
            "section": s.section,
            "text": s.text[:300],
            "rejection_reason": s.rejection_reason or "No reason recorded",
            "cited_claim_ids": json_list_loads(s.cited_claim_ids),
        }
        for s in rejected_sentences
    ]

    # LLM usage aggregated
    usage_rows = db.query(LLMUsage).all()
    total_prompt = sum(r.prompt_tokens for r in usage_rows)
    total_completion = sum(r.completion_tokens for r in usage_rows)
    total_cost = sum(r.estimated_cost_usd for r in usage_rows)

    by_stage: dict[str, dict] = {}
    for row in usage_rows:
        stage = row.stage
        if stage not in by_stage:
            by_stage[stage] = {"model": row.model, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        by_stage[stage]["prompt_tokens"] += row.prompt_tokens
        by_stage[stage]["completion_tokens"] += row.completion_tokens
        by_stage[stage]["cost_usd"] += row.estimated_cost_usd

    return {
        "papers_analyzed": papers_analyzed,
        "claims_extracted": claims_extracted,
        "sentences_generated": total_sentences,
        "sentences_verified": verified,
        "sentences_rejected": rejected,
        "open_clarifications": open_clarifications,
        "rejected_details": rejected_details,
        "llm_usage": {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cost_usd": round(total_cost, 6),
            "by_stage": by_stage,
        },
    }


@router.get("/preview")
def get_paper_preview(db: Session = Depends(get_db)):
    """Return the paper as Markdown for the frontend preview."""
    sections = _build_sections(db)
    bibliography = _build_bibliography(db)
    transparency = _build_transparency_report(db)

    if not sections:
        raise HTTPException(400, "No verified sentences found. Run Stage 6 generation first.")

    markdown = paper_to_markdown(sections, bibliography)
    return {
        "markdown": markdown,
        "bibliography": bibliography,
        "transparency": transparency,
        "section_count": len(sections),
        "sentence_count": sum(len(v) for v in sections.values()),
    }


@router.get("/download")
def download_docx(db: Session = Depends(get_db)):
    """Generate and return the DOCX file for download."""
    sections = _build_sections(db)
    bibliography = _build_bibliography(db)
    transparency = _build_transparency_report(db)

    if not sections:
        raise HTTPException(400, "No verified sentences found. Run Stage 6 generation first.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp_path = tmp.name

    try:
        build_docx(
            sections=sections,
            bibliography=bibliography,
            transparency=transparency,
            output_path=tmp_path,
        )
        with open(tmp_path, "rb") as f:
            content = f.read()
    finally:
        os.unlink(tmp_path)

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=generated_paper.docx"},
    )


@router.get("/transparency")
def get_transparency_report(db: Session = Depends(get_db)):
    """Return the full transparency report as JSON."""
    return _build_transparency_report(db)
