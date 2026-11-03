"""End-of-day market snapshot and reaction-to-filing lookup."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional, Sequence

from . import numbers as N


def _get(r, k):
    return r[k] if isinstance(r, dict) else getattr(r, k)


def snapshot(rows: Sequence[Any]) -> Optional[dict]:
    """rows: price rows sorted by date ascending (dicts or Price objects); snapshot as of the last row."""
    rows = [r for r in rows if _get(r, "close") is not None]
    if not rows:
        return None
    last = rows[-1]
    closes = [_get(r, "close") for r in rows]
    vols = [_get(r, "volume") for r in rows]
    ret = N.daily_return_pct(closes[-1], closes[-2]) if len(closes) >= 2 else None
    trailing = vols[-21:-1]
    vr = N.volume_ratio(vols[-1], trailing) if trailing else None
    # sigma of today's move against the 20 sessions before it (today excluded, like the volume average)
    rets = [N.daily_return_pct(closes[i], closes[i - 1]) for i in range(max(1, len(closes) - 21), len(closes) - 1)]
    sd = N.stdev([r for r in rets if r is not None])
    sigma = N.rnd(ret / sd, 2) if (ret is not None and sd) else None
    year = rows[-252:] if len(rows) > 252 else rows
    hi = max(_get(r, "high") or _get(r, "close") for r in year)
    lo = min(_get(r, "low") or _get(r, "close") for r in year)
    one_y = N.growth_pct(closes[-1], _get(year[0], "close")) if len(year) > 200 else None
    avg_vol = N.mean([v for v in trailing if v is not None]) if trailing else None
    return {
        "date": _get(last, "date").isoformat() if hasattr(_get(last, "date"), "isoformat") else _get(last, "date"),
        "close": N.rnd(closes[-1], 2), "return_pct": ret, "volume": vols[-1],
        "avg_volume": N.rnd(avg_vol, 0) if avg_vol else None, "volume_ratio": vr, "return_sigma": sigma,
        "return_1y_pct": one_y, "high_52w": N.rnd(hi, 2), "low_52w": N.rnd(lo, 2),
        "source": _get(last, "source"),
    }


def reaction(rows: Sequence[Any], on_or_after: date) -> Optional[dict]:
    """Snapshot as of the first session on or after `on_or_after`."""
    for i, r in enumerate(rows):
        if _get(r, "date") >= on_or_after:
            return snapshot(rows[: i + 1])
    return None
