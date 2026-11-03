"""Indian fiscal-period helpers. FY27 runs 1 Apr 2026 – 31 Mar 2027; Q1 = Apr–Jun."""
from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Optional


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def fy_of(d: date) -> int:
    """Two-digit FY number for a date (Oct 2026 -> 27)."""
    return (d.year + 1 if d.month >= 4 else d.year) % 100


def quarter_of(d: date) -> int:
    return ((d.month - 4) % 12) // 3 + 1


def quarter_label(period_end: date) -> str:
    return f"Q{quarter_of(period_end)} FY{fy_of(period_end):02d}"


def fy_label(period_end: date) -> str:
    return f"FY{fy_of(period_end):02d}"


def month_label(d: date) -> str:
    return d.strftime("%b %Y")


def _full_year(fy2: int) -> int:
    return 2000 + fy2


def fy_end(fy2: int) -> date:
    return date(_full_year(fy2), 3, 31)


def quarter_end(q: int, fy2: int) -> date:
    y = _full_year(fy2)
    return {1: date(y - 1, 6, 30), 2: date(y - 1, 9, 30), 3: date(y - 1, 12, 31), 4: date(y, 3, 31)}[q]


def fy_quarter_ends(fy2: int) -> list[date]:
    return [quarter_end(q, fy2) for q in (1, 2, 3, 4)]


_Q = re.compile(r"Q([1-4])\s*FY\s*'?(\d{2,4})", re.I)
_FY = re.compile(r"FY\s*'?(\d{2,4})", re.I)


def parse_quarter(label: str) -> Optional[tuple[int, int]]:
    m = _Q.search(label or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)) % 100


def parse_fy(label: str) -> Optional[int]:
    if parse_quarter(label):
        return None
    m = _FY.search(label or "")
    return int(m.group(1)) % 100 if m else None


def next_quarter(label: str) -> Optional[str]:
    pq = parse_quarter(label)
    if not pq:
        return None
    q, fy = pq
    return f"Q1 FY{fy + 1:02d}" if q == 4 else f"Q{q + 1} FY{fy:02d}"


def fy_of_label(label: str) -> Optional[int]:
    pq = parse_quarter(label)
    if pq:
        return pq[1]
    return parse_fy(label)


def prev_quarter_end_before(year: int, month: int) -> date:
    """Most recent quarter end strictly before the call month (transcript -> quarter discussed)."""
    qm = ((month - 1) // 3) * 3
    if qm == 0:
        return date(year - 1, 12, 31)
    return month_end(year, qm)
