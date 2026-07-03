"""
config.py — Environment configuration with fail-fast validation.
Both ANTHROPIC_API_KEY and OPENAI_API_KEY are required.
The app will not start without them.
"""
import sys
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    openai_api_key: str

    max_literature_pdfs: int = 15
    max_file_size_mb: int = 20

    db_path: str = "/app/data/research_assistant.db"
    chroma_path: str = "/app/data/chroma"

    claude_model: str = "claude-sonnet-4-5"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_verify_model: str = "gpt-4o-mini"

    # Batching limits
    stage5_batch_size: int = 10  # claims per Claude call in Stage 5
    stage6b_batch_size: int = 10  # sentences per GPT-4o-mini call in Stage 6b

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    try:
        return Settings()
    except Exception as e:
        print(f"\n[FATAL] Configuration error: {e}")
        print("Ensure both ANTHROPIC_API_KEY and OPENAI_API_KEY are set in .env\n")
        sys.exit(1)


settings = get_settings()
