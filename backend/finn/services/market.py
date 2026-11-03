"""End-of-day market maths: returns, volume ratios, reaction to an event date. EOD only — never real-time."""
from __future__ import annotations

import statistics
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Price
from .numbers import daily_return_pct, volume_ratio


def series(s: Session, ticker: str, limit: int = 260) -> list[Price]:
    rows = s.scalars(select(Price).where(Price.ticker == ticker).order_by(Price.date.desc()).limit(limit)).all()
    return list(reversed(rows))


def snapshot(rows: list[Price], window: int = 20) -> dict | None:
    """Latest EOD stats with the trailing window *excluding* the latest session."""
    if len(rows) < 2:
        return None
    last, prev = rows[-1], rows[-2]
    hist = rows[-(window + 1) : -1]
    rets = [daily_return_pct(b.close, a.close) for a, b in zip(rows[-(window + 2) : -2], rows[-(window + 1) : -1])]
    rets = [r for r in rets if r is not None]
    sd = statistics.pstdev(rets) if len(rets) > 3 else None
    ret = daily_return_pct(last.close, prev.close)
    first_y = next((r for r in rows if (last.date - r.date).days <= 365), rows[0])
    return {
        "date": last.date.isoformat(),
        "close": last.close,
        "prev_close": prev.close,
        "return_pct": ret,
        "volume": last.volume,
        "avg_volume": round(statistics.fmean([h.volume for h in hist if h.volume]), 0) if hist else None,
        "volume_ratio": volume_ratio(last.volume, [h.volume for h in hist]),
        "return_sigma": round(ret / sd, 2) if ret is not None and sd else None,
        "vol_20d_pct": round(sd, 2) if sd else None,
        "return_1y_pct": daily_return_pct(last.close, first_y.close),
        "high_52w": max(r.high or r.close for r in rows[-252:]),
        "low_52w": min(r.low or r.close for r in rows[-252:]),
        "source": last.source,
    }


def reaction(rows: list[Price], on: date, window: int = 20) -> dict | None:
    """Price/volume reaction on the first session on/after `on` (filings after 15:30 hit the next session)."""
    idx = next((i for i, r in enumerate(rows) if r.date >= on), None)
    if idx is None or idx < 2:
        return None
    sub = rows[: idx + 1]
    snap = snapshot(sub, window)
    return snap
