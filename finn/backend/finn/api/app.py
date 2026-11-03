"""FINN HTTP API. Handlers stay thin: validation + serialisation; logic lives in services/ and research/."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_session, init_db, session_scope
from ..models import AlertEvent, AlertRule, Announcement, Company, Document, FinancialPeriod, Holding, Meta, Price
from ..research import answer, guidance, health, retrieval
from ..services import alerts, digest, llm, market, materiality, pipeline, signals
from ..services.results import periods, results_card
from ..services.taxonomy import CATEGORIES
from ..universe import ALL

log = logging.getLogger("finn.api")
app = FastAPI(title="FINN API", version="1.0", description="Financial Investment Agent — push signals and evidence-backed research for NSE companies.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


def _restore_snapshot() -> None:
    """If a prebuilt snapshot ships with the code (backend/seed) and there's no database yet, start from it."""
    import os
    import shutil

    snap = Path(os.getenv("FINN_SNAPSHOT_DIR", Path(__file__).resolve().parents[2] / "seed"))
    db = Path(settings.database_url.replace("sqlite:///", "")) if settings.database_url.startswith("sqlite") else None
    if db and not db.exists() and (snap / "finn.db").exists():
        db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snap / "finn.db", db)
        if (snap / "docs").exists():
            shutil.copytree(snap / "docs", settings.docs_dir, dirs_exist_ok=True)
        log.info("restored data snapshot from %s", snap)


@app.on_event("startup")
def _startup() -> None:
    _restore_snapshot()
    init_db()
    with session_scope() as s:
        if not s.scalar(select(func.count()).select_from(Company)):
            from .. import demo

            log.info("empty database — building illustrative demo dataset")
            demo.reset(s)


@app.middleware("http")
async def _timing(request: Request, call_next):
    t0 = time.time()
    resp = await call_next(request)
    resp.headers["X-Response-Time-ms"] = str(int((time.time() - t0) * 1000))
    return resp


