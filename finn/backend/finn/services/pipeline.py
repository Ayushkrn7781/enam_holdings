"""Live ingestion orchestration, shared by the `python -m finn.refresh` CLI and the API's on-demand research.

Each source runs independently and records its own status — one blocked source never stops the others,
and a failure is reported, never papered over with fabricated data.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import now_ist, settings
from ..models import (AlertEvent, Announcement, Chunk, Company, Document, FinancialPeriod, Guidance, Holding, Meta, Price)
from ..universe import ALL, PORTFOLIO
from . import alerts, signals, taxonomy

log = logging.getLogger("finn.pipeline")
TICKER_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")


def set_status(s: Session, source: str, ok: bool, detail: str) -> None:
    m = s.get(Meta, "source_status") or Meta(key="source_status", value={})
    v = dict(m.value)
    v[source] = {"ok": ok, "detail": detail, "at": now_ist().isoformat(timespec="seconds")}
    m.value = v
    s.merge(m)
    s.commit()


def data_mode(s: Session) -> dict:
    m = s.get(Meta, "data_mode")
    return m.value if m else {"mode": "empty"}


def purge_demo(s: Session) -> None:
    """Switching to live data removes every illustrative row so the two can never mix."""
    for M in (Price, FinancialPeriod, Announcement):
        s.execute(delete(M).where(M.source == "demo"))
    demo_docs = s.scalars(select(Document.id).where(Document.source == "demo")).all()
    if demo_docs:
        s.execute(delete(Guidance).where(Guidance.document_id.in_(demo_docs)))
        s.execute(delete(Chunk).where(Chunk.document_id.in_(demo_docs)))
        s.execute(delete(Document).where(Document.id.in_(demo_docs)))
    s.execute(delete(AlertEvent))
    s.commit()


def ensure_company(s: Session, ticker: str) -> Company | None:
    ticker = ticker.upper().strip()
    if not TICKER_RE.match(ticker):
        return None
    c = s.get(Company, ticker)
    if c:
        return c
    seed = next((x for x in ALL if x[0] == ticker), None)
    if seed:
        c = Company(ticker=ticker, name=seed[1], sector=seed[2], is_financial=seed[3], source="seed")
    else:
        from ..connectors import prices

        info = prices.company_info(ticker)
        if not info:
            return None
        c = Company(ticker=ticker, name=info["name"], sector=info["sector"], is_financial=info["is_financial"], about=info["about"], source="yfinance")
    s.add(c)
    s.commit()
    return c


def refresh_prices(s: Session, tickers: list[str]) -> None:
    from ..connectors import prices

    try:
        data = prices.fetch(tickers)
        n = sum(prices.store(s, t, rows) for t, rows in data.items())
        missing = [t for t, r in data.items() if not r]
        s.commit()
        set_status(s, "prices", n > 0, f"{n} EOD rows for {len(tickers) - len(missing)}/{len(tickers)} tickers" + (f"; missing {', '.join(missing)}" if missing else ""))
    except Exception as e:
        s.rollback()
        log.exception("price refresh failed")
        set_status(s, "prices", False, f"yfinance failed: {e}")


def refresh_announcements(s: Session, tickers: list[str], days: int = 7) -> None:
    from ..connectors.nse import NSEClient

    cli = NSEClient()
    end = now_ist().date()
    start = end - timedelta(days=days)
    n_new, n_att, errors = 0, 0, []
    for t in tickers:
        try:
            for a in cli.announcements(t, start, end):
                if s.scalar(select(Announcement.id).where(Announcement.dedupe_key == a["dedupe_key"])):
                    continue
                # cost discipline: only download attachments for filings the rules don't already call routine
                pre = taxonomy.classify(a["subject"], a["exchange_category"])
                if a["attachment_url"] and pre.category not in ("unclassified", "investor_meetings", "agm_egm", "postal_ballot", "earnings_call"):
                    a["attachment_text"] = cli.pdf_text(a["attachment_url"])
                    n_att += bool(a["attachment_text"])
                s.add(Announcement(**a))
                n_new += 1
            s.commit()
        except Exception as e:
            s.rollback()
            errors.append(f"{t}: {str(e)[:80]}")
    ok = n_new > 0 or not errors
    set_status(s, "announcements", ok, f"{n_new} new filings, {n_att} attachments parsed" + (f"; {len(errors)} errors (e.g. {errors[0]})" if errors else ""))


def refresh_fundamentals(s: Session, ticker: str, with_docs: bool = False, max_transcripts: int = 4) -> dict:
    from ..connectors.screener import ScreenerClient
    from ..research import guidance
    from ..research.ingest import index_pdf
    from ..research.periods import quarter_label

    cli = ScreenerClient()
    f = cli.fundamentals(ticker)
    c = ensure_company(s, ticker)
    if c:
        c.is_financial = f["is_financial"] or c.is_financial
        c.about = c.about or f["about"]
    for ptype, rows in (("Q", f["quarters"]), ("Y", f["annual"])):
        for r in rows:
            existing = s.scalar(select(FinancialPeriod).where(FinancialPeriod.ticker == ticker, FinancialPeriod.period_type == ptype,
                                                              FinancialPeriod.period_end == r["period_end"], FinancialPeriod.basis == f["basis"]))
            if existing:
                existing.metrics, existing.source_url = r["metrics"], f["url"]
            else:
                s.add(FinancialPeriod(ticker=ticker, period_type=ptype, period_end=r["period_end"], label=r["label"], basis=f["basis"],
                                      metrics=r["metrics"], source="screener", source_url=f["url"]))
    s.commit()
    n_docs = 0
    if with_docs:
        txs = [d for d in f["documents"] if d["doc_type"] == "transcript"][:max_transcripts]
        ars = [d for d in f["documents"] if d["doc_type"] == "annual_report"][:1]
        for d in ars + txs:
            doc = s.scalar(select(Document).where(Document.ticker == ticker, Document.url == d["url"]))
            if not doc:
                pe = d.get("period_end")
                label = d.get("period_label")
                if d["doc_type"] == "transcript" and d.get("call_date"):
                    # a call in month M discusses the quarter that ended ~1-2 months earlier
                    cd = d["call_date"]
                    qm, qy = ((cd.month - 1) // 3) * 3, cd.year  # most recent quarter-end strictly before the call month
                    if qm == 0:
                        qm, qy = 12, cd.year - 1
                    import calendar

                    pe = date(qy, qm, calendar.monthrange(qy, qm)[1])
                    label = quarter_label(pe)
                doc = Document(ticker=ticker, doc_type=d["doc_type"], title=d["title"], url=d["url"], period_label=label, period_end=pe, source="screener")
                s.add(doc)
                s.flush()
            if doc.status != "indexed":
                path = settings.docs_dir / f"{ticker}_{doc.id}.pdf"
                if cli.download(doc.url, path):
                    doc.local_path = str(path)
                    n_docs += bool(index_pdf(s, doc))
                else:
                    doc.status, doc.error = "failed", "download failed or not a PDF"
            s.commit()
        guidance.extract(s, ticker)
    return {"ticker": ticker, "quarters": len(f["quarters"]), "years": len(f["annual"]), "documents_indexed": n_docs, "basis": f["basis"]}


def refresh_all(s: Session, tickers: list[str] | None = None, research: list[str] | None = None, days: int = 7, docs: bool = True) -> dict:
    holdings = tickers or s.scalars(select(Holding.ticker)).all() or [p[0] for p in PORTFOLIO]
    if data_mode(s).get("mode") == "demo":
        purge_demo(s)
    for t in holdings:
        ensure_company(s, t)
        if not s.scalar(select(Holding.id).where(Holding.ticker == t)):
            s.add(Holding(ticker=t))
    s.commit()
    research = research or []
    refresh_prices(s, list(dict.fromkeys(holdings + research)))
    refresh_announcements(s, holdings, days)
    fund_ok, fund_err = 0, []
    for t in dict.fromkeys(holdings + research):
        try:
            refresh_fundamentals(s, t, with_docs=docs and t in research)
            fund_ok += 1
        except Exception as e:
            s.rollback()
            fund_err.append(f"{t}: {str(e)[:60]}")
    set_status(s, "fundamentals", fund_ok > 0, f"{fund_ok} companies" + (f"; failed: {'; '.join(fund_err[:3])}" if fund_err else ""))
    s.merge(Meta(key="data_mode", value={"mode": "live", "as_of": now_ist().date().isoformat(), "generated_at": now_ist().isoformat(timespec="seconds"),
                                         "note": "Live EOD data from Yahoo Finance, NSE filings and screener.in, as of the last refresh."}))
    s.commit()
    alerts.seed_defaults(s)
    signals.process(s, force=True)
    alerts.evaluate(s)
    return {"holdings": len(holdings), "research": research, "status": s.get(Meta, "source_status").value}
