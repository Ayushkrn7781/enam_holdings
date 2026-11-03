"""Indian fiscal-period helpers. FY27 = 1 Apr 2026 – 31 Mar 2027; Q1 = Apr–Jun."""
from __future__ import annotations

import calendar
import re
from datetime import date


def quarter_label(d: date) -> str:
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month)
    fy = d.year + 1 if d.month > 3 else d.year
    return f"Q{q} FY{fy % 100:02d}" if q else d.strftime("%b %Y")


def fy_label(d: date) -> str:
    fy = d.year + 1 if d.month > 3 else d.year
    return f"FY{fy % 100:02d}"


def fy_end(label: str) -> date | None:
    m = re.fullmatch(r"FY\s?'?(\d{2}|\d{4})", label.strip(), re.I)
    if not m:
        return None
    y = int(m.group(1))
    y = y + 2000 if y < 100 else y
    return date(y, 3, 31)


def quarter_end(label: str) -> date | None:
    m = re.fullmatch(r"Q([1-4])\s?FY\s?'?(\d{2}|\d{4})", label.strip(), re.I)
    if not m:
        return None
    q, y = int(m.group(1)), int(m.group(2))
    y = y + 2000 if y < 100 else y
    month = {1: 6, 2: 9, 3: 12, 4: 3}[q]
    year = y - 1 if q in (1, 2, 3) else y
    return date(year, month, calendar.monthrange(year, month)[1])


def next_quarter(label: str) -> str | None:
    d = quarter_end(label)
    if not d:
        return None
    m = d.month + 3
    y = d.year + (1 if m > 12 else 0)
    m = m - 12 if m > 12 else m
    return quarter_label(date(y, m, calendar.monthrange(y, m)[1]))


def fy_of_quarter(label: str) -> str | None:
    d = quarter_end(label)
    return fy_label(d) if d else None
