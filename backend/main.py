"""
main.py — FastAPI application entry point.

Startup:
1. Verifies ANTHROPIC_API_KEY and OPENAI_API_KEY are present (fail-fast via config.py)
2. Initializes SQLite database (creates tables if not exist)
3. Registers all routers
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings  # fail-fast happens at import time
from database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    os.makedirs(settings.chroma_path, exist_ok=True)
    init_db()
    logger.info(f"Database ready at {settings.db_path}")
    logger.info(f"ChromaDB store at {settings.chroma_path}")
    logger.info("Research Paper Assistant backend ready ✓")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Research Paper Assistant API",
    description="Evidence-based research paper generation with full citation traceability",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server and production frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://frontend:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from routers.upload import router as upload_router
from routers.extraction import router as extraction_router
from routers.knowledge import router as knowledge_router
from routers.comparison import router as comparison_router
from routers.generation import router as generation_router
from routers.output import router as output_router
from routers.pipeline_router import router as pipeline_router

app.include_router(upload_router, prefix="/api")
app.include_router(extraction_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(comparison_router, prefix="/api")
app.include_router(generation_router, prefix="/api")
app.include_router(output_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok", "service": "research-paper-assistant"}


@app.get("/")
def root():
    return {
        "message": "Research Paper Assistant API",
        "docs": "/docs",
        "health": "/health",
    }
