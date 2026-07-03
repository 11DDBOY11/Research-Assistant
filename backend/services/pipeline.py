"""
pipeline.py — Orchestrator for the 7-stage pipeline.
Uses asyncio.Queue + SSE to push real-time progress to the frontend.
Session model: one DB = one session, run_id is runtime-only (not in DB).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# Runtime-only SSE queues: {run_id: asyncio.Queue}
_sse_queues: dict[str, asyncio.Queue] = {}


def create_run(run_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _sse_queues[run_id] = q
    return q


def get_queue(run_id: str) -> asyncio.Queue | None:
    return _sse_queues.get(run_id)


def cleanup_run(run_id: str) -> None:
    _sse_queues.pop(run_id, None)


async def emit(run_id: str, stage: int, total_stages: int, message: str, data: dict = None) -> None:
    """Emit a progress event to the SSE queue."""
    q = get_queue(run_id)
    if q is None:
        return
    event = {
        "stage": stage,
        "total_stages": total_stages,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
        **(data or {}),
    }
    await q.put(event)
    logger.info(f"[{run_id}] Stage {stage}/{total_stages}: {message}")


async def emit_done(run_id: str) -> None:
    q = get_queue(run_id)
    if q:
        await q.put({"done": True})


async def emit_error(run_id: str, error: str) -> None:
    q = get_queue(run_id)
    if q:
        await q.put({"error": error})


async def sse_stream(run_id: str) -> AsyncGenerator[str, None]:
    """
    AsyncGenerator that yields SSE-formatted strings.
    Used by the /pipeline/stream endpoint.
    """
    q = get_queue(run_id)
    if q is None:
        yield f"data: {json.dumps({'error': 'Unknown run_id'})}\n\n"
        return

    while True:
        try:
            event = await asyncio.wait_for(q.get(), timeout=120.0)
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("done") or event.get("error"):
                break
        except asyncio.TimeoutError:
            yield "data: {\"keepalive\": true}\n\n"
