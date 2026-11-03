"""Live ingestion pipeline. Each source runs independently; failures are recorded, never papered over."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import now_ist, settings
from ..db import get_meta, set_meta
from ..models import (AlertEvent, Announcement, Chunk, Company, Document, FinancialPeriod, Guidance, Holding, Price)
from ..research import guidance as G, ingest
from ..research.periods import fy_label, month_label, prev_quarter_end_before, quarter_label
from ..universe import BY_TICKER, PORTFOLIO, valid_ticker
from . import alerts, signals
from .taxonomy import classify_rules

log = logging.getLogger("finn.pipeline")
SKIP_ATTACH = {"unclassified", "investor_meetings", "agm_egm", "postal_ballot", "earnings_call"}


def _status(s: Session, source: str, ok: bool, detail: str) -> None:
    st = get_meta(s, "source_status", {}) or {}
    st[source] = {"ok": ok, "detail": detail, "at": now_ist().isoformat(timespec="seconds")}
    set_meta(s, "source_status", st)


def ensure_company(s: Session, ticker: str) -> Optional[Company]:
    if not valid_ticker(ticker):
        return None
    c = s.get(Company, ticker)
    if c:
        return c
    if ticker in BY_TICKER:
        t, n, sec, fin = BY_TICKER[ticker]
        c = Company(ticker=t, name=n, sector=sec, is_financial=fin, source="nse")
    else:
        from ..connectors.prices import company_info
        info = company_info(ticker)
        if not info:
            return None
        c = Company(**info)
    s.add(c)
    s.flush()
    return c


def purge_demo(s: Session) -> None:
    for model in (AlertEvent, Guidance, Chunk, Document, Announcement, FinancialPeriod, Price, Holding, Company):
        if hasattr(model, "source"):
            s.execute(delete(model).where(model.source == "demo"))
    s.flush()


def refresh_prices(s: Session, tickers: list[str]) -> int:
    from ..connectors.prices import fetch, upsert_prices
    data = fetch(tickers)
    n = 0
    for t, rows in data.items():
        n += upsert_prices(s, rows)
    return n


def refresh_announcements(s: Session, tickers: list[str], days: int = 7) -> int:
    from ..connectors.nse import NSE
    nse = NSE()
    end = now_ist().date()
    start = end - timedelta(days=days)
    n = 0
    for t in tickers:
        for a in nse.announcements(t, start, end):
            if not a["published_at"] or s.scalars(select(Announcement.id).where(
                    Announcement.dedupe_key == a["dedupe_key"])).first():
                continue
            pre = classify_rules(a["subject"], a["exchange_category"], a["body"])
            if a["attachment_url"] and (pre is None or pre[0] not in SKIP_ATTACH):
                a["attachment_text"] = nse.pdf_text(a["attachment_url"])  # cost discipline: only for material types
            s.add(Announcement(**a))
            n += 1
        s.flush()
        import time
        time.sleep(0.7)
    return n


def transcript_quarter(call_month: str) -> Optional[date]:
    m = re.search(r"([A-Za-z]{3})\s+(\d{4})", call_month or "")
    if not m:
        return None
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    if m.group(1).lower() not in months:
        return None
    return prev_quarter_end_before(int(m.group(2)), months.index(m.group(1).lower()) + 1)


def refresh_fundamentals(s: Session, ticker: str, with_docs: bool = True) -> dict[str, Any]:
    from ..connectors import screener
    data = screener.fetch_company(ticker)
    comp = ensure_company(s, ticker)
    if comp is not None:
        comp.is_financial = comp.is_financial or data["is_financial"]
        if data.get("about"):
            comp.about = data["about"]
    for ptype, table in (("Q", data["quarters"]), ("Y", data["annual"])):
        for d, metrics in table.items():
            row = s.scalars(select(FinancialPeriod).where(
                FinancialPeriod.ticker == ticker, FinancialPeriod.period_type == ptype, FinancialPeriod.period_end == d,
                FinancialPeriod.basis == data["basis"])).first()
            label = month_label(d)
            if row is None:
                s.add(FinancialPeriod(ticker=ticker, period_type=ptype, period_end=d, label=label, basis=data["basis"],
                                      metrics=metrics, source="screener", source_url=data["url"]))
            else:
                row.metrics, row.source, row.source_url = metrics, "screener", data["url"]
    s.flush()
    docs_done = 0
    if with_docs:
        ars = [d for d in data["documents"] if d["doc_type"] == "annual_report"][:1]
        txs = [d for d in data["documents"] if d["doc_type"] == "transcript"][:4]
        for d in ars + txs:
            if d["doc_type"] == "transcript":
                qe = transcript_quarter(d.get("call_month", ""))
                d["period_end"] = qe
                d["period_label"] = quarter_label(qe) if qe else None
            doc = s.scalars(select(Document).where(Document.ticker == ticker, Document.url == d["url"])).first()
            if doc is None:
                doc = Document(ticker=ticker, doc_type=d["doc_type"], title=d["title"], url=d["url"],
                               period_label=d.get("period_label"), period_end=d.get("period_end"), source="screener")
                s.add(doc)
                s.flush()
            dest = settings.docs_dir / ticker / f"{doc.id}.pdf"
            try:
                screener.download(d["url"], dest)
                doc.local_path, doc.status = str(dest), "downloaded"
                ingest.ingest_document(s, doc)
                docs_done += 1
            except Exception as e:
                doc.status, doc.error = "failed", str(e)[:300]
        s.flush()
        G.extract(s, ticker)
    return {"quarters": len(data["quarters"]), "years": len(data["annual"]), "documents": docs_done,
            "basis": data["basis"]}


def refresh_all(s: Session, tickers: Optional[list[str]] = None, research: Optional[list[str]] = None,
                days: int = 7, with_docs: bool = True) -> dict[str, Any]:
    tickers = tickers or [t for t, *_ in PORTFOLIO]
    research = research or []
    if get_meta(s, "data_mode", "demo") == "demo":
        purge_demo(s)
    for t in tickers + research:
        ensure_company(s, t)
    for t in tickers:
        if not s.scalars(select(Holding).where(Holding.ticker == t)).first() and s.get(Company, t):
            s.add(Holding(ticker=t, source="nse"))
    s.flush()
    report: dict[str, Any] = {}
    for name, fn in (("yfinance", lambda: refresh_prices(s, tickers + research)),
                     ("nse", lambda: refresh_announcements(s, tickers, days))):
        try:
            with s.begin_nested():
                n = fn()
            _status(s, name, True, f"{n} rows")
            report[name] = n
        except Exception as e:
            _status(s, name, False, str(e)[:300])
            report[name] = f"failed: {e}"
    ok_f, fail_f = 0, []
    for t in tickers + research:
        try:
            with s.begin_nested():
                refresh_fundamentals(s, t, with_docs=with_docs and t in research)  # docs only for research names
            ok_f += 1
        except Exception as e:
            fail_f.append(f"{t}: {str(e)[:80]}")
    _status(s, "screener", ok_f > 0, f"{ok_f} companies ok" + (f"; failed {', '.join(fail_f[:5])}" if fail_f else ""))
    report["screener"] = {"ok": ok_f, "failed": fail_f}
    set_meta(s, "data_mode", "live")
    alerts.seed_defaults(s)
    signals.process(s, force=True)
    alerts.evaluate(s)
    return report
