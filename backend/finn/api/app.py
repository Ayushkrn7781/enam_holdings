"""FastAPI app: thin handlers over the services. Also serves the built SPA."""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import db as DB
from .. import demo
from ..config import BACKEND_DIR, now_ist, settings
from ..db import get_meta, init_db, session_scope, set_meta
from ..models import (AlertEvent, AlertRule, Announcement, Chunk, Company, Document, FinancialPeriod, Guidance, Holding,
                      Price)
from ..research import answer as R, guidance as G, health as H, retrieval
from ..research.periods import quarter_label
from ..services import alerts as AL, digest as D, llm, market, materiality as M, results, signals
from ..services.taxonomy import IMPORTANCE, LABELS, categories
from ..universe import ALL, BY_TICKER, normalise, valid_ticker

log = logging.getLogger("finn.api")
app = FastAPI(title="FINN", version="1.0", description="Financial investment agent: push digest + grounded research")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- lifecycle + middleware
def restore_snapshot(force: bool = False) -> bool:
    snap = settings.snapshot_dir / "finn.db"
    dbp = settings.db_path
    if dbp is None or not snap.exists():
        return False
    if dbp.exists() and not force:
        return False
    DB.dispose()
    for suf in ("", "-wal", "-shm"):
        p = Path(str(dbp) + suf)
        if p.exists():
            p.unlink()
    dbp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(snap, dbp)
    src_docs = settings.snapshot_dir / "docs"
    if src_docs.exists():
        dest = settings.docs_dir
        shutil.copytree(src_docs, dest, dirs_exist_ok=True)
    retrieval.invalidate()
    return True


@app.on_event("startup")
def _startup() -> None:
    restore_snapshot()
    init_db()
    with session_scope() as s:
        if s.scalars(select(Company)).first() is None:
            demo.reset(s)


@app.middleware("http")
async def _timing(request: Request, call_next):
    t0 = time.perf_counter()
    resp = await call_next(request)
    resp.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - t0) * 1000:.1f}"
    return resp


