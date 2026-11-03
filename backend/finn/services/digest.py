"""Windowed digest. The headline and lines are assembled from computed data, never generated."""
from __future__ import annotations

from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_meta
from ..models import AlertEvent, AlertRule, Announcement, Company, Holding
from .alerts import anchor
from .taxonomy import LABELS

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
MATERIAL = {"critical", "high", "medium"}


def why_rank(a: Announcement) -> str:
    if a.is_duplicate_of is not None:
        return "Duplicate of an earlier filing; suppressed"
    b = a.score_breakdown or {}
    fin, dev = b.get("financial", {}), b.get("deviation", {})
    strongest = max((fin, dev), key=lambda c: c.get("value", 0))
    if strongest.get("value", 0) >= 45:
        return strongest.get("reason", "")
    return (b.get("category") or {}).get("reason", "")


def serialize(a: Announcement, company: Optional[Company] = None, triage: Optional[str] = None,
              detail: bool = False) -> dict[str, Any]:
    enr = a.enrichment or {}
    b = a.score_breakdown or {}
    out: dict[str, Any] = {
        "id": a.id, "ticker": a.ticker, "company": company.name if company else a.ticker,
        "sector": company.sector if company else None, "published_at": a.published_at.isoformat(),
        "subject": a.subject, "exchange_category": a.exchange_category, "category": a.category,
        "category_label": LABELS.get(a.category or "", a.category), "subtype": a.subtype,
        "category_method": a.category_method, "score": a.score, "priority": a.priority, "summary": a.summary,
        "is_duplicate": a.is_duplicate_of is not None, "is_duplicate_of": a.is_duplicate_of, "source": a.source,
        "attachment_url": a.attachment_url,
        "breakdown": [{"key": k, "label": v.get("label"), "contribution": v.get("contribution"),
                       "value": v.get("value"), "weight": v.get("weight"), "reason": v.get("reason")}
                      for k, v in b.items()],
        "why_rank": why_rank(a), "triage": triage,
    }
    card = enr.get("results")
    if card:
        out["results_preview"] = {
            "period_label": card.get("period_label"),
            "verification": (card.get("verification") or {}).get("status"),
            "rows": [{"key": r["key"], "label": r["label"], "yoy": r["yoy"], "qoq": r["qoq"], "current": r["current"]}
                     for r in card["rows"]]}
    people = enr.get("people") or []
    if people:
        p = people[0]
        out["bio_preview"] = {"name": p.get("name"), "role": p.get("role"), "change": p.get("change"),
                              "profile": p.get("profile")}
    if detail:
        out["body"] = a.body
        out["attachment_text"] = a.attachment_text
        out["enrichment"] = enr
        out["score_breakdown"] = b
    return out


def build(s: Session, hours: int = 24, start: Optional[datetime] = None, end: Optional[datetime] = None,
          tickers: Optional[list[str]] = None, sector: Optional[str] = None, categories: Optional[list[str]] = None,
          min_priority: Optional[str] = None) -> dict[str, Any]:
    at = anchor(s)
    end = end or at
    start = start or (end - timedelta(hours=hours))
    holdings = {h.ticker for h in s.scalars(select(Holding)).all()}
    comps = {c.ticker: c for c in s.scalars(select(Company)).all()}
    triage = get_meta(s, "triage", {}) or {}
    q = select(Announcement).where(Announcement.published_at >= start, Announcement.published_at <= end,
                                   Announcement.ticker.in_(holdings))
    items = s.scalars(q).all()
    if tickers:
        items = [a for a in items if a.ticker in set(tickers)]
    if sector:
        items = [a for a in items if comps.get(a.ticker) and comps[a.ticker].sector == sector]
    if categories:
        items = [a for a in items if a.category in set(categories)]
    if min_priority in PRIORITY_ORDER:
        items = [a for a in items if PRIORITY_ORDER.get(a.priority or "low", 3) <= PRIORITY_ORDER[min_priority]]
    items.sort(key=lambda a: (-(a.score or 0), a.published_at))
    material = [a for a in items if a.priority in MATERIAL and a.is_duplicate_of is None]
    routine = [a for a in items if a not in material]

    # EOD moves in the window
    ev_rows = s.execute(select(AlertEvent, AlertRule).join(AlertRule, AlertRule.id == AlertEvent.rule_id)
                        .where(AlertRule.kind.in_(["price_up", "price_down", "volume"]))).all()
    moves = []
    for e, r in ev_rows:
        if e.ticker in holdings and start <= e.triggered_at <= end:
            moves.append({"ticker": e.ticker, "kind": r.kind, "message": e.message, "value": e.value,
                          "date": e.triggered_at.date().isoformat(), "priority": r.priority})
    moves.sort(key=lambda m: (m["kind"] != "volume", -abs(m["value"] or 0)))

    counts = Counter(a.priority for a in material)
    counts_out = {"filings": len(items), "companies": len({a.ticker for a in items}),
                  "critical": counts.get("critical", 0), "high": counts.get("high", 0),
                  "medium": counts.get("medium", 0), "routine": len(routine)}

    lines: "OrderedDict[str, list[str]]" = OrderedDict()
    for a in material:
        if a.priority in ("critical", "high"):
            lbl = LABELS.get(a.category or "", a.category)
            lines.setdefault(lbl, [])
            if a.ticker not in lines[lbl]:
                lines[lbl].append(a.ticker)
    vol = sorted({m["ticker"] for m in moves if m["kind"] == "volume"})
    px = sorted({m["ticker"] for m in moves if m["kind"] != "volume"} - set(vol))
    line_list = [{"label": k, "tickers": v} for k, v in lines.items()]
    if vol:
        line_list.append({"label": "Unusual volume", "tickers": vol})
    if px:
        line_list.append({"label": "Outsized price move", "tickers": px})
    attention = {a.ticker for a in material if a.priority in ("critical", "high")}
    if attention:
        headline = f"{len(attention)} holding{'s' if len(attention) != 1 else ''} need{'s' if len(attention) == 1 else ''} your attention"
    else:
        headline = f"Nothing urgent. {len(material)} update{'s' if len(material) != 1 else ''} worth a glance"

    top = Counter(a.ticker for a in material).most_common(5)
    routine_by_cat = Counter(LABELS.get(a.category or "", a.category) for a in routine)
    return {
        "anchor": at.isoformat(), "window": {"start": start.isoformat(), "end": end.isoformat(), "hours": hours},
        "headline": headline, "lines": line_list, "counts": counts_out,
        "items": [serialize(a, comps.get(a.ticker), triage.get(str(a.id))) for a in material],
        "routine": [serialize(a, comps.get(a.ticker), triage.get(str(a.id))) for a in routine],
        "routine_summary": [{"label": k, "count": v} for k, v in routine_by_cat.most_common()],
        "moves": moves, "top_companies": [{"ticker": t, "count": c} for t, c in top],
        "data_mode": get_meta(s, "data_mode", "demo"),
    }
