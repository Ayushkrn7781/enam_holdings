"""Deterministic maths. The LLM never does arithmetic; everything numeric goes through here."""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Optional, Sequence

Num = Optional[float]


def _d(x) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        d = Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None
    if d.is_nan() or d.is_infinite():
        return None
    return d


def rnd(x, places: int = 1) -> Num:
    d = _d(x)
    if d is None:
        return None
    q = Decimal(1).scaleb(-places)
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def growth_pct(cur, base) -> Num:
    """(cur - base) / |base| * 100. A narrowed loss (-100 -> -50) reads +50%. None on missing/zero base."""
    c, b = _d(cur), _d(base)
    if c is None or b is None or b == 0:
        return None
    return rnd((c - b) / abs(b) * 100)


def margin_pct(part, whole) -> Num:
    p, w = _d(part), _d(whole)
    if p is None or w is None or w == 0:
        return None
    return rnd(p / w * 100)


def ratio(a, b, places: int = 2) -> Num:
    x, y = _d(a), _d(b)
    if x is None or y is None or y == 0:
        return None
    return rnd(x / y, places)


def daily_return_pct(close, prev) -> Num:
    c, p = _d(close), _d(prev)
    if c is None or p is None or p == 0:
        return None
    return rnd((c / p - 1) * 100, 2)


def volume_ratio(today, trailing: Sequence[float]) -> Num:
    """today / mean(trailing sessions). `trailing` must exclude today."""
    vals = [v for v in trailing if v is not None]
    if today is None or not vals:
        return None
    m = sum(vals) / len(vals)
    if m == 0:
        return None
    return rnd(Decimal(str(today)) / Decimal(str(m)), 2)


def mean(xs: Iterable[float]) -> Num:
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def stdev(xs: Iterable[float]) -> Num:
    v = [x for x in xs if x is not None]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def zscore(x, history: Sequence[float]) -> Num:
    s = stdev(history)
    m = mean(history)
    if x is None or s is None or m is None or s == 0:
        return None
    return rnd((x - m) / s, 2)


def cagr_pct(end, start, years) -> Num:
    e, s = _d(end), _d(start)
    if e is None or s is None or not years or s <= 0 or e <= 0:
        return None
    return rnd(((float(e) / float(s)) ** (1 / years) - 1) * 100)


def bps(cur, prev) -> Optional[int]:
    if cur is None or prev is None:
        return None
    return int(Decimal(str((cur - prev) * 100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def indian_group(n: int) -> str:
    s = str(abs(n))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + out


def fmt_cr(x, places: int = 0) -> str:
    """₹12,34,567 Cr with Indian grouping."""
    if x is None:
        return "N/A"
    d = _d(x)
    q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    whole = int(abs(q))
    frac = ""
    if places:
        frac = "." + f"{abs(q):.{places}f}".split(".")[1]
    sign = "-" if q < 0 else ""
    return f"{sign}₹{indian_group(whole)}{frac} Cr"


def fmt_pct(x, signed: bool = True) -> str:
    if x is None:
        return "N/A"
    return f"{x:+.1f}%" if signed else f"{x:.1f}%"


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))
