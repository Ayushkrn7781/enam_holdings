"""Runtime configuration. Everything comes from the environment; nothing secret is hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def _load_dotenv(path: Path = REPO_DIR / ".env") -> None:
    """Read KEY=VALUE lines from the repo's .env. Real environment variables always win.
    FINN_NO_DOTENV=1 skips it (tests use this to stay deterministic)."""
    if os.environ.get("FINN_NO_DOTENV") == "1" or not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()
IST = timezone(timedelta(hours=5, minutes=30))


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("FINN_DATA_DIR", str(BACKEND_DIR / "data"))))
    snapshot_dir: Path = field(default_factory=lambda: Path(_env("FINN_SNAPSHOT_DIR", str(BACKEND_DIR / "seed"))))
    database_url: str = ""
    llm_api_key: str | None = None
    llm_base_url: str = GEMINI_OPENAI_BASE
    llm_fast_model: str | None = None
    llm_strong_model: str | None = None
    llm_timeout_s: float = 60.0
    llm_min_interval_s: float = 4.5
    enable_dense: bool = False
    embed_model: str = "BAAI/bge-small-en-v1.5"
    cors_origins: str = "*"
    frontend_dist: Path = field(default_factory=lambda: Path(_env("FRONTEND_DIST", str(REPO_DIR / "frontend" / "dist"))))

    def __post_init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = _env("DATABASE_URL", f"sqlite:///{self.data_dir / 'finn.db'}")
        self.llm_api_key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY") or _env("LLM_API_KEY")
        self.llm_base_url = (_env("LLM_BASE_URL", GEMINI_OPENAI_BASE) or GEMINI_OPENAI_BASE).rstrip("/")
        self.llm_fast_model = _env("LLM_FAST_MODEL")
        self.llm_strong_model = _env("LLM_STRONG_MODEL")
        self.llm_timeout_s = float(_env("LLM_TIMEOUT_S", "60"))
        self.llm_min_interval_s = float(_env("LLM_MIN_INTERVAL_S", "4.5"))
        self.enable_dense = _env("FINN_ENABLE_DENSE", "0") == "1"
        self.embed_model = _env("FINN_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
        self.cors_origins = _env("CORS_ORIGINS", "*")

    @property
    def docs_dir(self) -> Path:
        p = self.data_dir / "docs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path | None:
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url[len("sqlite:///"):])
        return None

    @property
    def llm_cache_path(self) -> Path:
        return self.data_dir / "llm_cache.db"


settings = Settings()


def reload_settings() -> Settings:
    """Re-read the environment (tests and the snapshot restore use this)."""
    global settings
    settings.__init__()  # type: ignore[misc]
    return settings


def now_ist() -> datetime:
    """Naive IST wall-clock time. All exchange timestamps are stored as naive IST."""
    return datetime.now(IST).replace(tzinfo=None)