@app.exception_handler(Exception)
async def _err(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": str(exc)[:300]})


def _404(what: str):
    raise HTTPException(status_code=404, detail={"error": "not_found", "detail": what})


def _ticker(s: Session, ticker: str) -> Company:
    c = s.get(Company, ticker.upper())
    if not c:
        _404(f"Unknown ticker {ticker}")
    return c


# ------------------------------------------------------------------ system

@app.get("/api/health")
def health_check():
    return {"ok": True, "time": datetime.utcnow().isoformat()}


@app.get("/api/system/data-status")
def data_status(s: Session = Depends(get_session)):
    mode = pipeline.data_mode(s)
    src = s.get(Meta, "source_status")
    counts = {name: s.scalar(select(func.count()).select_from(M)) for name, M in
              (("companies", Company), ("prices", Price), ("announcements", Announcement), ("financial_periods", FinancialPeriod), ("documents", Document))}
    last_px = s.scalar(select(func.max(Price.date)))
    return {"mode": mode, "sources": src.value if src else {}, "counts": counts, "last_eod_session": last_px.isoformat() if last_px else None,
            "monitoring": "End-of-day: prices and filings are evaluated once per refresh (scheduled after market close). Not real-time.",
            "llm": llm.stats(), "retrieval": retrieval.mode()}


@app.post("/api/system/demo-reset")
def demo_reset(s: Session = Depends(get_session)):
    import os
    import shutil

    snap = os.getenv("FINN_SNAPSHOT_DIR")
    if snap and Path(snap, "finn.db").exists():
        # serverless deploy: restore the prebuilt snapshot instead of regenerating (no PDF library there)
        s.close()
        from ..db import engine

        engine.dispose()
        db = Path(settings.database_url.replace("sqlite:///", ""))
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        shutil.copy2(Path(snap, "finn.db"), db)
        return {"restored": "snapshot"}
    from .. import demo

    return demo.reset(s)


@app.get("/api/system/eval")
def eval_results():
    p = Path(__file__).resolve().parents[2] / "eval" / "results.json"
    if not p.exists():
        return {"available": False}
    import json

    return {"available": True, **json.loads(p.read_text())}


@app.get("/api/meta/categories")
def categories():
    return [{"key": k, **v} for k, v in CATEGORIES.items()]


# ------------------------------------------------------------------ portfolio & companies

def _company_card(s: Session, c: Company, holdings: set[str]) -> dict:
    rows = market.series(s, c.ticker, 260)
    snap = market.snapshot(rows)
    since = digest.anchor_time(s) - timedelta(days=7)
    sig = s.execute(select(func.count(), func.max(Announcement.score)).where(Announcement.ticker == c.ticker, Announcement.published_at >= since,
                                                                           Announcement.priority.in_(["critical", "high", "medium"]))).one()
    card = results_card(s, c.ticker)
    return {"ticker": c.ticker, "name": c.name, "sector": c.sector, "is_financial": c.is_financial, "in_portfolio": c.ticker in holdings,
            "price": snap, "spark": [r.close for r in rows[-60:]], "signals_7d": sig[0], "top_score_7d": sig[1],
            "latest_quarter": {"period": card["period"], "rows": [{k: r[k] for k in ("metric", "label", "current", "yoy_pct")} for r in card["rows"]]} if card else None,
            "has_documents": bool(s.scalar(select(func.count()).select_from(Document).where(Document.ticker == c.ticker, Document.status == "indexed")))}


@app.get("/api/portfolio")
def get_portfolio(sector: str | None = None, s: Session = Depends(get_session)):
    holdings = set(s.scalars(select(Holding.ticker)).all())
    cos = s.scalars(select(Company).where(Company.ticker.in_(holdings)).order_by(Company.ticker)).all()
    items = [_company_card(s, c, holdings) for c in cos if not sector or c.sector == sector]
    return {"items": items, "sectors": sorted({c.sector for c in cos}), "count": len(items)}


class AddHolding(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)


@app.post("/api/portfolio", status_code=201)
def add_holding(body: AddHolding, bg: BackgroundTasks, s: Session = Depends(get_session)):
    c = pipeline.ensure_company(s, body.ticker)
    if not c:
        raise HTTPException(422, detail={"error": "unknown_ticker", "detail": f"{body.ticker} is not a recognised NSE symbol (or the data source is unreachable)."})
    if not s.scalar(select(Holding.id).where(Holding.ticker == c.ticker)):
        s.add(Holding(ticker=c.ticker))
        s.commit()
    if pipeline.data_mode(s).get("mode") == "live":
        bg.add_task(_bg_ingest, c.ticker, False)
    return {"ok": True, "ticker": c.ticker}


@app.delete("/api/portfolio/{ticker}")
def remove_holding(ticker: str, s: Session = Depends(get_session)):
    h = s.scalar(select(Holding).where(Holding.ticker == ticker.upper()))
    if not h:
        _404(f"{ticker} is not in the portfolio")
    s.delete(h)
    s.commit()
    return {"ok": True}


@app.get("/api/companies/search")
def search_companies(q: str = Query("", max_length=40), s: Session = Depends(get_session)):
    ql = q.strip().upper()
    holdings = set(s.scalars(select(Holding.ticker)).all())
    known = {c.ticker: c for c in s.scalars(select(Company)).all()}
    pool = [{"ticker": t, "name": c.name, "sector": c.sector, "known": True, "in_portfolio": t in holdings} for t, c in known.items()]
    pool += [{"ticker": t, "name": n, "sector": sec, "known": False, "in_portfolio": False} for t, n, sec, _ in ALL if t not in known]
    hits = [p for p in pool if not ql or ql in p["ticker"] or ql in p["name"].upper()]
    hits.sort(key=lambda p: (not p["ticker"].startswith(ql), p["ticker"]))
    if ql and pipeline.TICKER_RE.match(ql) and not any(h["ticker"] == ql for h in hits):
        hits.append({"ticker": ql, "name": f"{ql} (any NSE symbol)", "sector": None, "known": False, "in_portfolio": False})
    return hits[:12]


@app.get("/api/companies/{ticker}")
def company(ticker: str, s: Session = Depends(get_session)):
    c = _ticker(s, ticker)
    return {**_company_card(s, c, set(s.scalars(select(Holding.ticker)).all())), "about": c.about, "source": c.source}


@app.get("/api/companies/{ticker}/prices")
def company_prices(ticker: str, days: int = Query(180, ge=5, le=800), s: Session = Depends(get_session)):
    _ticker(s, ticker)
    rows = market.series(s, ticker.upper(), days)
    return {"ticker": ticker.upper(), "source": rows[-1].source if rows else None, "frequency": "EOD",
            "rows": [{"date": r.date.isoformat(), "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume} for r in rows]}


@app.get("/api/companies/{ticker}/financials")
def company_financials(ticker: str, s: Session = Depends(get_session)):
    _ticker(s, ticker)
    ser = lambda ps: [{"label": p.label, "period_end": p.period_end.isoformat(), "basis": p.basis, "unit": p.unit, "metrics": p.metrics,  # noqa: E731
                       "source": p.source, "source_url": p.source_url} for p in ps]
    return {"ticker": ticker.upper(), "quarterly": ser(periods(s, ticker.upper(), "Q")), "annual": ser(periods(s, ticker.upper(), "Y")),
            "latest_results": results_card(s, ticker.upper())}


@app.get("/api/companies/{ticker}/announcements")
def company_announcements(ticker: str, limit: int = Query(30, le=200), s: Session = Depends(get_session)):
    _ticker(s, ticker)
    anns = s.scalars(select(Announcement).where(Announcement.ticker == ticker.upper()).order_by(Announcement.published_at.desc()).limit(limit)).all()
    cos = {c.ticker: c for c in s.scalars(select(Company)).all()}
    holdings = set(s.scalars(select(Holding.ticker)).all())
    return [digest.serialize(a, cos, holdings) for a in anns]


# ------------------------------------------------------------------ push: signals & digest

def _triage(s: Session) -> dict:
    m = s.get(Meta, "triage")
    return dict(m.value) if m else {}


@app.get("/api/digest")
def get_digest(
    hours: int | None = Query(24, ge=1, le=24 * 90),
    start: datetime | None = None,
    end: datetime | None = None,
    ticker: list[str] | None = Query(None),
    sector: str | None = None,
    category: list[str] | None = Query(None),
    min_priority: Literal["critical", "high", "medium", "low"] | None = None,
    s: Session = Depends(get_session),
):
    d = digest.build(s, hours=hours, start=start, end=end, tickers=ticker, sector=sector, categories=category, min_priority=min_priority)
    tri = _triage(s)
    for it in d["material"] + d["routine"]:
        it["triage"] = tri.get(str(it["id"]))
    d["data_mode"] = pipeline.data_mode(s)
    return d


@app.get("/api/signals")
def list_signals(
    hours: int = Query(24 * 7, ge=1, le=24 * 365),
    priority: list[str] | None = Query(None),
    category: list[str] | None = Query(None),
    ticker: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    s: Session = Depends(get_session),
):
    since = digest.anchor_time(s) - timedelta(hours=hours)
    q = select(Announcement).where(Announcement.published_at >= since)
    if priority:
        q = q.where(Announcement.priority.in_(priority))
    if category:
        q = q.where(Announcement.category.in_(category))
    if ticker:
        q = q.where(Announcement.ticker == ticker.upper())
    total = s.scalar(select(func.count()).select_from(q.subquery()))
    rows = s.scalars(q.order_by(Announcement.score.desc(), Announcement.published_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    cos = {c.ticker: c for c in s.scalars(select(Company)).all()}
    holdings = set(s.scalars(select(Holding.ticker)).all())
    return {"items": [digest.serialize(a, cos, holdings) for a in rows], "page": page, "page_size": page_size, "total": total}


@app.get("/api/signals/{signal_id}")
def get_signal(signal_id: int, s: Session = Depends(get_session)):
    a = s.get(Announcement, signal_id)
    if not a:
        _404("signal not found")
    cos = {c.ticker: c for c in s.scalars(select(Company)).all()}
    holdings = set(s.scalars(select(Holding.ticker)).all())
    d = digest.serialize(a, cos, holdings, full=True)
    d["triage"] = _triage(s).get(str(a.id))
    rows = market.series(s, a.ticker, 40)
    d["price_context"] = [{"date": r.date.isoformat(), "close": r.close, "volume": r.volume} for r in rows]
    d["related"] = [digest.serialize(x, cos, holdings) for x in s.scalars(
        select(Announcement).where(Announcement.ticker == a.ticker, Announcement.id != a.id).order_by(Announcement.published_at.desc()).limit(5))]
    return d


class Triage(BaseModel):
    action: Literal["pin", "dismiss", "clear"]


@app.post("/api/signals/{signal_id}/triage")
def triage(signal_id: int, body: Triage, s: Session = Depends(get_session)):
    if not s.get(Announcement, signal_id):
        _404("signal not found")
    m = s.get(Meta, "triage") or Meta(key="triage", value={})
    v = dict(m.value)
    if body.action == "clear":
        v.pop(str(signal_id), None)
    else:
        v[str(signal_id)] = body.action
    m.value = v
    s.merge(m)
    s.commit()
    return {"ok": True, "triage": v.get(str(signal_id))}


# ------------------------------------------------------------------ pull: research

class Query_(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/research/query")
def research_query(body: Query_, s: Session = Depends(get_session)):
    _ticker(s, body.ticker)
    return answer.answer(s, body.ticker.upper(), body.question.strip())


@app.get("/api/research/{ticker}")
def research_overview(ticker: str, s: Session = Depends(get_session)):
    _ticker(s, ticker)
    out = answer.overview(s, ticker.upper())
    out["documents"] = _docs(s, ticker.upper())
    out["ingestion"] = (s.get(Meta, f"ingest:{ticker.upper()}") or Meta(value={"status": "idle"})).value
    out["data_mode"] = pipeline.data_mode(s)
    return out


def _docs(s: Session, ticker: str) -> list[dict]:
    docs = s.scalars(select(Document).where(Document.ticker == ticker).order_by(Document.period_end.desc())).all()
    return [{"id": d.id, "doc_type": d.doc_type, "title": d.title, "period": d.period_label, "pages": d.pages, "status": d.status,
             "error": d.error, "url": d.url, "source": d.source, "file": f"/api/documents/{d.id}/file" if d.local_path else None,
             "chunks": len(d.chunks)} for d in docs]


@app.get("/api/research/{ticker}/documents")
def research_documents(ticker: str, s: Session = Depends(get_session)):
    _ticker(s, ticker)
    return _docs(s, ticker.upper())


@app.get("/api/research/{ticker}/management-guidance")
def research_guidance(ticker: str, s: Session = Depends(get_session)):
    _ticker(s, ticker)
    return guidance.scorecard(s, ticker.upper())


@app.get("/api/research/{ticker}/financial-health")
def research_health(ticker: str, s: Session = Depends(get_session)):
    _ticker(s, ticker)
    return health.analyse(s, ticker.upper())


@app.get("/api/research/{ticker}/bull-bear")
def research_bull_bear(ticker: str, s: Session = Depends(get_session)):
    _ticker(s, ticker)
    return answer.bull_bear(s, ticker.upper())


def _bg_ingest(ticker: str, docs: bool = True) -> None:
    with session_scope() as s:
        s.merge(Meta(key=f"ingest:{ticker}", value={"status": "running", "at": datetime.utcnow().isoformat()}))
        s.commit()
        try:
            from ..connectors import prices

            pipeline.refresh_prices(s, [ticker])
            res = pipeline.refresh_fundamentals(s, ticker, with_docs=docs)
            s.merge(Meta(key=f"ingest:{ticker}", value={"status": "done", **res}))
        except Exception as e:
            s.rollback()
            s.merge(Meta(key=f"ingest:{ticker}", value={"status": "failed", "detail": str(e)[:300]}))
        s.commit()


@app.post("/api/research/{ticker}/ingest", status_code=202)
def research_ingest(ticker: str, bg: BackgroundTasks, s: Session = Depends(get_session)):
    """Fetch fundamentals + annual report + last 4 transcripts for ANY NSE ticker, then index them."""
    c = pipeline.ensure_company(s, ticker)
    if not c:
        raise HTTPException(422, detail={"error": "unknown_ticker", "detail": f"Could not resolve {ticker} (unknown symbol or data source unreachable)."})
    bg.add_task(_bg_ingest, c.ticker, True)
    return {"ok": True, "ticker": c.ticker, "status": "queued"}


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: int, s: Session = Depends(get_session)):
    d = s.get(Document, doc_id)
    path = Path(d.local_path) if d and d.local_path else None
    if path and not path.exists() and "docs" in path.parts:
        # data built on another machine: resolve the same file under this deployment's docs dir
        path = settings.docs_dir.joinpath(*path.parts[path.parts.index("docs") + 1:])
    if not path or not path.exists():
        _404("document file not available")
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")


# ------------------------------------------------------------------ alerts

def _rule(r: AlertRule) -> dict:
    return {"id": r.id, "ticker": r.ticker, "kind": r.kind, "threshold": r.threshold, "category": r.category, "priority": r.priority,
            "enabled": r.enabled, "description": alerts.describe(r)}


@app.get("/api/alerts")
def get_alerts(limit: int = Query(60, le=300), s: Session = Depends(get_session)):
    rules = s.scalars(select(AlertRule).order_by(AlertRule.id)).all()
    evs = s.execute(select(AlertEvent, AlertRule).join(AlertRule).order_by(AlertEvent.triggered_at.desc()).limit(limit)).all()
    return {"rules": [_rule(r) for r in rules],
            "events": [{"id": e.id, "rule_id": e.rule_id, "kind": r.kind, "priority": r.priority, "ticker": e.ticker, "at": e.triggered_at.isoformat(),
                        "message": e.message, "value": e.value, "announcement_id": e.announcement_id, "seen": e.seen} for e, r in evs],
            "unseen": s.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.seen.is_(False))),
            "monitoring": "Evaluated on each end-of-day refresh."}


class RuleIn(BaseModel):
    ticker: str | None = None
    kind: Literal["price_up", "price_down", "volume", "category"]
    threshold: float | None = Field(None, gt=0, le=100)
    category: str | None = None
    priority: Literal["critical", "high", "medium", "low"] = "high"
    enabled: bool = True


@app.post("/api/alerts", status_code=201)
def create_alert(body: RuleIn, s: Session = Depends(get_session)):
    if body.kind == "category" and body.category not in CATEGORIES:
        raise HTTPException(422, detail={"error": "bad_category", "detail": f"category must be one of {list(CATEGORIES)}"})
    if body.kind != "category" and body.threshold is None:
        raise HTTPException(422, detail={"error": "threshold_required", "detail": "price/volume alerts need a threshold"})
    r = AlertRule(**body.model_dump())
    r.ticker = r.ticker.upper() if r.ticker else None
    s.add(r)
    s.commit()
    alerts.evaluate(s)
    return _rule(r)


class RulePatch(BaseModel):
    threshold: float | None = Field(None, gt=0, le=100)
    enabled: bool | None = None
    priority: Literal["critical", "high", "medium", "low"] | None = None


@app.patch("/api/alerts/{rule_id}")
def patch_alert(rule_id: int, body: RulePatch, s: Session = Depends(get_session)):
    r = s.get(AlertRule, rule_id)
    if not r:
        _404("alert rule not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(r, k, v)
    if body.threshold is not None:  # history for this rule is re-derived under the new threshold
        s.query(AlertEvent).filter(AlertEvent.rule_id == r.id).delete()
    s.commit()
    alerts.evaluate(s)
    return _rule(r)


@app.delete("/api/alerts/{rule_id}")
def delete_alert(rule_id: int, s: Session = Depends(get_session)):
    r = s.get(AlertRule, rule_id)
    if not r:
        _404("alert rule not found")
    s.query(AlertEvent).filter(AlertEvent.rule_id == r.id).delete()
    s.delete(r)
    s.commit()
    return {"ok": True}


@app.post("/api/alerts/seen")
def mark_seen(s: Session = Depends(get_session)):
    s.query(AlertEvent).filter(AlertEvent.seen.is_(False)).update({"seen": True})
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ settings

@app.get("/api/settings/materiality")
def get_weights(s: Session = Depends(get_session)):
    m = s.get(Meta, "materiality_weights")
    return {"weights": m.value if m else materiality.DEFAULT_WEIGHTS, "bands": materiality.BANDS}


class Weights(BaseModel):
    category: float = Field(ge=0, le=1)
    financial: float = Field(ge=0, le=1)
    deviation: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)


@app.put("/api/settings/materiality")
def put_weights(body: Weights, s: Session = Depends(get_session)):
    w = body.model_dump()
    tot = sum(w.values())
    if tot <= 0:
        raise HTTPException(422, detail={"error": "bad_weights", "detail": "weights must sum to > 0"})
    w = {k: round(v / tot, 4) for k, v in w.items()}  # normalise to 1
    s.merge(Meta(key="materiality_weights", value=w))
    s.commit()
    signals.process(s, force=True)
    return {"weights": w}


# ------------------------------------------------------------------ static frontend (single-URL deploy)

if settings.frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            _404("no such endpoint")
        f = settings.frontend_dist / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(settings.frontend_dist / "index.html")
