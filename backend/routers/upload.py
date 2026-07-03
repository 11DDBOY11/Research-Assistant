"""
upload.py — Stage 1: File ingestion with validation.

Validates:
- File size: max 20MB per file
- MIME type: application/pdf or text/plain (magic-byte check, not extension)
- Count: max 15 literature PDFs + 1 project file per session

Parses each file into blocks and stores in pages table.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

import magic
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import settings
from database import Paper, Page, get_db, init_db
from models.schemas import PaperRole, UploadResponse
from services.pdf_parser import parse_pdf, parse_txt, parse_docx

router = APIRouter(prefix="/upload", tags=["upload"])
logger = logging.getLogger(__name__)

MAX_BYTES = settings.max_file_size_mb * 1024 * 1024

ALLOWED_MIME = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    # Some systems report these for PDF/text
    "application/octet-stream": None,  # will be re-checked
}


def _detect_mime(data: bytes) -> str:
    """Use libmagic for reliable MIME detection (not extension-based)."""
    mime = magic.from_buffer(data[:4096], mime=True)
    return mime


def _validate_file(content: bytes, filename: str, role: str) -> str:
    """Validate size, MIME type. Returns detected file_type string."""
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File '{filename}' exceeds {settings.max_file_size_mb}MB limit",
        )

    mime = _detect_mime(content)

    if mime == "application/pdf":
        return "pdf"
    elif mime in ("text/plain", "text/html"):
        return "txt"
    elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    elif mime == "application/zip" and filename.lower().endswith(".docx"):
        # DOCX files are ZIP archives; magic may report application/zip
        return "docx"
    else:
        raise HTTPException(
            status_code=415,
            detail=f"File '{filename}' has unsupported type '{mime}'. Accepted: PDF, TXT, DOCX",
        )


def _parse_file(file_type: str, file_path: str):
    if file_type == "pdf":
        return parse_pdf(file_path)
    elif file_type == "txt":
        return parse_txt(file_path)
    elif file_type == "docx":
        return parse_docx(file_path)
    else:
        return []


@router.post("/literature", response_model=UploadResponse)
async def upload_literature(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload up to 15 literature PDFs (or TXT/DOCX). Stage 1."""
    # Count existing literature papers
    existing_count = db.query(Paper).filter(Paper.role == PaperRole.LITERATURE.value).count()
    if existing_count + len(files) > settings.max_literature_pdfs:
        raise HTTPException(
            status_code=400,
            detail=f"Exceeds {settings.max_literature_pdfs} literature file limit. "
                   f"Currently have {existing_count}.",
        )

    paper_ids: list[int] = []
    filenames: list[str] = []

    for upload in files:
        content = await upload.read()
        file_type = _validate_file(content, upload.filename or "file", "literature")

        # Write to temp file for parsing
        suffix = f".{file_type}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Parse blocks
            blocks = _parse_file(file_type, tmp_path)
        finally:
            os.unlink(tmp_path)

        if not blocks:
            raise HTTPException(
                status_code=422,
                detail=f"Could not extract any text from '{upload.filename}'. "
                       "Check that the file is not password-protected.",
            )

        # Store paper + pages
        paper = Paper(
            filename=upload.filename or "unnamed",
            file_type=file_type,
            role=PaperRole.LITERATURE.value,
            status="uploaded",
        )
        db.add(paper)
        db.flush()

        for block in blocks:
            db.add(Page(
                paper_id=paper.id,
                page_num=block.page_num,
                paragraph_id=block.paragraph_id,
                text=block.text,
            ))

        db.commit()
        paper_ids.append(paper.id)
        filenames.append(upload.filename or "unnamed")
        logger.info(f"Ingested literature paper {paper.id}: {upload.filename} ({len(blocks)} blocks)")

    return UploadResponse(
        paper_ids=paper_ids,
        filenames=filenames,
        message=f"Successfully uploaded {len(paper_ids)} file(s)",
    )


@router.post("/project", response_model=UploadResponse)
async def upload_project(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload the student's project file (PDF, TXT, or DOCX). Stage 1."""
    # Remove any existing project file first (single-session: one project at a time)
    existing = db.query(Paper).filter(Paper.role == PaperRole.PROJECT.value).all()
    for p in existing:
        db.delete(p)
    db.commit()

    content = await file.read()
    file_type = _validate_file(content, file.filename or "project", "project")

    suffix = f".{file_type}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        blocks = _parse_file(file_type, tmp_path)
    finally:
        os.unlink(tmp_path)

    if not blocks:
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the project file.",
        )

    paper = Paper(
        filename=file.filename or "project",
        file_type=file_type,
        role=PaperRole.PROJECT.value,
        status="uploaded",
    )
    db.add(paper)
    db.flush()

    for block in blocks:
        db.add(Page(
            paper_id=paper.id,
            page_num=block.page_num,
            paragraph_id=block.paragraph_id,
            text=block.text,
        ))

    db.commit()
    logger.info(f"Ingested project file {paper.id}: {file.filename} ({len(blocks)} blocks)")

    return UploadResponse(
        paper_ids=[paper.id],
        filenames=[file.filename or "project"],
        message="Project file uploaded successfully",
    )


@router.get("/status")
def get_upload_status(db: Session = Depends(get_db)):
    """Return counts of uploaded files."""
    lit_count = db.query(Paper).filter(Paper.role == PaperRole.LITERATURE.value).count()
    proj_count = db.query(Paper).filter(Paper.role == PaperRole.PROJECT.value).count()
    literature = db.query(Paper).filter(Paper.role == PaperRole.LITERATURE.value).all()
    return {
        "literature_count": lit_count,
        "project_count": proj_count,
        "max_literature": settings.max_literature_pdfs,
        "ready_to_run": lit_count > 0 and proj_count > 0,
        "literature_files": [{"id": p.id, "filename": p.filename, "status": p.status} for p in literature],
    }


@router.delete("/reset")
def reset_session(db: Session = Depends(get_db)):
    """Reset the session — delete all papers, pages, and derived data."""
    from database import (
        Paper, Page, PaperMetadata, Claim, ProjectClaim,
        ClarificationRequest, GeneratedSentence, LLMUsage,
    )
    from services.chroma_store import reset_collection

    db.query(GeneratedSentence).delete()
    db.query(ProjectClaim).delete()
    db.query(Claim).delete()
    db.query(ClarificationRequest).delete()
    db.query(PaperMetadata).delete()
    db.query(Page).delete()
    db.query(Paper).delete()
    db.query(LLMUsage).delete()
    db.commit()
    reset_collection()
    return {"message": "Session reset successfully"}
