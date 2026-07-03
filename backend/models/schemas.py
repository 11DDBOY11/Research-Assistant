"""
schemas.py — Pydantic models and enums used throughout the pipeline.
Canonical source of truth for data shapes; imported by all routers and services.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PaperRole(str, Enum):
    LITERATURE = "literature"
    PROJECT = "project"


class ComparisonResult(str, Enum):
    MATCHES_EXISTING = "matches_existing"
    PARTIAL_OVERLAP = "partial_overlap"
    NOT_FOUND_IN_CORPUS = "not_found_in_corpus"


class VerificationStatus(str, Enum):
    """
    Status of a generated sentence after Stage 6b verification.
    Never compare as raw strings — use this enum exclusively.
    """
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Stage 2 / Stage 4 — LLM extraction schema
# ---------------------------------------------------------------------------

class ExtractedClaim(BaseModel):
    text: str
    page: int
    paragraph_id: str  # format: p{page_num}_b{block_idx}

    @field_validator("paragraph_id")
    @classmethod
    def paragraph_id_must_be_present(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("paragraph_id is required and cannot be empty")
        return v

    @field_validator("page")
    @classmethod
    def page_must_be_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("page must be >= 0")
        return v


class PaperExtraction(BaseModel):
    title: str
    authors: list[str]
    year: Optional[int]
    problem_statement: str
    objectives: list[str]
    methodology: str
    algorithms: list[str]
    datasets: list[str]
    results: str
    limitations: list[str]
    future_work: list[str]
    claims: list[ExtractedClaim]

    @field_validator("claims")
    @classmethod
    def claims_must_have_source(cls, claims: list[ExtractedClaim]) -> list[ExtractedClaim]:
        valid = [c for c in claims if c.paragraph_id and c.page >= 0]
        return valid


# ---------------------------------------------------------------------------
# Stage 5 — Comparison result
# ---------------------------------------------------------------------------

class ClaimComparison(BaseModel):
    project_claim_id: int
    result: ComparisonResult
    matched_paper_ids: list[str]  # stored as JSON text in DB
    reasoning: str


class BatchComparisonOutput(BaseModel):
    comparisons: list[ClaimComparison]


# ---------------------------------------------------------------------------
# Stage 6b — Verification result
# ---------------------------------------------------------------------------

class SentenceVerification(BaseModel):
    sentence_id: int
    verdict: bool  # True = supported, False = rejected
    reason: str


class BatchVerificationOutput(BaseModel):
    verifications: list[SentenceVerification]


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    paper_ids: list[int]
    filenames: list[str]
    message: str


class PipelineStartResponse(BaseModel):
    run_id: str
    message: str


class ClarificationRequest(BaseModel):
    id: int
    paper_id: int
    field_name: str
    prompt: str
    user_response: Optional[str] = None
    resolved: bool = False


class ClarificationUpdate(BaseModel):
    clarification_id: int
    response: str


class GeneratedPaper(BaseModel):
    markdown: str
    bibliography: list[dict[str, Any]]
    section_count: int


class TransparencyReport(BaseModel):
    papers_analyzed: int
    claims_extracted: int
    sentences_generated: int
    sentences_verified: int
    sentences_rejected: int
    open_clarifications: int
    rejected_details: list[dict[str, Any]]
    llm_usage: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def json_list_dumps(lst: list) -> str:
    """Serialize a list to JSON text for SQLite TEXT columns."""
    return json.dumps(lst)


def json_list_loads(s: Optional[str]) -> list:
    """Deserialize a JSON text column back to a list."""
    if not s:
        return []
    return json.loads(s)
