"""
openai_client.py — OpenAI client for Stage 3 (embeddings) and Stage 6b (verification).

Stage 3: text-embedding-3-small for all claim texts.
Stage 6b: gpt-4o-mini entailment check, batched 10 sentences per call.
  - Must be independent of Claude (Stage 6a) to catch hallucinated citations.
  - Returns {sentence_id, verdict: bool, reason} per sentence.
"""
from __future__ import annotations

import json
import logging
from sqlalchemy.orm import Session

from openai import OpenAI

from config import settings
from database import LLMUsage
from models.schemas import BatchVerificationOutput, SentenceVerification

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.openai_api_key)

# Pricing for cost estimation (mid-2025)
# text-embedding-3-small: $0.02/1M tokens
# gpt-4o-mini: $0.15/1M input, $0.60/1M output
EMBED_COST_PER_1M = 0.02
MINI_INPUT_COST_PER_1M = 0.15
MINI_OUTPUT_COST_PER_1M = 0.60


def _log_embedding_usage(db: Session, token_count: int):
    cost = (token_count / 1_000_000) * EMBED_COST_PER_1M
    db.add(LLMUsage(
        stage="stage3",
        model=settings.openai_embedding_model,
        prompt_tokens=token_count,
        completion_tokens=0,
        estimated_cost_usd=cost,
    ))
    db.commit()


def _log_verify_usage(db: Session, usage):
    cost = (usage.prompt_tokens / 1_000_000) * MINI_INPUT_COST_PER_1M + \
           (usage.completion_tokens / 1_000_000) * MINI_OUTPUT_COST_PER_1M
    db.add(LLMUsage(
        stage="stage6b",
        model=settings.openai_verify_model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        estimated_cost_usd=cost,
    ))
    db.commit()


# ---------------------------------------------------------------------------
# Stage 3 — Embeddings (batched by 100)
# ---------------------------------------------------------------------------

def embed_texts(db: Session, texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using text-embedding-3-small.
    Processes in batches of 100 to stay within API limits.
    Returns list of embedding vectors in the same order as input.
    """
    BATCH_SIZE = 100
    all_embeddings: list[list[float]] = []
    total_tokens = 0

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=batch,
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
        total_tokens += response.usage.total_tokens

    _log_embedding_usage(db, total_tokens)
    return all_embeddings


def embed_single(text: str) -> list[float]:
    """Embed a single text without DB logging (used for query-time search)."""
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=[text],
    )
    return response.data[0].embedding


# ---------------------------------------------------------------------------
# Stage 6b — Verification Gate (batched by 10 sentences per call)
# ---------------------------------------------------------------------------

VERIFY_SYSTEM = """You are an entailment checker. For each sentence, determine whether
the cited source text actually supports the sentence. Be strict: if the source text
does not clearly entail the sentence, mark it as not supported.
Return ONLY valid JSON, no explanations outside the JSON."""

VERIFY_PROMPT = """For each item, check if the sentence is fully supported by its cited source text.
Return:
{
  "verifications": [
    {
      "sentence_id": integer,
      "verdict": true_or_false,
      "reason": "one sentence explanation"
    }
  ]
}

ITEMS TO VERIFY:
{items_json}
"""


def verify_sentences_batch(
    db: Session,
    items: list[dict],  # [{"sentence_id": int, "sentence": str, "source_texts": [str]}]
) -> BatchVerificationOutput:
    """
    Verify up to 10 sentences per call.
    items: each item has a sentence and its cited source texts to check against.
    """
    prompt = VERIFY_PROMPT.format(items_json=json.dumps(items, indent=2))

    response = client.chat.completions.create(
        model=settings.openai_verify_model,
        messages=[
            {"role": "system", "content": VERIFY_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    _log_verify_usage(db, response.usage)

    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        return BatchVerificationOutput.model_validate(data)
    except Exception as e:
        logger.error(f"Stage 6b parse error: {e} | raw: {raw[:500]}")
        # On parse error: reject all sentences in this batch (safe default)
        return BatchVerificationOutput(verifications=[
            SentenceVerification(
                sentence_id=item["sentence_id"],
                verdict=False,
                reason="Verification parse error — sentence rejected as safety measure",
            )
            for item in items
        ])
