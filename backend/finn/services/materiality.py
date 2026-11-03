"""Explainable materiality: a weighted sum of five rule-based components, each 0-100 with a reason."""
from __future__ import annotations

import math
import re
from typing import Optional

from . import numbers as N
from .taxonomy import IMPORTANCE, SCHEDULED_SUBTYPES

DEFAULT_WEIGHTS = {"category": 0.25, "financial": 0.25, "deviation": 0.20, "relevance": 0.15, "novelty": 0.15}
COMPONENT_LABELS = {"category": "Category", "financial": "Financial impact", "deviation": "Unusualness",
                    "relevance": "Relevance", "novelty": "Novelty"}
BANDS = [("critical", 80.0), ("high", 60.0), ("medium", 35.0), ("low", float("-inf"))]


def normalise_weights(w: dict | None) -> dict:
    w = {k: max(0.0, float((w or {}).get(k, DEFAULT_WEIGHTS[k]))) for k in DEFAULT_WEIGHTS}
    total = sum(w.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in w.items()}


def priority(score: float) -> str:
    for name, edge in BANDS:
        if score >= edge:
            return name
    return "low"


def score(components: dict, weights: dict | None = None) -> tuple[float, dict]:
    """components: {name: {"value": 0-100, "reason": str}} -> (score, breakdown)."""
    w = normalise_weights(weights)
    total = 0.0
    breakdown = {}
    for k in DEFAULT_WEIGHTS:
        c = components.get(k, {"value": 0, "reason": ""})
        contrib = w[k] * float(c["value"])
        total += contrib
        breakdown[k] = {"label": COMPONENT_LABELS[k], "value": round(float(c["value"]), 1), "weight": round(w[k], 4),
                        "contribution": round(contrib, 2), "reason": c["reason"]}
    return round(total, 1), breakdown


# ---------------------------------------------------------------- components
def financial(category: str, subtype: str, amount_cr: Optional[float], annual_revenue: Optional[float],
              rev_yoy: Optional[float] = None, pat_yoy: Optional[float] = None) -> dict:
    if category == "unclassified":
        return {"value": 0, "reason": "Routine filing, no financial impact"}
    if category == "results" and subtype != "board_notice":
        if rev_yoy is None and pat_yoy is None:
            return {"value": 45, "reason": "Results filed; numbers could not be read"}
        m = max(abs(pat_yoy or 0), 1.5 * abs(rev_yoy or 0))
        v = N.clamp(25 + m * 2.5)
        return {"value": round(v, 1), "reason": f"Revenue YoY {N.fmt_pct(rev_yoy)}, PAT YoY {N.fmt_pct(pat_yoy)}"}
    if amount_cr:
        if annual_revenue:
            pct = amount_cr / annual_revenue * 100
            v = N.clamp(20 + 16 * math.sqrt(pct) * 1.1)
            return {"value": round(v, 1),
                    "reason": f"{N.fmt_cr(amount_cr)} is {pct:.1f}% of annual revenue ({N.fmt_cr(annual_revenue)})"}
        return {"value": 45, "reason": f"{N.fmt_cr(amount_cr)} disclosed; no revenue base to size it against"}
    default = {"management_change": 50, "M&A": 50, "litigation": 45, "credit_rating": 45, "pledging": 45}.get(category, 15)
    return {"value": default, "reason": "No amount disclosed; category default"}


def _d(iso: str) -> str:
    try:
        from datetime import date
        return date.fromisoformat(iso).strftime("%-d %b")
    except Exception:
        return iso


def deviation(category_importance: float, category: str, pat_z: Optional[float], react: Optional[dict]) -> dict:
    parts: list[tuple[float, str]] = []
    if pat_z is not None:
        parts.append((N.clamp(abs(pat_z) * 30), f"PAT YoY is {pat_z:+.1f}σ versus the last 8 quarters"))
    if react:
        if react.get("return_sigma") is not None:
            parts.append((N.clamp(abs(react["return_sigma"]) * 28),
                          f"Stock moved {N.fmt_pct(react.get('return_pct'))} on {_d(react['date'])} "
                          f"({react['return_sigma']:+.1f}σ of its 20-day range)"))
        if react.get("volume_ratio") is not None:
            parts.append((N.clamp((react["volume_ratio"] - 1) * 45),
                          f"Volume {react['volume_ratio']:.1f}× its 20-day average on {_d(react['date'])}"))
    if parts:
        v, reason = max(parts, key=lambda p: p[0])
    else:
        v, reason = 20, "No price reaction or results history yet"
    if category_importance < 40 and v > 25:
        v, reason = 25, reason + " (capped: low-importance filing, move likely unrelated)"
    if category == "unclassified" and v > 20:
        v = 20
    return {"value": round(v, 1), "reason": reason}


def relevance(in_portfolio: bool, alerted_category: bool, subtype: str) -> dict:
    if in_portfolio and alerted_category and subtype != "board_notice":
        return {"value": 100, "reason": "A holding, in a category you alert on"}
    if in_portfolio:
        return {"value": 75, "reason": "A holding"}
    return {"value": 25, "reason": "Not in your portfolio"}


_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def novelty(max_sim: float, same_cat_within_14d: bool, subtype: str, category: str) -> dict:
    v = 100 * (1 - max_sim)
    reason = "Nothing similar from this company in 90 days" if max_sim < 0.05 else \
        f"{max_sim:.0%} similar to an earlier filing in 90 days"
    if same_cat_within_14d and v > 70:
        v, reason = 70, reason + "; same category filed within 14 days"
    if subtype in SCHEDULED_SUBTYPES and v > 30:
        v, reason = 30, "Scheduled / procedural filing"
    if category == "unclassified" and v > 10:
        v, reason = 10, "Routine paperwork"
    return {"value": round(v, 1), "reason": reason}


def category_component(cat_score: float, reason: str) -> dict:
    return {"value": cat_score, "reason": reason}


__all__ = ["DEFAULT_WEIGHTS", "IMPORTANCE", "normalise_weights", "priority", "score", "financial", "deviation",
           "relevance", "novelty", "tokens", "jaccard"]
