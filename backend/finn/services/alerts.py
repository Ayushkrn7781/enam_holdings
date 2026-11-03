"""Threshold alerts over end-of-day data and material filings. The user decides what 'unusual' means."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AlertEvent, AlertRule, Announcement, Holding, Price
from . import market
from .taxonomy import LABELS

MONITORING_NOTE = ("End-of-day monitoring: prices and volumes are checked after the close against your thresholds. "
                   "Not real-time.")

DEFAULT_RULES = [
    dict(kind="volume", threshold=2.0, priority="high"),
    dict(kind="price_up", threshold=4.0, priority="medium"),
    dict(kind="price_down", threshold=4.0, priority="high"),
    dict(kind="category", category="results", priority="high"),
    dict(kind="category", category="management_change", priority="critical"),
    dict(kind="category", category="M&A", priority="high"),
    dict(kind="category", category="fund_raise", priority="medium"),
    dict(kind="category", category="litigation", priority="medium"),
    dict(kind="category", category="credit_rating", priority="medium"),
    dict(kind="category", category="pledging", priority="high"),
]


def seed_defaults(s: Session) -> None:
    if s.scalars(select(AlertRule)).first() is None:
        for r in DEFAULT_RULES:
            s.add(AlertRule(source="default", **r))
        s.flush()


def describe(r: AlertRule) -> str:
    who = r.ticker or "any holding"
    if r.kind == "volume":
        return f"Volume > {r.threshold:g}× 20-day average, {who}"
    if r.kind == "price_up":
        return f"Price up ≥ {r.threshold:g}% in a day, {who}"
    if r.kind == "price_down":
        return f"Price down ≥ {r.threshold:g}% in a day, {who}"
    return f"{LABELS.get(r.category or '', r.category)} filing, {who}"


def anchor(s: Session) -> datetime:
    from ..config import now_ist
    from ..db import get_meta
    if get_meta(s, "data_mode", "demo") == "demo":
        latest = s.scalars(select(Announcement.published_at).order_by(Announcement.published_at.desc())).first()
        if latest:
            return latest + timedelta(minutes=1)
    return now_ist()


def _add(s: Session, ev: AlertEvent) -> bool:
    exists = s.scalars(select(AlertEvent.id).where(AlertEvent.rule_id == ev.rule_id, AlertEvent.ticker == ev.ticker,
                                                   AlertEvent.ref == ev.ref)).first()
    if exists:
        return False
    try:
        with s.begin_nested():
            s.add(ev)
        return True
    except IntegrityError:
        return False


def evaluate(s: Session) -> int:
    rules = s.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))).all()
    holdings = [h.ticker for h in s.scalars(select(Holding)).all()]
    at = anchor(s)
    n = 0
    price_rules = [r for r in rules if r.kind in ("price_up", "price_down", "volume") and r.threshold is not None]
    if price_rules:
        for t in holdings:
            rows = s.scalars(select(Price).where(Price.ticker == t).order_by(Price.date)).all()
            if len(rows) < 2:
                continue
            for i in range(max(1, len(rows) - 10), len(rows)):
                snap = market.snapshot(rows[: i + 1])
                if not snap:
                    continue
                d = rows[i].date
                for r in price_rules:
                    if r.ticker not in (None, t):
                        continue
                    ret, vr = snap["return_pct"], snap["volume_ratio"]
                    hit, msg, val = False, "", None
                    if r.kind == "price_up" and ret is not None and ret >= r.threshold:
                        hit, msg, val = True, f"Closed {ret:+.1f}% on {d:%d %b}", ret
                    elif r.kind == "price_down" and ret is not None and ret <= -r.threshold:
                        hit, msg, val = True, f"Closed {ret:+.1f}% on {d:%d %b}", ret
                    elif r.kind == "volume" and vr is not None and vr >= r.threshold:
                        hit, msg, val = True, f"Volume {vr:.1f}× its 20-day average on {d:%d %b}", vr
                    if hit:
                        n += _add(s, AlertEvent(rule_id=r.id, ticker=t, ref=f"px:{d.isoformat()}",
                                                triggered_at=datetime.combine(d, datetime.min.time()).replace(hour=16),
                                                message=msg, value=val, source=rows[i].source))
    cat_rules = [r for r in rules if r.kind == "category"]
    if cat_rules:
        anns = s.scalars(select(Announcement).where(Announcement.published_at >= at - timedelta(days=14),
                                                    Announcement.published_at <= at,
                                                    Announcement.ticker.in_(holdings))).all()
        for a in anns:
            if a.subtype == "board_notice" or a.is_duplicate_of is not None:
                continue
            for r in cat_rules:
                if r.category == a.category and r.ticker in (None, a.ticker):
                    n += _add(s, AlertEvent(rule_id=r.id, ticker=a.ticker, ref=f"ann:{a.id}", triggered_at=a.published_at,
                                            message=f"{LABELS.get(a.category, a.category)}: {a.summary or a.subject}",
                                            announcement_id=a.id, source=a.source))
    s.flush()
    return n


def reset_rule_events(s: Session, rule_id: int) -> None:
    s.execute(delete(AlertEvent).where(AlertEvent.rule_id == rule_id))
    s.flush()


def serialize_rule(r: AlertRule) -> dict:
    return {"id": r.id, "ticker": r.ticker, "kind": r.kind, "threshold": r.threshold, "category": r.category,
            "priority": r.priority, "enabled": r.enabled, "description": describe(r), "source": r.source}


def serialize_event(e: AlertEvent, rule: AlertRule | None) -> dict:
    return {"id": e.id, "rule_id": e.rule_id, "ticker": e.ticker, "ref": e.ref,
            "triggered_at": e.triggered_at.isoformat(), "message": e.message, "value": e.value,
            "announcement_id": e.announcement_id, "seen": e.seen, "priority": rule.priority if rule else None,
            "kind": rule.kind if rule else None, "rule": describe(rule) if rule else None, "source": e.source}
