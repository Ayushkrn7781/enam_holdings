"""Explainable 0-100 materiality score.

    Materiality = 0.25*Category + 0.25*Financial impact + 0.20*Historical deviation
                + 0.15*Portfolio relevance + 0.15*Novelty

Every component is normalised to 0-100 by a documented rule and returns a human-readable reason,
so the UI can show *why* an item ranks where it does. No LLM produces any of these numbers.
Weights and priority bands are configurable (Meta 'materiality_weights'); bands are prototype defaults.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WEIGHTS = {"category": 0.25, "financial": 0.25, "deviation": 0.20, "relevance": 0.15, "novelty": 0.15}
BANDS = [(80, "critical"), (60, "high"), (35, "medium"), (0, "low")]


@dataclass
class Component:
    value: float
    reason: str
    evidence: dict | None = None


def priority_for(score: float) -> str:
    return next(label for cut, label in BANDS if score >= cut)


def clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def financial_impact(category: str, results_card: dict | None, amount_cr: float | None, annual_revenue_cr: float | None) -> Component:
    if category == "results" and results_card:
        rows = {r["metric"]: r for r in results_card["rows"]}
        pat, rev = rows["pat"].get("yoy_pct"), rows["revenue"].get("yoy_pct")
        if pat is None and rev is None:
            return Component(40, "results without comparable base period")
        mag = max(abs(pat or 0), abs(rev or 0) * 1.5)
        v = clamp(25 + mag * 2.5)
        return Component(v, f"YoY PAT {pat if pat is not None else 'N/A'}%, revenue {rev if rev is not None else 'N/A'}%",
                         {"pat_yoy": pat, "revenue_yoy": rev})
    if amount_cr is not None and annual_revenue_cr:
        share = amount_cr / annual_revenue_cr * 100
        # sqrt scaling: 0.5% of revenue -> ~32, 5% -> ~59, 15% -> ~88, >=20% -> 100
        v = clamp(20 + 16 * (share ** 0.5) * 1.1)
        return Component(v, f"₹{amount_cr:,.0f} Cr ≈ {share:.1f}% of annual revenue", {"amount_cr": amount_cr, "pct_of_revenue": round(share, 2)})
    if amount_cr is not None:
        return Component(45, f"₹{amount_cr:,.0f} Cr disclosed; revenue base unavailable to size it", {"amount_cr": amount_cr})
    neutral = {"management_change": 50, "M&A": 50, "litigation": 45, "credit_rating": 45, "pledging": 45}.get(category, 15)
    return Component(neutral, "no quantified amount in the filing (category default)")


def deviation(results_card: dict | None, results_yoy_history: list[float], reaction: dict | None) -> Component:
    """Max of (results surprise vs own history) and (EOD price/volume reaction vs own volatility)."""
    parts: list[tuple[float, str]] = []
    if results_card:
        pat = next((r["yoy_pct"] for r in results_card["rows"] if r["metric"] == "pat"), None)
        hist = [h for h in results_yoy_history if h is not None]
        if pat is not None and len(hist) >= 3:
            import statistics

            sd = statistics.pstdev(hist) or 1.0
            z = (pat - statistics.fmean(hist)) / sd
            parts.append((clamp(abs(z) * 30), f"PAT growth {z:+.1f}σ vs its last {len(hist)} quarters"))
    if reaction:
        sig = reaction.get("return_sigma")
        vr = reaction.get("volume_ratio")
        if sig is not None:
            parts.append((clamp(abs(sig) * 28), f"price moved {reaction['return_pct']:+.2f}% ({sig:+.1f}σ) on {reaction['date']}"))
        if vr is not None:
            parts.append((clamp((vr - 1) * 45), f"volume {vr:.1f}× 20-day average on {reaction['date']}"))
    if not parts:
        return Component(20, "no price reaction or history available yet")
    best = max(parts, key=lambda p: p[0])
    return Component(round(best[0], 1), "; ".join(p[1] for p in parts), None)


def relevance(in_portfolio: bool, watched_category: bool) -> Component:
    if in_portfolio and watched_category:
        return Component(100, "portfolio holding + a category you alert on")
    if in_portfolio:
        return Component(75, "portfolio holding")
    return Component(25, "not in portfolio (ad-hoc research)")


def novelty(max_similarity: float, days_since_same_category: int | None) -> Component:
    v = 100 * (1 - max_similarity)
    reason = "first filing of its kind in 90 days" if max_similarity < 0.2 else f"{max_similarity:.0%} similar to an earlier filing"
    if days_since_same_category is not None and days_since_same_category < 14 and max_similarity < 0.2:
        v = min(v, 70)
        reason = f"same category filed {days_since_same_category}d ago"
    return Component(round(clamp(v), 1), reason)


def score(components: dict[str, Component], weights: dict[str, float] | None = None) -> tuple[float, dict]:
    w = weights or DEFAULT_WEIGHTS
    total = sum(w[k] * components[k].value for k in w)
    breakdown = {
        k: {"value": round(components[k].value, 1), "weight": w[k], "contribution": round(w[k] * components[k].value, 1),
            "reason": components[k].reason, "evidence": components[k].evidence}
        for k in w
    }
    return round(total, 1), breakdown
