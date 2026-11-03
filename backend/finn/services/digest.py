"""Windowed portfolio digest — the morning brief. The executive summary is assembled from data, never generated."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import now_ist
from ..models import AlertEvent, AlertRule, Announcement, Company, Holding, Meta
from .taxonomy import CATEGORIES


def window_bounds(hours: int | None, start: datetime | None, end: datetime | None, anchor: datetime) -> tuple[datetime, datetime]:
    end = end or anchor
    start = start or end - timedelta(hours=hours or 24)
    return start, end


def anchor_time(s: Session) -> datetime:
    """'Now' for the digest, in IST (exchange timestamps are IST).
    The demo dataset is frozen, so it anchors to its latest filing; live data uses the clock."""
    latest = s.scalar(select(Announcement.published_at).order_by(Announcement.published_at.desc()).limit(1))
    mode = s.get(Meta, "data_mode")
    if mode and mode.value.get("mode") == "demo" and latest:
        return latest + timedelta(minutes=1)
    return now_ist()


def _why_rank(br: dict | None) -> str | None:
    """One line on what drives the score: the strongest of size / unusualness, else the category itself."""
    if not br:
        return None
    if br.get("duplicate_of"):
        return "Duplicate of an earlier filing — suppressed."
    cands = [(br[k]["contribution"], br[k]["reason"]) for k in ("financial", "deviation") if k in br and br[k]["value"] >= 45]
    if cands:
        return max(cands)[1][0].upper() + max(cands)[1][1:]
    r = br.get("category", {}).get("reason")
    return r[0].upper() + r[1:] if r else None


def serialize(a: Announcement, companies: dict[str, Company], holdings: set[str], full: bool = False) -> dict:
    c = companies.get(a.ticker)
    d = {
        "id": a.id,
        "ticker": a.ticker,
        "company": c.name if c else a.ticker,
        "sector": c.sector if c else None,
        "in_portfolio": a.ticker in holdings,
        "published_at": a.published_at.isoformat(),
        "subject": a.subject,
        "summary": a.summary,
        "category": a.category,
        "category_label": CATEGORIES.get(a.category or "unclassified", {}).get("label"),
        "score": a.score,
        "priority": a.priority,
        "attachment_url": a.attachment_url,
        "source": a.source,
        "is_duplicate": a.is_duplicate_of is not None,
        "subtype": (a.enrichment or {}).get("subtype"),
        "has_results": bool((a.enrichment or {}).get("results")),
        "has_bio": bool((a.enrichment or {}).get("management")),
        "breakdown": {k: {"contribution": v["contribution"]} for k, v in (a.score_breakdown or {}).items() if isinstance(v, dict)},
        "why_rank": _why_rank(a.score_breakdown),
    }
    if full:
        d.update(
            {
                "exchange_category": a.exchange_category,
                "score_breakdown": a.score_breakdown,
                "enrichment": a.enrichment,
                "category_method": a.category_method,
                "body": (a.attachment_text or a.body or "")[:1500],
            }
        )
    elif (a.enrichment or {}).get("results"):
        r = a.enrichment["results"]
        d["results_preview"] = [{k: row[k] for k in ("label", "current", "qoq_pct", "yoy_pct")} for row in r["rows"]]
    elif (a.enrichment or {}).get("management"):
        p = a.enrichment["management"]["people"][0]
        d["bio_preview"] = {k: p.get(k) for k in ("name", "role", "change", "profile")}
    return d


def build(
    s: Session,
    hours: int | None = 24,
    start: datetime | None = None,
    end: datetime | None = None,
    tickers: list[str] | None = None,
    sector: str | None = None,
    categories: list[str] | None = None,
    min_priority: str | None = None,
    portfolio_only: bool = True,
) -> dict:
    anchor = anchor_time(s)
    start, end = window_bounds(hours, start, end, anchor)
    holdings = set(s.scalars(select(Holding.ticker)).all())
    companies = {c.ticker: c for c in s.scalars(select(Company)).all()}
    q = select(Announcement).where(Announcement.published_at >= start, Announcement.published_at <= end)
    if portfolio_only:
        q = q.where(Announcement.ticker.in_(holdings))
    if tickers:
        q = q.where(Announcement.ticker.in_(tickers))
    if categories:
        q = q.where(Announcement.category.in_(categories))
    anns = [a for a in s.scalars(q).all() if not sector or (companies.get(a.ticker) and companies[a.ticker].sector == sector)]
    order = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    if min_priority:
        anns = [a for a in anns if order.get(a.priority or "low", 0) >= order[min_priority]]
    anns.sort(key=lambda a: (-(a.score or 0), a.published_at), reverse=False)

    material = [a for a in anns if a.priority in ("critical", "high", "medium") and not a.is_duplicate_of]
    routine = [a for a in anns if a not in material]

    moves = s.execute(
        select(AlertEvent, AlertRule)
        .join(AlertRule, AlertRule.id == AlertEvent.rule_id)
        .where(AlertRule.kind.in_(["volume", "price_up", "price_down"]), AlertEvent.triggered_at >= start - timedelta(hours=16), AlertEvent.triggered_at <= end)
        .order_by(AlertEvent.triggered_at.desc())
    ).all()
    move_items = []
    seen = set()
    for ev, rule in moves:
        if ev.ticker in seen and rule.kind != "volume":
            continue
        seen.add(ev.ticker)
        move_items.append({"id": ev.id, "ticker": ev.ticker, "kind": rule.kind, "value": ev.value, "message": ev.message, "at": ev.triggered_at.isoformat()})

    by_co: dict[str, float] = defaultdict(float)
    for a in material:
        by_co[a.ticker] = max(by_co[a.ticker], a.score or 0)
    top_cos = sorted(by_co.items(), key=lambda x: -x[1])[:5]

    counts = Counter(a.priority for a in anns if not a.is_duplicate_of)
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat(), "hours": round((end - start).total_seconds() / 3600)},
        "anchored_to_dataset": anchor < now_ist() - timedelta(hours=1),
        "counts": {
            "total": len(anns),
            "critical": counts.get("critical", 0),
            "high": counts.get("high", 0),
            "medium": counts.get("medium", 0),
            "routine": len(routine),
            "companies": len({a.ticker for a in anns}),
        },
        "executive_summary": (es := executive_summary(material, move_items, companies, len(anns)))["text"],
        "headline": es["headline"],
        "summary_lines": es["lines"],
        "top_companies": [{"ticker": t, "company": companies[t].name if t in companies else t, "score": sc} for t, sc in top_cos],
        "material": [serialize(a, companies, holdings) for a in material],
        "routine": [serialize(a, companies, holdings) for a in routine],
        "moves": move_items,
    }


def executive_summary(material: list[Announcement], moves: list[dict], companies: dict, total: int) -> dict:
    """Assembled from counts and categories — no generation, so it can never claim something the data doesn't show.
    Returns {headline, lines:[{label, tickers}], text}."""
    names = lambda ts: list(dict.fromkeys(ts))  # noqa: E731
    if not material and not moves:
        h = f"Quiet window. {total} filing{'s' if total != 1 else ''}, none material."
        return {"headline": h, "lines": [], "text": h}
    top = [a for a in material if a.priority in ("critical", "high")]
    rest = [a for a in material if a.priority == "medium"]
    lines = []
    if top:
        by_cat: dict[str, list[str]] = defaultdict(list)
        for a in sorted(top, key=lambda a: -(a.score or 0)):
            by_cat[a.category].append(a.ticker)
        for c, ts in by_cat.items():
            lines.append({"label": CATEGORIES[c]["label"], "tickers": names(ts)})
    vol = [m for m in moves if m["kind"] == "volume"]
    px = [m for m in moves if m["kind"] != "volume"]
    if vol:
        lines.append({"label": "Unusual volume", "tickers": names(m["ticker"] for m in vol)})
    if px:
        lines.append({"label": "Outsized price move", "tickers": names(m["ticker"] for m in px)})
    n = len({a.ticker for a in top})
    if n:
        headline = f"{n} holding{'s' if n != 1 else ''} need{'s' if n == 1 else ''} your attention"
    elif rest:
        headline = f"Nothing urgent. {len(rest)} update{'s' if len(rest) != 1 else ''} worth a glance"
    else:
        headline = "No material filings; some unusual trading"
    text = headline + ". " + "; ".join(f"{l['label'].lower()} ({', '.join(l['tickers'])})" for l in lines) + "."
    return {"headline": headline, "lines": lines, "text": text}
