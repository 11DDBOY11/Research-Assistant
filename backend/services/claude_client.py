"""
claude_client.py — Anthropic Claude client for Stage 2 (extraction) and Stage 6a (generation).

Key behaviors:
- Stage 2: Returns strict PaperExtraction JSON. On Pydantic validation failure,
  retries once with a corrective re-prompt. On second failure, drops only the
  invalid claims (not the whole paper) and logs them.
- Stage 5: Batched comparison — up to 10 project claims per call.
- Stage 6a: Drafts paper sentences with cited claim IDs.
- All calls log token usage to the LLMUsage table via a provided db session.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import anthropic
from pydantic import ValidationError
from sqlalchemy.orm import Session

from config import settings
from database import LLMUsage
from models.schemas import (
    PaperExtraction,
    BatchComparisonOutput,
    ClaimComparison,
    ComparisonResult,
    json_list_dumps,
)

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# Published pricing (as of mid-2025) for cost estimation
# claude-sonnet-4-5: $3/1M input, $15/1M output
COST_PER_1M_INPUT = 3.0
COST_PER_1M_OUTPUT = 15.0


def _log_usage(db: Session, stage: str, model: str, usage: anthropic.types.Usage):
    prompt_tokens = usage.input_tokens
    completion_tokens = usage.output_tokens
    cost = (prompt_tokens / 1_000_000) * COST_PER_1M_INPUT + \
           (completion_tokens / 1_000_000) * COST_PER_1M_OUTPUT
    db.add(LLMUsage(
        stage=stage,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
    ))
    db.commit()


# ---------------------------------------------------------------------------
# Stage 2 — Paper Extraction
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = """You are a research paper analyzer. Return ONLY valid JSON matching
the schema exactly. Every claim MUST have a non-empty paragraph_id (format: p{page}_b{block})
and a page number >= 0. Do not include any text outside the JSON object."""

EXTRACTION_PROMPT = """Analyze this research paper and extract structured information.
Return a single JSON object with this exact schema:
{
  "title": "string",
  "authors": ["string"],
  "year": integer_or_null,
  "problem_statement": "string",
  "objectives": ["string"],
  "methodology": "string",
  "algorithms": ["string"],
  "datasets": ["string"],
  "results": "string",
  "limitations": ["string"],
  "future_work": ["string"],
  "claims": [
    {"text": "string", "page": integer, "paragraph_id": "p{page}_b{block}"}
  ]
}

PAPER TEXT (page-by-page, with paragraph_ids):
{paper_text}
"""

CORRECTION_PROMPT = """Your previous response had validation errors: {errors}

Return corrected JSON. CRITICAL RULES:
1. Every claim must have "paragraph_id" in format p{{page}}_b{{block}} (e.g., "p0_b3")
2. Every claim must have "page" >= 0
3. No claim may have an empty paragraph_id
4. Return ONLY the JSON object, nothing else.

Original paper text:
{paper_text}
"""


def extract_paper(db: Session, paper_text: str, paper_id: int) -> tuple[PaperExtraction, list[dict]]:
    """
    Extract structured data from paper text.
    Returns (PaperExtraction, list_of_dropped_claims).
    Dropped claims are logged to clarification_requests by the router.
    """
    prompt = EXTRACTION_PROMPT.format(paper_text=paper_text[:80_000])  # token guard

    # First attempt
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage(db, "stage2", settings.claude_model, response.usage)

    raw = response.content[0].text.strip()
    try:
        return _parse_and_validate(raw), []
    except (ValidationError, json.JSONDecodeError) as e:
        logger.warning(f"Stage 2 first attempt failed for paper {paper_id}: {e}")

    # Second attempt with corrective re-prompt
    correction = CORRECTION_PROMPT.format(errors=str(e), paper_text=paper_text[:80_000])
    response2 = client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=EXTRACTION_SYSTEM,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": correction},
        ],
    )
    _log_usage(db, "stage2_retry", settings.claude_model, response2.usage)

    raw2 = response2.content[0].text.strip()
    try:
        return _parse_and_validate(raw2), []
    except (ValidationError, json.JSONDecodeError) as e2:
        logger.error(f"Stage 2 second attempt failed for paper {paper_id}: {e2}")
        # Best-effort: parse raw JSON, filter out invalid claims, keep valid ones
        return _salvage_extraction(raw2, e2)


def _parse_and_validate(raw: str) -> PaperExtraction:
    """Strip markdown code fences if present, then parse JSON, then Pydantic validate."""
    text = raw
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    data = json.loads(text)
    return PaperExtraction.model_validate(data)


def _salvage_extraction(raw: str, original_error: Exception) -> tuple[PaperExtraction, list[dict]]:
    """
    On second validation failure: parse what we can, drop invalid claims,
    return valid PaperExtraction + list of dropped claim dicts for logging.
    """
    dropped: list[dict] = []
    try:
        text = raw
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        data = json.loads(text)

        # Filter claims individually
        valid_claims = []
        for claim in data.get("claims", []):
            try:
                from models.schemas import ExtractedClaim
                ExtractedClaim.model_validate(claim)
                valid_claims.append(claim)
            except ValidationError as ce:
                dropped.append({"claim": claim, "reason": str(ce)})

        data["claims"] = valid_claims
        extraction = PaperExtraction.model_validate(data)
        logger.info(f"Salvaged extraction: {len(valid_claims)} valid, {len(dropped)} dropped claims")
        return extraction, dropped
    except Exception as final_err:
        logger.error(f"Salvage failed — returning empty extraction: {final_err}")
        return PaperExtraction(
            title="Unknown", authors=[], year=None,
            problem_statement="", objectives=[], methodology="",
            algorithms=[], datasets=[], results="",
            limitations=[], future_work=[], claims=[]
        ), dropped


# ---------------------------------------------------------------------------
# Stage 5 — Comparison (batched, up to 10 claims per call)
# ---------------------------------------------------------------------------

COMPARISON_SYSTEM = """You are a research comparison engine. Return ONLY valid JSON.
For each project claim, classify it against the provided literature evidence."""

COMPARISON_PROMPT = """Compare each project claim against the provided literature evidence snippets.
Return a JSON object with this exact schema:
{
  "comparisons": [
    {
      "project_claim_id": integer,
      "result": "matches_existing|partial_overlap|not_found_in_corpus",
      "matched_paper_ids": ["paper_id_string"],
      "reasoning": "one sentence explanation"
    }
  ]
}

