"""
database.py — SQLAlchemy ORM models and async engine setup.
All array-like data (cited_claim_ids, matched_paper_ids, etc.) is stored
as JSON-serialized TEXT columns. Decode with json_list_loads() from schemas.py.
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config import settings

DATABASE_URL = f"sqlite:///{settings.db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class Paper(Base):
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)          # "pdf" | "txt" | "docx"
    role = Column(String, nullable=False)               # PaperRole enum value
    status = Column(String, default="uploaded")         # uploaded|extracted|embedded|done
    created_at = Column(DateTime, default=datetime.utcnow)

    pages = relationship("Page", back_populates="paper", cascade="all, delete-orphan")
    metadata_rec = relationship("PaperMetadata", back_populates="paper", uselist=False)
    claims = relationship("Claim", back_populates="paper", cascade="all, delete-orphan")
    project_claims = relationship("ProjectClaim", back_populates="paper")
    clarifications = relationship("ClarificationRequest", back_populates="paper")


class Page(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    page_num = Column(Integer, nullable=False)
    paragraph_id = Column(String, nullable=False)       # "p{page_num}_b{block_idx}"
    text = Column(Text, nullable=False)

    paper = relationship("Paper", back_populates="pages")


class PaperMetadata(Base):
    __tablename__ = "paper_metadata"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), unique=True, nullable=False)
    title = Column(String, default="")
    authors_json = Column(Text, default="[]")           # JSON list of strings
    year = Column(Integer, nullable=True)
    problem_statement = Column(Text, default="")
    objectives_json = Column(Text, default="[]")
    methodology = Column(Text, default="")
    algorithms_json = Column(Text, default="[]")
    datasets_json = Column(Text, default="[]")
    results = Column(Text, default="")
    limitations_json = Column(Text, default="[]")
    future_work_json = Column(Text, default="[]")
    claims_json = Column(Text, default="[]")            # full claims list as JSON

    paper = relationship("Paper", back_populates="metadata_rec")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    page_num = Column(Integer, nullable=False)
    paragraph_id = Column(String, nullable=False)
    claim_text = Column(Text, nullable=False)
    chroma_id = Column(String, nullable=True)           # ChromaDB document ID

    paper = relationship("Paper", back_populates="claims")


class ProjectClaim(Base):
    __tablename__ = "project_claims"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    claim_text = Column(Text, nullable=False)
    comparison_result = Column(String, nullable=True)   # ComparisonResult enum value
    matched_paper_ids = Column(Text, default="[]")      # JSON list — decode with json_list_loads()
    reasoning = Column(Text, default="")

    paper = relationship("Paper", back_populates="project_claims")


class ClarificationRequest(Base):
    __tablename__ = "clarification_requests"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    field_name = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    user_response = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("Paper", back_populates="clarifications")


class GeneratedSentence(Base):
    __tablename__ = "generated_sentences"

    id = Column(Integer, primary_key=True, index=True)
    section = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    cited_claim_ids = Column(Text, default="[]")        # JSON list — decode with json_list_loads()
    status = Column(String, default="pending")          # VerificationStatus enum value
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, index=True)
    stage = Column(String, nullable=False)              # "stage2", "stage5", "stage6a", "stage6b"
    model = Column(String, nullable=False)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
    call_ts = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
