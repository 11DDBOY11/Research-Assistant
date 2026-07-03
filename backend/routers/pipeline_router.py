"""
pipeline_router.py — Manual pipeline trigger + SSE progress stream.

The pipeline runs in a background task after the user clicks "Run Pipeline".
Progress is streamed to the frontend via SSE. Stages run sequentially.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import Paper, get_db, SessionLocal
from models.schemas import PaperRole
from services.pipeline import create_run, sse_stream, emit, emit_done, emit_error, cleanup_run

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)

TOTAL_STAGES = 7


async def _run_pipeline(run_id: str):
    """
    Execute all 7 stages sequentially, emitting progress via SSE.
    Each stage is called via the existing router logic (direct function calls).
    """
    db = SessionLocal()
    try:
        # Import routers inline to avoid circular imports
        from routers.extraction import extract_all_literature, extract_project
        from routers.knowledge import embed_all_claims
        from routers.comparison import run_comparison
        from routers.generation import run_generation

        # Stage 1 already done (upload) — confirm
        lit_count = db.query(Paper).filter(Paper.role == PaperRole.LITERATURE.value).count()
        proj_count = db.query(Paper).filter(Paper.role == PaperRole.PROJECT.value).count()

        if lit_count == 0 or proj_count == 0:
            await emit_error(run_id, "Upload at least 1 literature file and 1 project file first.")
            return

        await emit(run_id, 1, TOTAL_STAGES, f"Files ready: {lit_count} literature + {proj_count} project")

        # Stage 2: Extract literature
        await emit(run_id, 2, TOTAL_STAGES, f"Extracting structured data from {lit_count} papers...")
        papers = db.query(Paper).filter(Paper.role == PaperRole.LITERATURE.value).all()
        for i, paper in enumerate(papers, 1):
            await emit(run_id, 2, TOTAL_STAGES, f"Extracting paper {i}/{lit_count}: {paper.filename}")
            # Use internal function call (same DB session)
            from routers.extraction import _build_paper_text, _store_extraction
            from services.claude_client import extract_paper as _extract_paper
            paper_text = _build_paper_text(db, paper.id)
            extraction, dropped = _extract_paper(db, paper_text, paper.id)
            _store_extraction(db, paper.id, extraction, dropped)

        await emit(run_id, 2, TOTAL_STAGES, f"✓ Extraction complete for all {lit_count} papers")

        # Stage 3: Embed claims
        await emit(run_id, 3, TOTAL_STAGES, "Building knowledge store (embedding claims)...")
        from routers.knowledge import embed_all_claims as _embed
        from database import Claim
        claims_to_embed = db.query(Claim).filter(Claim.chroma_id == None).all()  # noqa: E711
        if claims_to_embed:
            from services.openai_client import embed_texts
            from services.chroma_store import store_claims
            texts = [c.claim_text for c in claims_to_embed]
            embeddings = embed_texts(db, texts)
            chroma_ids = [f"claim_{c.id}" for c in claims_to_embed]
            metadatas = [
                {"paper_id": str(c.paper_id), "page_num": c.page_num,
                 "paragraph_id": c.paragraph_id, "db_claim_id": c.id}
                for c in claims_to_embed
            ]
            store_claims(chroma_ids, embeddings, texts, metadatas)
            for claim, cid in zip(claims_to_embed, chroma_ids):
                claim.chroma_id = cid
            db.commit()
        await emit(run_id, 3, TOTAL_STAGES, f"✓ Embedded {len(claims_to_embed)} claims")

        # Stage 4: Extract project
        await emit(run_id, 4, TOTAL_STAGES, "Analyzing project file...")
        from routers.extraction import _build_paper_text as _bpt, _store_extraction as _se
        from services.claude_client import extract_paper as _ep
        from database import ClarificationRequest
        project = db.query(Paper).filter(Paper.role == PaperRole.PROJECT.value).first()
        project_text = _bpt(db, project.id)
        project_extraction, dropped_proj = _ep(db, project_text, project.id)

        missing_fields = []
        if not project_extraction.problem_statement.strip():
            missing_fields.append(("problem_statement", "What is the main problem your project addresses?"))
        if not project_extraction.methodology.strip():
            missing_fields.append(("methodology", "Describe the methodology or approach you used."))
        if not project_extraction.results.strip():
            missing_fields.append(("results", "What were the main results or outcomes of your project?"))
        if not project_extraction.title.strip():
            missing_fields.append(("title", "What is the title of your project?"))

        db.query(ClarificationRequest).filter(
            ClarificationRequest.paper_id == project.id
        ).delete()
        for field_name, prompt in missing_fields:
            db.add(ClarificationRequest(paper_id=project.id, field_name=field_name, prompt=prompt))

        _se(db, project.id, project_extraction, dropped_proj)
        clarification_msg = f" ({len(missing_fields)} fields need your input)" if missing_fields else ""
        await emit(run_id, 4, TOTAL_STAGES, f"✓ Project analyzed{clarification_msg}",
                   {"clarifications_needed": len(missing_fields)})

        # Pause here to let user fill clarifications? No — pipeline continues;
        # clarifications are surfaced in UI asynchronously and can be filled later.
        # The generation stage uses whatever is in the DB at run time.

        # Stage 5: Compare
        await emit(run_id, 5, TOTAL_STAGES, "Comparing project claims against literature...")
        from routers.comparison import run_comparison as _compare
        from database import ProjectClaim
        from models.schemas import json_list_dumps
        from services.chroma_store import search_similar
        from services.openai_client import embed_single
        from services.claude_client import compare_claims_batch
        from config import settings

        project_claims = db.query(Claim).filter(Claim.paper_id == project.id).all()
        db.query(ProjectClaim).filter(ProjectClaim.paper_id == project.id).delete()
        db.flush()

        if project_claims:
            evidence_map = {}
            for claim in project_claims:
                qe = embed_single(claim.claim_text)
                evidence_map[claim.id] = search_similar(qe, top_k=5)

            batch_size = settings.stage5_batch_size
            for i in range(0, len(project_claims), batch_size):
                batch = project_claims[i:i + batch_size]
                claims_payload = [{"id": c.id, "text": c.claim_text} for c in batch]
                evidence_payload = [
                    {"project_claim_id": c.id, "similar": [
                        {"claim_text": r["text"], "paper_id": r["metadata"].get("paper_id", "unknown")}
                        for r in evidence_map.get(c.id, [])
                    ]}
                    for c in batch
                ]
                batch_output = compare_claims_batch(db, claims_payload, evidence_payload)
                for comp in batch_output.comparisons:
                    db.add(ProjectClaim(
                        paper_id=project.id,
                        claim_text=next((c.claim_text for c in batch if c.id == comp.project_claim_id), ""),
                        comparison_result=comp.result.value,
                        matched_paper_ids=json_list_dumps(comp.matched_paper_ids),
                        reasoning=comp.reasoning,
                    ))
            db.commit()

        await emit(run_id, 5, TOTAL_STAGES, f"✓ Compared {len(project_claims)} project claims")

        # Stage 6: Generate + Verify
        await emit(run_id, 6, TOTAL_STAGES, "Generating paper draft (Claude)...")
        from routers.generation import run_generation as _gen
        from database import GeneratedSentence
        from services.claude_client import generate_paper_draft
        from services.openai_client import verify_sentences_batch
        from models.schemas import VerificationStatus

        lit_claims = db.query(Claim).join(Paper).filter(Paper.role == PaperRole.LITERATURE.value).all()
        claims_payload_gen = [
            {"id": c.id, "text": c.claim_text, "paper_id": c.paper_id,
             "page": c.page_num, "paragraph_id": c.paragraph_id}
            for c in lit_claims
        ]
        from routers.generation import _build_project_context
        project_context = _build_project_context(db)
        draft_sections = generate_paper_draft(db, claims_payload_gen, project_context)

        db.query(GeneratedSentence).delete()
        db.flush()
        all_sentences = []
        for section, sentences in draft_sections.items():
            for s in sentences:
                sent = GeneratedSentence(
                    section=section, text=s["text"],
                    cited_claim_ids=json_list_dumps(s["cited_claim_ids"]),
                    status=VerificationStatus.PENDING.value,
                )
                db.add(sent)
                db.flush()
                all_sentences.append(sent)
        db.commit()

        await emit(run_id, 6, TOTAL_STAGES,
                   f"Verifying {len(all_sentences)} sentences (GPT-4o-mini)...")

        claim_lookup = {c.id: c.claim_text for c in lit_claims}
        from models.schemas import json_list_loads
        verify_items = []
        for sentence in all_sentences:
            cited_ids = json_list_loads(sentence.cited_claim_ids)
            source_texts = [claim_lookup.get(cid, "") for cid in cited_ids if cid in claim_lookup]
            if not cited_ids or not source_texts:
                sentence.status = VerificationStatus.REJECTED.value
                sentence.rejection_reason = "No cited claims — auto-rejected"
                continue
            verify_items.append({
                "sentence_id": sentence.id, "sentence": sentence.text,
                "source_texts": source_texts,
            })
        db.commit()

        verified_count = 0
        rejected_count = 0
        for i in range(0, len(verify_items), settings.stage6b_batch_size):
            batch = verify_items[i:i + settings.stage6b_batch_size]
            result = verify_sentences_batch(db, batch)
            for v in result.verifications:
                sent = db.query(GeneratedSentence).filter(GeneratedSentence.id == v.sentence_id).first()
                if not sent:
                    continue
                if v.verdict:
                    sent.status = VerificationStatus.VERIFIED.value
                    verified_count += 1
                else:
                    sent.status = VerificationStatus.REJECTED.value
                    sent.rejection_reason = v.reason
                    rejected_count += 1
        db.commit()

        await emit(run_id, 6, TOTAL_STAGES,
                   f"✓ {verified_count} sentences verified, {rejected_count} rejected")

        # Stage 7: Output ready
        await emit(run_id, 7, TOTAL_STAGES, "✓ Pipeline complete — paper ready for download!")
        await emit_done(run_id)

    except Exception as e:
        logger.exception(f"Pipeline error in run {run_id}: {e}")
        await emit_error(run_id, str(e))
    finally:
        db.close()
        cleanup_run(run_id)


@router.post("/start")
async def start_pipeline(background_tasks: BackgroundTasks):
    """
    Manual trigger — user clicks 'Run Pipeline'.
    Returns run_id immediately; client subscribes to /pipeline/stream/{run_id} for progress.
    """
    run_id = str(uuid.uuid4())
    create_run(run_id)
    background_tasks.add_task(_run_pipeline, run_id)
    return {"run_id": run_id, "message": "Pipeline started — connect to SSE stream for progress"}


@router.get("/stream/{run_id}")
async def stream_progress(run_id: str):
    """SSE endpoint — client subscribes to get real-time pipeline progress."""
    return StreamingResponse(
        sse_stream(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
