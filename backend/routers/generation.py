"""
generation.py — Stage 6a (Claude draft) + Stage 6b (GPT-4o-mini verification gate).

Core rule: a sentence only makes it to the output if Stage 6b confirms
the cited source text entails it. Failed sentences are DROPPED and logged —
never silently reworded or kept.

Stage 6b uses a separate provider (OpenAI) to independently check Stage 6a
(Claude) output. This is intentional — same-model self-verification risks
rationalizing its own hallucinated output.
"""
from __future__ import annotations

import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import Claim, GeneratedSentence, Paper, PaperMetadata, get_db
from models.schemas import PaperRole, VerificationStatus, json_list_dumps, json_list_loads
from services.claude_client import generate_paper_draft
from services.openai_client import verify_sentences_batch

router = APIRouter(prefix="/generate", tags=["generation"])
logger = logging.getLogger(__name__)


def _build_project_context(db: Session) -> str:
    """Build a text summary of the project from extracted metadata + clarifications."""
    from database import ClarificationRequest
    project = db.query(Paper).filter(Paper.role == PaperRole.PROJECT.value).first()
    if not project:
        return ""

    meta = db.query(PaperMetadata).filter(PaperMetadata.paper_id == project.id).first()
    clarifications = db.query(ClarificationRequest).filter(
        ClarificationRequest.paper_id == project.id,
        ClarificationRequest.resolved == True,
    ).all()

    context_parts = [f"Project: {project.filename}"]
    if meta:
        context_parts.append(f"Title: {meta.title}")
        context_parts.append(f"Problem: {meta.problem_statement}")
        context_parts.append(f"Methodology: {meta.methodology}")
        context_parts.append(f"Results: {meta.results}")

    for c in clarifications:
        context_parts.append(f"{c.field_name}: {c.user_response}")

    return "\n".join(context_parts)


@router.post("/run")
def run_generation(db: Session = Depends(get_db)):
    """
    Stage 6a + 6b: Generate paper draft then verify each sentence independently.
    Rejected sentences are logged, never reworded.
    """
    # Gather all literature claims with provenance
    claims = db.query(Claim).join(Paper).filter(
        Paper.role == PaperRole.LITERATURE.value
    ).all()
    if not claims:
        raise HTTPException(400, "No literature claims found. Run Stages 1–3 first.")

    claims_payload = [
        {
            "id": c.id,
            "text": c.claim_text,
            "paper_id": c.paper_id,
            "page": c.page_num,
            "paragraph_id": c.paragraph_id,
        }
        for c in claims
    ]

    project_context = _build_project_context(db)

    # ── Stage 6a: Claude drafts the paper ────────────────────────────────────
    logger.info("Stage 6a: Generating paper draft with Claude...")
    draft_sections = generate_paper_draft(db, claims_payload, project_context)

    # Clear previous generated sentences
    db.query(GeneratedSentence).delete()
    db.flush()

    # Store all sentences as PENDING
    all_sentences: list[GeneratedSentence] = []
    for section, sentences in draft_sections.items():
        for s in sentences:
            sentence = GeneratedSentence(
                section=section,
                text=s["text"],
                cited_claim_ids=json_list_dumps(s["cited_claim_ids"]),
                status=VerificationStatus.PENDING.value,
            )
            db.add(sentence)
            db.flush()
            all_sentences.append(sentence)

    db.commit()
    logger.info(f"Stage 6a complete: {len(all_sentences)} sentences drafted")

    # ── Stage 6b: GPT-4o-mini verifies each sentence ─────────────────────────
    logger.info("Stage 6b: Verifying sentences with GPT-4o-mini...")

    # Build a lookup: claim_id → claim_text for source fetching
    claim_lookup = {c.id: c.claim_text for c in claims}

    # Prepare verification items — batched by 10
    verify_items: list[dict] = []
    for sentence in all_sentences:
        cited_ids = json_list_loads(sentence.cited_claim_ids)
        source_texts = [claim_lookup.get(cid, "") for cid in cited_ids if cid in claim_lookup]

        if not cited_ids or not source_texts:
            # No citations → auto-reject (core rule: no evidence, no sentence)
            sentence.status = VerificationStatus.REJECTED.value
            sentence.rejection_reason = "No cited claims found — sentence has no evidence anchor"
            continue

        verify_items.append({
            "sentence_id": sentence.id,
            "sentence": sentence.text,
            "source_texts": source_texts,
        })

    db.commit()

    # Process in batches of stage6b_batch_size
    batch_size = settings.stage6b_batch_size
    verified_count = 0
    rejected_count = 0

    for i in range(0, len(verify_items), batch_size):
        batch = verify_items[i:i + batch_size]
        verification = verify_sentences_batch(db, batch)

        for result in verification.verifications:
            sentence = db.query(GeneratedSentence).filter(
                GeneratedSentence.id == result.sentence_id
            ).first()
            if not sentence:
                continue

            if result.verdict:
                sentence.status = VerificationStatus.VERIFIED.value
                verified_count += 1
            else:
                sentence.status = VerificationStatus.REJECTED.value
                sentence.rejection_reason = result.reason
                rejected_count += 1

    db.commit()
    logger.info(
        f"Stage 6b complete: {verified_count} verified, {rejected_count} rejected "
        f"out of {len(verify_items)} checked"
    )

    return {
        "sentences_drafted": len(all_sentences),
        "sentences_verified": verified_count,
        "sentences_rejected": rejected_count,
        "auto_rejected_no_citation": len(all_sentences) - len(verify_items),
    }


@router.get("/sentences")
def get_generated_sentences(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """Return generated sentences, optionally filtered by status."""
    query = db.query(GeneratedSentence)
    if status:
        try:
            vs = VerificationStatus(status)
            query = query.filter(GeneratedSentence.status == vs.value)
        except ValueError:
            raise HTTPException(400, f"Invalid status '{status}'. Use: pending, verified, rejected")

    sentences = query.all()
    return {
        "count": len(sentences),
        "sentences": [
            {
                "id": s.id,
                "section": s.section,
                "text": s.text,
                "cited_claim_ids": json_list_loads(s.cited_claim_ids),
                "status": s.status,
                "rejection_reason": s.rejection_reason,
            }
            for s in sentences
        ],
    }
