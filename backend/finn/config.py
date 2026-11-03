"""Runtime configuration. Everything comes from environment variables; nothing secret is hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Naive IST wall-clock time — all exchange timestamps in FINN are stored as naive IST."""
    return datetime.now(IST).replace(tzinfo=None)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("FINN_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'finn.db'}")
    # "demo" = clearly-labelled illustrative dataset; "live" = data pulled by `python -m finn.refresh`
    data_mode: str = os.getenv("FINN_DATA_MODE", "auto")

    # LLM routing. Groq free tier by default; any OpenAI-compatible endpoint works.
    llm_api_key: str | None = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    llm_fast_model: str = os.getenv("LLM_FAST_MODEL", "llama-3.1-8b-instant")
    llm_strong_model: str = os.getenv("LLM_STRONG_MODEL", "llama-3.3-70b-versatile")
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "45"))

    # Dense retrieval is optional (fastembed / ONNX). BM25 always runs.
    enable_dense: bool = os.getenv("FINN_ENABLE_DENSE", "0") == "1"
    embed_model: str = os.getenv("FINN_EMBED_MODEL", "BAAI/bge-small-en-v1.5")

    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "*").split(",")
    )
    frontend_dist: Path = Path(os.getenv("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))
    docs_dir: Path = DATA_DIR / "docs"


settings = Settings()
settings.docs_dir.mkdir(parents=True, exist_ok=True)
