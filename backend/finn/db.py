"""Engine, sessions and the small Meta key/value store."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_engine = None
_SessionLocal: sessionmaker | None = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = settings.database_url
        kwargs: dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _pragmas(conn, _rec):  # pragma: no cover - trivial
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def dispose() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)
    models.Base.metadata.create_all(engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_meta(s: Session, key: str, default: Any = None) -> Any:
    from .models import Meta
    row = s.get(Meta, key)
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except Exception:
        return default


def set_meta(s: Session, key: str, value: Any) -> None:
    from .models import Meta
    row = s.get(Meta, key)
    payload = json.dumps(value, default=str)
    if row is None:
        s.add(Meta(key=key, value=payload))
    else:
        row.value = payload


def meta_keys(s: Session, prefix: str) -> list[str]:
    from .models import Meta
    return [k for (k,) in s.execute(select(Meta.key).where(Meta.key.like(f"{prefix}%")))]
