"""
pdf_parser.py — Extract text from PDFs using PyMuPDF block detection.

Uses page.get_text("blocks") for bounding-box-aware paragraph splitting,
which handles two-column academic PDF layouts correctly.

OCR fallback: if a page yields <50 chars, pytesseract is used on a
rendered image of that page.

paragraph_id format: p{page_num}_b{block_idx}
  - page_num: 0-indexed internally, stored as-is
  - block_idx: sequential index of text blocks on that page
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)

OCR_CHAR_THRESHOLD = 50  # pages with fewer chars trigger OCR fallback


@dataclass
class ParsedBlock:
    page_num: int
    paragraph_id: str   # p{page_num}_b{block_idx}
    text: str


def parse_pdf(file_path: str | Path) -> list[ParsedBlock]:
    """
    Parse a PDF file into a list of ParsedBlock objects.
    Each block corresponds to one PyMuPDF text block (bounding-box-detected).
    OCR is applied per-page when extracted text is too short.
    """
    path = Path(file_path)
    blocks: list[ParsedBlock] = []

    doc = fitz.open(str(path))
    for page_num, page in enumerate(doc):
        page_blocks = _extract_page_blocks(page, page_num)
        # OCR fallback if total chars on page is sparse
        total_chars = sum(len(b.text) for b in page_blocks)
        if total_chars < OCR_CHAR_THRESHOLD:
            logger.info(f"Page {page_num}: only {total_chars} chars — using OCR fallback")
            page_blocks = _ocr_page(page, page_num)
        blocks.extend(page_blocks)

    doc.close()
    return blocks


def _extract_page_blocks(page: fitz.Page, page_num: int) -> list[ParsedBlock]:
    """
    Extract text blocks using PyMuPDF's block detection.
    Returns only text blocks (block_type == 0); image blocks are skipped.
    """
    raw_blocks = page.get_text("blocks")
    result: list[ParsedBlock] = []
    block_idx = 0
    for block in raw_blocks:
        # block: (x0, y0, x1, y1, text, block_no, block_type)
        if block[6] != 0:  # 0 = text block; skip image blocks
            continue
        text = block[4].strip()
        if not text:
            continue
        paragraph_id = f"p{page_num}_b{block_idx}"
        result.append(ParsedBlock(page_num=page_num, paragraph_id=paragraph_id, text=text))
        block_idx += 1
    return result


def _ocr_page(page: fitz.Page, page_num: int) -> list[ParsedBlock]:
    """
    OCR fallback: render page to image, run pytesseract, split on double-newline.
    Returns paragraphs as ParsedBlock objects.
    """
    try:
        import pytesseract
    except ImportError:
        logger.error("pytesseract not installed — OCR fallback unavailable")
        return []

    try:
        mat = fitz.Matrix(2, 2)  # 2x scale for better OCR quality
        clip = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(clip.tobytes("png")))
        ocr_text: str = pytesseract.image_to_string(img)

        paragraphs = [p.strip() for p in ocr_text.split("\n\n") if p.strip()]
        result: list[ParsedBlock] = []
        for block_idx, para in enumerate(paragraphs):
            paragraph_id = f"p{page_num}_b{block_idx}"
            result.append(ParsedBlock(page_num=page_num, paragraph_id=paragraph_id, text=para))
        return result
    except Exception as e:
        logger.exception(f"OCR failed for page {page_num}: {e}")
        return []


def parse_txt(file_path: str | Path) -> list[ParsedBlock]:
    """
    Parse a plain-text file. Split on double-newlines to approximate paragraphs.
    All blocks assigned page_num=0 (single-page concept for text files).
    """
    path = Path(file_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return [
        ParsedBlock(page_num=0, paragraph_id=f"p0_b{i}", text=para)
        for i, para in enumerate(paragraphs)
    ]


def parse_docx(file_path: str | Path) -> list[ParsedBlock]:
    """
    Parse a DOCX file using python-docx.
    Each non-empty paragraph becomes one block (page_num=0).
    """
    try:
        from docx import Document
    except ImportError:
        logger.error("python-docx not installed — DOCX parsing unavailable")
        return []

    doc = Document(str(file_path))
    blocks: list[ParsedBlock] = []
    block_idx = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            blocks.append(ParsedBlock(page_num=0, paragraph_id=f"p0_b{block_idx}", text=text))
            block_idx += 1
    return blocks
