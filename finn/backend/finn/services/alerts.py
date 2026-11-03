"""Threshold alerts over EOD data and classified filings. Monitoring frequency: once per EOD refresh."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AlertEvent, AlertRule, Announcement, Holding
from . import market
from .taxonomy import CATEGORIES

DEFAULT_RULES = [
    {"kind": "volume", "threshold": 2.0, "priority": "high"},
    {"kind": "price_up", "threshold": 4.0, "priority": "medium"},
    {"kind": "price_down", "threshold": 4.0, "priority": "high"},
    {"kind": "category", "category": "results", "priority": "high"},
    {"kind": "category", "category": "management_change", "priority": "critical"},
    {"kind": "category", "category": "M&A", "priority": "high"},
    {"kind": "category", "category": "fund_raise", "priority": "medium"},
    {"kind": "category", "category": "litigation", "priority": "medium"},
    {"kind": "category", "category": "credit_rating", "priority": "medium"},
    {"kind": "category", "category": "pledging", "priority": "high"},
]


def seed_defaults(s: Session) -> None:
    if s.scalar(select(AlertRule.id).limit(1)):
        return
    for r in DEFAULT_RULES:
        s.add(AlertRule(**r))
    s.commit()


def describe(rule: AlertRule) -> str:
    who = rule.ticker or "any holding"
    if rule.kind == "volume":
        return f"Volume > {rule.threshold:g}× 20-day average, {who}"
    if rule.kind == "price_up":
        return f"Price up > {rule.threshold:g}% in a session, {who}"
    if rule.kind == "price_down":
        return f"Price down > {rule.threshold:g}% in a session, {who}"
    return f"New {CATEGORIES.get(rule.category or '', {}).get('label', rule.category)} filing, {who}"


def _add(s: Session, ev: AlertEvent) -> bool:
    try:
        with s.begin_nested():
            s.add(ev)
        return True
    except IntegrityError:
        return False


def evaluate(s: Session, lookback_sessions: int = 10) -> int:
    rules = s.scalars(select(AlertRule).where(AlertRule.enabled)).all()
    holdings = s.scalars(select(Holding.ticker)).all()
    new = 0
    series = {t: market.series(s, t, 60) for t in holdings}
    for rule in rules:
        tickers = [rule.ticker] if rule.ticker else holdings
        if rule.kind in ("volume", "price_up", "price_down"):
            for t in tickers:
                rows = series.get(t) or market.series(s, t, 60)
                for end in range(max(22, len(rows) - lookback_sessions), len(rows) + 1):
                    snap = market.snapshot(rows[:end])
                    if not snap:
                        continue
                    hit, val, msg = False, None, ""
                    if rule.kind == "volume" and snap["volume_ratio"] and snap["volume_ratio"] >= rule.threshold:
                        hit, val = True, snap["volume_ratio"]
                        msg = f"{t} traded {val:.1f}× its 20-day average volume (close ₹{snap['close']:,.2f}, {snap['return_pct']:+.2f}%)."
                    elif rule.kind == "price_up" and snap["return_pct"] is not None and snap["return_pct"] >= rule.threshold:
                        hit, val = True, snap["return_pct"]
                        msg = f"{t} rose {val:+.2f}% to ₹{snap['close']:,.2f}" + (f" ({snap['return_sigma']:+.1f}σ)." if snap["return_sigma"] else ".")
                    elif rule.kind == "price_down" and snap["return_pct"] is not None and snap["return_pct"] <= -rule.threshold:
                        hit, val = True, snap["return_pct"]
                        msg = f"{t} fell {val:.2f}% to ₹{snap['close']:,.2f}" + (f" ({snap['return_sigma']:+.1f}σ)." if snap["return_sigma"] else ".")
                    if hit:
                        when = datetime.fromisoformat(snap["date"]).replace(hour=16)
                        new += _add(s, AlertEvent(rule_id=rule.id, ticker=t, ref=f"px:{snap['date']}", triggered_at=when, message=msg, value=val))
        else:
            from .digest import anchor_time

            since = anchor_time(s) - timedelta(days=14)
            anns = s.scalars(
                select(Announcement).where(
                    Announcement.category == rule.category,
                    Announcement.ticker.in_(tickers),
                    Announcement.published_at >= since,
                    Announcement.is_duplicate_of.is_(None),
                )
            ).all()
            for a in anns:
                if a.enrichment and a.enrichment.get("subtype") == "board_notice":
                    continue
                msg = f"{a.ticker}: {a.summary or a.subject}"
                new += _add(s, AlertEvent(rule_id=rule.id, ticker=a.ticker, ref=f"ann:{a.id}", triggered_at=a.published_at,
                                          message=msg, announcement_id=a.id))
    s.commit()
    return new
