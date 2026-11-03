"""Deterministic financial arithmetic. The LLM never does maths in FINN — everything numeric goes through here."""
from __future__ import annotations

import statistics
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Sequence


def D(x) -> Decimal | None:
    if x is None:
        return None
    try:
        d = Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def growth_pct(current, base) -> float | None:
    """(current - base) / |base| * 100. N/A (None) when either side is missing or base is zero.

    |base| in the denominator keeps the sign meaningful when a loss narrows (e.g. -100 -> -50 = +50%).
    """
    c, b = D(current), D(base)
    if c is None or b is None or b == 0:
        return None
    g = (c - b) / abs(b) * Decimal(100)
    return float(g.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def ratio(num, den, scale: float = 1.0, places: str = "0.01") -> float | None:
    n, d = D(num), D(den)
    if n is None or d is None or d == 0:
        return None
    return float((n / d * Decimal(str(scale))).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def margin_pct(profit, revenue) -> float | None:
    return ratio(profit, revenue, 100, "0.1")


def daily_return_pct(close, prev_close) -> float | None:
    """(Current close / Previous close - 1) x 100"""
    c, p = D(close), D(prev_close)
    if c is None or p is None or p == 0:
        return None
    return float(((c / p - 1) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def volume_ratio(volume, history: Sequence[float]) -> float | None:
    """Current volume / mean of the trailing window (window excludes today)."""
    hist = [h for h in history if h]
    if not hist or not volume:
        return None
    return ratio(volume, statistics.fmean(hist), 1, "0.01")


def zscore(value: float | None, history: Iterable[float | None]) -> float | None:
    vals = [v for v in history if v is not None]
    if value is None or len(vals) < 4:
        return None
    sd = statistics.pstdev(vals)
    if sd == 0:
        return None
    return round((value - statistics.fmean(vals)) / sd, 2)


def cagr_pct(end, start, years: float) -> float | None:
    e, s = D(end), D(start)
    if e is None or s is None or s <= 0 or e <= 0 or years <= 0:
        return None
    return round(((float(e) / float(s)) ** (1 / years) - 1) * 100, 1)


def fmt_cr(x: float | None) -> str:
    """Indian-style crore formatting: 12,34,567 Cr."""
    if x is None:
        return "N/A"
    neg = x < 0
    n = f"{abs(x):.0f}"
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        n = ",".join(parts + [tail])
    return f"{'-' if neg else ''}₹{n} Cr"


def fmt_pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "N/A"
    return f"{x:+.1f}%" if signed else f"{x:.1f}%"
