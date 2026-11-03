"""Vercel serverless entry point: the whole FastAPI app as one Python function.

Vercel's filesystem is read-only except /tmp, so the SQLite database lives in /tmp and the
illustrative demo dataset is rebuilt on each cold start (~3 s). The React app is served
separately by Vercel's CDN from frontend/dist; every /api/* request is rewritten to this file.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("FINN_DATA_DIR", "/tmp/finn")
os.environ.setdefault("FRONTEND_DIST", "/nonexistent")  # static files come from the CDN, not FastAPI

import shutil  # noqa: E402

# Cold start: copy the prebuilt demo snapshot (database + generated PDFs) into /tmp. Milliseconds,
# versus seconds to regenerate it. The snapshot was built with FINN_DATA_DIR=/tmp/finn, so stored
# document paths resolve as-is.
DATA = Path(os.environ["FINN_DATA_DIR"])
SNAPSHOT = ROOT / "backend" / "seed"
os.environ.setdefault("FINN_SNAPSHOT_DIR", str(SNAPSHOT))
if not (DATA / "finn.db").exists() and SNAPSHOT.exists():
    DATA.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SNAPSHOT / "finn.db", DATA / "finn.db")
    shutil.copytree(SNAPSHOT / "docs", DATA / "docs", dirs_exist_ok=True)

from finn.api.app import app  # noqa: E402,F401  (Vercel picks up the ASGI `app`)