PROJECT CLAIMS:
{claims_json}

LITERATURE EVIDENCE (top-5 similar claims per project claim):
{evidence_json}
"""


def compare_claims_batch(
    db: Session,
    claims: list[dict],  # [{"id": int, "text": str}]
    evidence: list[dict],  # [{"project_claim_id": int, "similar": [{"claim_text", "paper_id"}]}]
) -> BatchComparisonOutput:
    prompt = COMPARISON_PROMPT.format(
        claims_json=json.dumps(claims, indent=2),
        evidence_json=json.dumps(evidence, indent=2),
    )
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=2048,
        system=COMPARISON_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage(db, "stage5", settings.claude_model, response.usage)

    raw = response.content[0].text.strip()
    try:
        return _parse_comparison(raw)
    except Exception as e:
        logger.error(f"Stage 5 comparison parse error: {e}")
        # Return not_found for all claims on failure
        return BatchComparisonOutput(comparisons=[
            ClaimComparison(
                project_claim_id=c["id"],
                result=ComparisonResult.NOT_FOUND_IN_CORPUS,
                matched_paper_ids=[],
                reasoning="Parse error — could not classify",
            )
            for c in claims
        ])


def _parse_comparison(raw: str) -> BatchComparisonOutput:
    text = raw
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    data = json.loads(text)
    return BatchComparisonOutput.model_validate(data)


# ---------------------------------------------------------------------------
# Stage 6a — Paper Generation
# ---------------------------------------------------------------------------

GENERATION_SYSTEM = """You are a research paper writer. Every sentence you write MUST
be supported by the provided evidence claims. Include inline citations like [CLAIM:id].
Return a JSON object with sections as keys and arrays of sentences as values."""

GENERATION_PROMPT = """Write a research paper section using ONLY the provided evidence.
For each sentence, include an inline citation [CLAIM:id] referencing the claim ID.
Do not write any sentence without a supporting claim.

Return JSON:
{
  "introduction": ["sentence with [CLAIM:id]", ...],
  "related_work": ["sentence with [CLAIM:id]", ...],
  "methodology": ["sentence with [CLAIM:id]", ...],
  "results": ["sentence with [CLAIM:id]", ...],
  "conclusion": ["sentence with [CLAIM:id]", ...]
}

VERIFIED CLAIMS (use these as your evidence):
{claims_json}

PROJECT CONTEXT:
{project_context}
"""


def generate_paper_draft(
    db: Session,
    claims: list[dict],  # [{"id": int, "text": str, "paper_id": int, "page": int}]
    project_context: str,
) -> dict[str, list[dict]]:
    """
    Returns {section: [{"text": str, "cited_claim_ids": [int]}]}
    Parses inline [CLAIM:id] citations into cited_claim_ids list.
    """
    prompt = GENERATION_PROMPT.format(
        claims_json=json.dumps(claims, indent=2),
        project_context=project_context[:8000],
    )
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=6000,
        system=GENERATION_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    _log_usage(db, "stage6a", settings.claude_model, response.usage)

    raw = response.content[0].text.strip()
    return _parse_generation(raw)


def _parse_generation(raw: str) -> dict[str, list[dict]]:
    import re
    text = raw
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    data = json.loads(text)

    result: dict[str, list[dict]] = {}
    for section, sentences in data.items():
        if not isinstance(sentences, list):
            continue
        parsed_sentences = []
        for sentence in sentences:
            if not isinstance(sentence, str):
                continue
            # Extract [CLAIM:id] references
            claim_ids = [int(m) for m in re.findall(r"\[CLAIM:(\d+)\]", sentence)]
            # Clean text: remove citation markers for display
            clean_text = re.sub(r"\s*\[CLAIM:\d+\]", "", sentence).strip()
            if clean_text:
                parsed_sentences.append({
                    "text": clean_text,
                    "cited_claim_ids": claim_ids,
                })
        result[section] = parsed_sentences
    return result