@app.exception_handler(HTTPException)
async def _http_exc(_req: Request, exc: HTTPException):
    code = {404: "not_found", 422: "invalid", 400: "bad_request"}.get(exc.status_code, "error")
    return JSONResponse({"error": code, "detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def _any_exc(_req: Request, exc: Exception):
    log.exception("unhandled")
    return JSONResponse({"error": "internal_error", "detail": str(exc)[:300]}, status_code=500)


def _404(what: str):
    raise HTTPException(404, what)


def _ticker(t: str) -> str:
    t = normalise(t)
    if not valid_ticker(t):
        raise HTTPException(422, f"'{t}' is not a valid NSE symbol")
    return t


# ---------------------------------------------------------------- system
@app.get("/api/health")
def health_check():
    return {"ok": True, "time": now_ist().isoformat(timespec="seconds")}


@app.get("/api/system/data-status")
def data_status():
    with session_scope() as s:
        counts = {name: s.scalar(select(func.count()).select_from(m)) for name, m in (
            ("companies", Company), ("holdings", Holding), ("prices", Price), ("announcements", Announcement),
            ("financial_periods", FinancialPeriod), ("documents", Document), ("chunks", Chunk), ("guidance", Guidance),
            ("alert_rules", AlertRule), ("alert_events", AlertEvent))}
        last = s.scalar(select(func.max(Price.date)))
        mode = get_meta(s, "data_mode", "demo")
        return {"mode": mode, "sources": get_meta(s, "source_status", {}), "counts": counts,
                "last_eod_session": last.isoformat() if last else None, "anchor": AL.anchor(s).isoformat(),
                "monitoring_note": AL.MONITORING_NOTE, "llm": llm.stats(), "retrieval": retrieval.mode(),
                "refresh_command": "./run.sh refresh   (or: cd backend && python -m finn.refresh)",
                "demo_note": ("ILLUSTRATIVE DEMO DATA: synthetic figures, fictional people, frozen at "
                              f"{demo.DEMO_TODAY:%d %b %Y}. Run a live refresh to replace it.") if mode == "demo" else None}


@app.post("/api/system/demo-reset")
def demo_reset():
    if restore_snapshot(force=True):
        init_db()
        return {"ok": True, "method": "snapshot"}
    with session_scope() as s:
        out = demo.reset(s)
    retrieval.invalidate()
    return {"ok": True, "method": "rebuild", **out}


@app.get("/api/system/eval")
def eval_results():
    p = BACKEND_DIR / "eval" / "results.json"
    if not p.exists():
        return {"available": False}
    return {"available": True, **json.loads(p.read_text())}


@app.get("/api/meta/categories")
def meta_categories():
    return {"categories": categories()}


# ---------------------------------------------------------------- portfolio + companies
def _price_rows(s, t, days: Optional[int] = None):
    q = select(Price).where(Price.ticker == t).order_by(Price.date)
    rows = s.scalars(q).all()
    return rows[-days:] if days else rows


def _portfolio_item(s, c: Company, in_pf: bool, since: datetime) -> dict:
    rows = _price_rows(s, c.ticker)
    snap = market.snapshot(rows) if rows else None
    sig = s.scalars(select(Announcement).where(Announcement.ticker == c.ticker, Announcement.published_at >= since,
                                               Announcement.is_duplicate_of.is_(None))).all()
    material = [a for a in sig if a.priority in ("critical", "high", "medium")]
    top = max(material, key=lambda a: a.score or 0, default=None)
    card = results.results_card(s, c.ticker)
    lq = None
    if card:
        r = {x["key"]: x for x in card["rows"]}
        lq = {"period_label": card["period_label"], "revenue_yoy": r["revenue"]["yoy"], "pat_yoy": r["pat"]["yoy"]}
    has_docs = s.scalars(select(Document.id).where(Document.ticker == c.ticker, Document.status == "indexed")).first()
    return {"ticker": c.ticker, "name": c.name, "sector": c.sector, "is_financial": c.is_financial, "in_portfolio": in_pf,
            "price": snap, "spark": [r.close for r in rows[-60:]], "signals_7d": len(material),
            "top_score_7d": top.score if top else None, "top_priority_7d": top.priority if top else None,
            "latest_quarter": lq, "has_documents": bool(has_docs), "source": c.source}


@app.get("/api/portfolio")
def portfolio():
    with session_scope() as s:
        at = AL.anchor(s)
        hs = s.scalars(select(Holding)).all()
        items = []
        for h in hs:
            c = s.get(Company, h.ticker)
            if c:
                items.append(_portfolio_item(s, c, True, at - timedelta(days=7)))
        items.sort(key=lambda x: x["ticker"])
        sectors = sorted({i["sector"] for i in items if i["sector"]})
        rets = [i["price"]["return_pct"] for i in items if i["price"] and i["price"]["return_pct"] is not None]
        last = max((i["price"]["date"] for i in items if i["price"]), default=None)
        return {"items": items, "sectors": sectors, "count": len(items),
                "summary": {"equal_weight_move": round(sum(rets) / len(rets), 2) if rets else None,
                            "up": sum(r > 0 for r in rets), "down": sum(r < 0 for r in rets), "date": last},
                "data_mode": get_meta(s, "data_mode", "demo")}


class AddHolding(BaseModel):
    ticker: str


@app.post("/api/portfolio")
def portfolio_add(body: AddHolding):
    from ..services.pipeline import ensure_company
    t = _ticker(body.ticker)
    with session_scope() as s:
        c = ensure_company(s, t)
        if c is None:
            raise HTTPException(422, f"Could not find NSE company '{t}'")
        if not s.scalars(select(Holding).where(Holding.ticker == t)).first():
            s.add(Holding(ticker=t, source=c.source))
        s.flush()
        return _portfolio_item(s, c, True, AL.anchor(s) - timedelta(days=7))


@app.delete("/api/portfolio/{ticker}")
def portfolio_remove(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        h = s.scalars(select(Holding).where(Holding.ticker == t)).first()
        if not h:
            _404(f"{t} is not in the portfolio")
        s.delete(h)
        return {"ok": True, "ticker": t}


@app.get("/api/companies/search")
def companies_search(q: str = ""):
    qq = q.strip().upper()
    with session_scope() as s:
        known = {c.ticker: c for c in s.scalars(select(Company)).all()}
        held = {h.ticker for h in s.scalars(select(Holding)).all()}
        pool = {t: (n, sec) for t, n, sec, _ in ALL}
        for t, c in known.items():
            pool[t] = (c.name, c.sector)
        out = []
        for t, (n, sec) in sorted(pool.items()):
            if not qq or qq in t or qq in (n or "").upper():
                out.append({"ticker": t, "name": n, "sector": sec, "in_portfolio": t in held, "known": t in known})
        out.sort(key=lambda x: (not x["ticker"].startswith(qq), x["ticker"]))
        out = out[:12]
        if qq and valid_ticker(qq) and qq not in pool:
            out.append({"ticker": qq, "name": f"{qq} (any NSE symbol)", "sector": None, "in_portfolio": False,
                        "known": False})
        return {"results": out}


@app.get("/api/companies/{ticker}")
def company(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        c = s.get(Company, t)
        if not c:
            _404(f"Unknown company {t}")
        rows = _price_rows(s, t)
        held = bool(s.scalars(select(Holding).where(Holding.ticker == t)).first())
        return {"ticker": c.ticker, "name": c.name, "sector": c.sector, "is_financial": c.is_financial, "about": c.about,
                "source": c.source, "in_portfolio": held, "price": market.snapshot(rows) if rows else None,
                "spark": [r.close for r in rows[-120:]]}


@app.get("/api/companies/{ticker}/prices")
def company_prices(ticker: str, days: int = Query(120, ge=5, le=400)):
    t = _ticker(ticker)
    with session_scope() as s:
        rows = _price_rows(s, t, days)
        return {"ticker": t, "prices": [{"date": r.date.isoformat(), "close": r.close, "volume": r.volume,
                                         "source": r.source} for r in rows]}


@app.get("/api/companies/{ticker}/financials")
def company_financials(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        out = {}
        for pt in ("Q", "Y"):
            out["quarters" if pt == "Q" else "annual"] = [
                {"period_end": p.period_end.isoformat(), "label": quarter_label(p.period_end) if pt == "Q" else p.label,
                 "basis": p.basis, "unit": p.unit, "metrics": p.metrics, "source": p.source}
                for p in results.periods(s, t, pt)]
        return {"ticker": t, **out}


@app.get("/api/companies/{ticker}/announcements")
def company_announcements(ticker: str, limit: int = 30):
    t = _ticker(ticker)
    with session_scope() as s:
        c = s.get(Company, t)
        rows = s.scalars(select(Announcement).where(Announcement.ticker == t)
                         .order_by(Announcement.published_at.desc()).limit(limit)).all()
        return {"ticker": t, "items": [D.serialize(a, c) for a in rows]}


# ---------------------------------------------------------------- push
def _parse_dt(x: Optional[str]) -> Optional[datetime]:
    if not x:
        return None
    try:
        return datetime.fromisoformat(x)
    except ValueError:
        raise HTTPException(422, f"Bad date '{x}'")


@app.get("/api/digest")
def digest(hours: int = Query(24, ge=1, le=2160), start: Optional[str] = None, end: Optional[str] = None,
           ticker: Optional[list[str]] = Query(None), sector: Optional[str] = None,
           category: Optional[list[str]] = Query(None), min_priority: Optional[str] = None):
    st, en = _parse_dt(start), _parse_dt(end)
    if st and en and en < st:
        raise HTTPException(422, "end is before start")
    if st and en and en.time() == datetime.min.time() and len(end or "") <= 10:
        en = en + timedelta(days=1) - timedelta(seconds=1)
    with session_scope() as s:
        return D.build(s, hours, st, en, [normalise(t) for t in ticker] if ticker else None, sector, category,
                       min_priority)


@app.get("/api/signals")
def signals_list(hours: int = Query(168, ge=1, le=2160), priority: Optional[list[str]] = Query(None),
                 category: Optional[list[str]] = Query(None), ticker: Optional[str] = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    with session_scope() as s:
        at = AL.anchor(s)
        q = select(Announcement).where(Announcement.published_at >= at - timedelta(hours=hours),
                                       Announcement.published_at <= at)
        if priority:
            q = q.where(Announcement.priority.in_(priority))
        if category:
            q = q.where(Announcement.category.in_(category))
        if ticker:
            q = q.where(Announcement.ticker == normalise(ticker))
        rows = s.scalars(q.order_by(Announcement.score.desc())).all()
        comps = {c.ticker: c for c in s.scalars(select(Company)).all()}
        triage = get_meta(s, "triage", {}) or {}
        page_rows = rows[(page - 1) * page_size: page * page_size]
        return {"total": len(rows), "page": page, "page_size": page_size,
                "items": [D.serialize(a, comps.get(a.ticker), triage.get(str(a.id))) for a in page_rows]}


@app.get("/api/signals/{sid}")
def signal_detail(sid: int):
    with session_scope() as s:
        a = s.get(Announcement, sid)
        if not a:
            _404(f"Signal {sid} not found")
        c = s.get(Company, a.ticker)
        triage = (get_meta(s, "triage", {}) or {}).get(str(a.id))
        out = D.serialize(a, c, triage, detail=True)
        held = bool(s.scalars(select(Holding).where(Holding.ticker == a.ticker)).first())
        out["in_portfolio"] = held
        rows = _price_rows(s, a.ticker)
        rd = signals.reaction_date(a.published_at)
        idx = next((i for i, r in enumerate(rows) if r.date >= rd), len(rows))
        ctx = rows[max(0, idx - 30): idx + 10]
        out["price_context"] = {"filing_date": a.published_at.date().isoformat(), "reaction_date": rd.isoformat(),
                                "prices": [{"date": r.date.isoformat(), "close": r.close, "volume": r.volume}
                                           for r in ctx]}
        rel = s.scalars(select(Announcement).where(Announcement.ticker == a.ticker, Announcement.id != a.id)
                        .order_by(Announcement.published_at.desc()).limit(5)).all()
        out["related"] = [D.serialize(r, c) for r in rel]
        return out


class Triage(BaseModel):
    action: str = Field(pattern="^(pin|dismiss|clear)$")


@app.post("/api/signals/{sid}/triage")
def signal_triage(sid: int, body: Triage):
    with session_scope() as s:
        if not s.get(Announcement, sid):
            _404(f"Signal {sid} not found")
        tri = get_meta(s, "triage", {}) or {}
        if body.action == "clear":
            tri.pop(str(sid), None)
        else:
            tri[str(sid)] = body.action
        set_meta(s, "triage", tri)
        return {"ok": True, "id": sid, "triage": tri.get(str(sid))}


# ---------------------------------------------------------------- pull
class Query_(BaseModel):
    ticker: str
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/research/query")
def research_query(body: Query_):
    t = _ticker(body.ticker)
    with session_scope() as s:
        if not s.get(Company, t):
            from ..services.pipeline import ensure_company
            if ensure_company(s, t) is None:
                _404(f"Unknown company {t}")
        return R.answer(s, t, body.question)


def _require_company(s, t):
    c = s.get(Company, t)
    if not c:
        _404(f"Unknown company {t}. Add it from search to fetch its data.")
    return c


@app.get("/api/research/{ticker}")
def research_overview(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        c = _require_company(s, t)
        docs = s.scalars(select(Document).where(Document.ticker == t)).all()
        held = bool(s.scalars(select(Holding).where(Holding.ticker == t)).first())
        rows = _price_rows(s, t)
        return {"ticker": t, "name": c.name, "sector": c.sector, "is_financial": c.is_financial, "source": c.source,
                "in_portfolio": held, "price": market.snapshot(rows) if rows else None,
                "spark": [r.close for r in rows[-120:]], "overview": R.overview(s, t),
                "documents": [_doc(s, d) for d in docs], "ingestion": get_meta(s, f"ingest:{t}"),
                "data_mode": get_meta(s, "data_mode", "demo")}


def _doc(s, d: Document) -> dict:
    n = s.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == d.id))
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "period": d.period_label, "pages": d.pages,
            "passages": n, "status": d.status, "error": d.error, "url": d.url, "source": d.source,
            "file_url": f"/api/documents/{d.id}/file" if d.local_path else None}


@app.get("/api/research/{ticker}/documents")
def research_documents(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        _require_company(s, t)
        return {"ticker": t, "documents": [_doc(s, d) for d in s.scalars(select(Document).where(Document.ticker == t))],
                "ingestion": get_meta(s, f"ingest:{t}")}


@app.get("/api/research/{ticker}/management-guidance")
def research_guidance(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        _require_company(s, t)
        return G.scorecard(s, t)


@app.get("/api/research/{ticker}/financial-health")
def research_health(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        _require_company(s, t)
        return H.assess(s, t)


@app.get("/api/research/{ticker}/bull-bear")
def research_bull_bear(ticker: str):
    t = _ticker(ticker)
    with session_scope() as s:
        _require_company(s, t)
        return R.bull_bear(s, t)


def _ingest_job(t: str) -> None:
    from ..services import pipeline
    with session_scope() as s:
        set_meta(s, f"ingest:{t}", {"status": "running", "at": now_ist().isoformat(timespec="seconds")})
    steps = {}
    with session_scope() as s:
        try:
            pipeline.ensure_company(s, t)
            steps["prices"] = pipeline.refresh_prices(s, [t])
        except Exception as e:
            steps["prices"] = f"failed: {str(e)[:160]}"
    with session_scope() as s:
        try:
            steps["fundamentals"] = pipeline.refresh_fundamentals(s, t, with_docs=True)
        except Exception as e:
            steps["fundamentals"] = f"failed: {str(e)[:160]}"
    ok = not any(isinstance(v, str) and v.startswith("failed") for v in steps.values())
    with session_scope() as s:
        set_meta(s, f"ingest:{t}", {"status": "done" if ok else "failed", "steps": steps,
                                    "at": now_ist().isoformat(timespec="seconds")})


@app.post("/api/research/{ticker}/ingest", status_code=202)
def research_ingest(ticker: str, bg: BackgroundTasks):
    t = _ticker(ticker)
    bg.add_task(_ingest_job, t)
    return {"accepted": True, "ticker": t,
            "note": "Fetching prices, screener.in financials and documents in the background."}


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: int):
    with session_scope() as s:
        d = s.get(Document, doc_id)
        if not d or not d.local_path:
            _404("Document file not available")
        p = Path(d.local_path)
        if not p.exists():
            parts = p.parts
            if "docs" in parts:
                p = settings.docs_dir.joinpath(*parts[len(parts) - parts[::-1].index("docs"):])
        if not p.exists():
            _404("Document file missing on this deployment")
        return FileResponse(str(p), media_type="application/pdf",
                            headers={"Content-Disposition": f'inline; filename="{p.name}"'})


# ---------------------------------------------------------------- alerts
class RuleIn(BaseModel):
    kind: str = Field(pattern="^(price_up|price_down|volume|category)$")
    threshold: Optional[float] = None
    category: Optional[str] = None
    ticker: Optional[str] = None
    priority: str = Field("medium", pattern="^(critical|high|medium|low)$")
    enabled: bool = True


class RulePatch(BaseModel):
    threshold: Optional[float] = None
    enabled: Optional[bool] = None
    priority: Optional[str] = Field(None, pattern="^(critical|high|medium|low)$")


def _alerts_payload(s) -> dict:
    rules = s.scalars(select(AlertRule).order_by(AlertRule.id)).all()
    by_id = {r.id: r for r in rules}
    evs = s.scalars(select(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(200)).all()
    return {"rules": [AL.serialize_rule(r) for r in rules],
            "events": [AL.serialize_event(e, by_id.get(e.rule_id)) for e in evs],
            "unseen": sum(1 for e in evs if not e.seen), "monitoring_note": AL.MONITORING_NOTE,
            "categories": [{"key": k, "label": LABELS[k]} for k in IMPORTANCE if k != "unclassified"]}


@app.get("/api/alerts")
def alerts_list():
    with session_scope() as s:
        return _alerts_payload(s)


@app.post("/api/alerts")
def alerts_create(body: RuleIn):
    if body.kind == "category" and body.category not in IMPORTANCE:
        raise HTTPException(422, "Unknown category for a category alert")
    if body.kind != "category" and (body.threshold is None or body.threshold <= 0):
        raise HTTPException(422, "Price and volume alerts need a positive threshold")
    with session_scope() as s:
        r = AlertRule(kind=body.kind, threshold=body.threshold if body.kind != "category" else None,
                      category=body.category if body.kind == "category" else None,
                      ticker=_ticker(body.ticker) if body.ticker else None, priority=body.priority,
                      enabled=body.enabled, source="user")
        s.add(r)
        s.flush()
        AL.evaluate(s)
        return AL.serialize_rule(r)


@app.patch("/api/alerts/{rid}")
def alerts_patch(rid: int, body: RulePatch):
    with session_scope() as s:
        r = s.get(AlertRule, rid)
        if not r:
            _404(f"Alert rule {rid} not found")
        if body.threshold is not None and r.kind != "category":
            if body.threshold <= 0:
                raise HTTPException(422, "Threshold must be positive")
            if body.threshold != r.threshold:
                r.threshold = body.threshold
                AL.reset_rule_events(s, r.id)
        if body.enabled is not None:
            r.enabled = body.enabled
        if body.priority:
            r.priority = body.priority
        s.flush()
        AL.evaluate(s)
        return AL.serialize_rule(r)


@app.delete("/api/alerts/{rid}")
def alerts_delete(rid: int):
    with session_scope() as s:
        r = s.get(AlertRule, rid)
        if not r:
            _404(f"Alert rule {rid} not found")
        AL.reset_rule_events(s, r.id)
        s.delete(r)
        return {"ok": True}


@app.post("/api/alerts/seen")
def alerts_seen():
    with session_scope() as s:
        for e in s.scalars(select(AlertEvent).where(AlertEvent.seen.is_(False))).all():
            e.seen = True
        return {"ok": True}


# ---------------------------------------------------------------- settings
@app.get("/api/settings/materiality")
def get_weights():
    with session_scope() as s:
        return {"weights": M.normalise_weights(get_meta(s, "materiality_weights")), "defaults": M.DEFAULT_WEIGHTS,
                "labels": M.COMPONENT_LABELS}


class Weights(BaseModel):
    weights: dict[str, float]


@app.put("/api/settings/materiality")
def put_weights(body: Weights):
    w = M.normalise_weights(body.weights)
    with session_scope() as s:
        set_meta(s, "materiality_weights", w)
        s.flush()
        n = signals.process(s, force=True)
        AL.evaluate(s)
        return {"weights": w, "rescored": n}


# ---------------------------------------------------------------- SPA
_dist = settings.frontend_dist
if (_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/") or path == "api":
        raise HTTPException(404, f"No API route /{path}")
    f = _dist / path
    if path and f.is_file() and _dist in f.resolve().parents:
        return FileResponse(str(f))
    index = _dist / "index.html"
    if index.exists():
        return FileResponse(str(index), headers={"Cache-Control": "no-cache"})  # hashed assets cache; the shell must not
    return JSONResponse({"error": "not_found", "detail": "Frontend not built. Run: cd frontend && npm run build"},
                        status_code=404)
