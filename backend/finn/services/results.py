"""Quarterly results intelligence: Revenue, EBITDA, PBT, PAT — QoQ and YoY.

Two independent sources are reconciled:
  1. the structured quarterly table (screener.in, or demo data), and
  2. the actual results filing PDF, parsed with a deterministic SEBI-format row parser
     (columns: current quarter | preceding quarter | same quarter last year | ...),
     with the cheap LLM only as a fallback for unusual layouts.
All growth maths runs in `numbers.py` (Decimal). If the two sources disagree by >2%, the card says so.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, FinancialPeriod
from ..research.periods import quarter_label
from . import llm
from .numbers import growth_pct, margin_pct

HEADLINE = ["revenue", "ebitda", "pbt", "pat"]
LABELS = {"revenue": "Revenue", "ebitda": "EBITDA", "pbt": "PBT", "pat": "PAT"}


def periods(s: Session, ticker: str, ptype: str = "Q") -> list[FinancialPeriod]:
    rows = s.scalars(
        select(FinancialPeriod)
        .where(FinancialPeriod.ticker == ticker, FinancialPeriod.period_type == ptype)
        .order_by(FinancialPeriod.period_end)
    ).all()
    # prefer consolidated if both bases exist
    by_end: dict[date, FinancialPeriod] = {}
    for r in rows:
        if r.period_end not in by_end or r.basis == "consolidated":
            by_end[r.period_end] = r
    return [by_end[k] for k in sorted(by_end)]


def _same_quarter_last_year(qs: list[FinancialPeriod], cur: FinancialPeriod) -> FinancialPeriod | None:
    for q in qs:
        if q.period_end.year == cur.period_end.year - 1 and q.period_end.month == cur.period_end.month:
            return q
    return None


def results_card(s: Session, ticker: str, period_end: date | None = None) -> dict | None:
    qs = periods(s, ticker, "Q")
    if not qs:
        return None
    idx = len(qs) - 1
    if period_end:
        idx = next((i for i, q in enumerate(qs) if q.period_end == period_end), idx)
    cur = qs[idx]
    prev = qs[idx - 1] if idx > 0 else None
    yoy = _same_quarter_last_year(qs, cur)
    company = s.get(Company, ticker)
    fin = bool(company and company.is_financial)

    rows = []
    for k in HEADLINE:
        c = cur.metrics.get(k)
        p = prev.metrics.get(k) if prev else None
        y = yoy.metrics.get(k) if yoy else None
        note = None
        if k == "ebitda" and fin:
            note = "Not meaningful for lenders (interest is the core cost); shown as Operating/Financing profit where reported."
        rows.append(
            {
                "metric": k,
                "label": LABELS[k],
                "current": c,
                "previous": p,
                "year_ago": y,
                "qoq_pct": growth_pct(c, p),
                "yoy_pct": growth_pct(c, y),
                "note": note,
            }
        )
    m_cur = margin_pct(cur.metrics.get("ebitda"), cur.metrics.get("revenue"))
    m_yoy = margin_pct(yoy.metrics.get("ebitda"), yoy.metrics.get("revenue")) if yoy else None
    m_prev = margin_pct(prev.metrics.get("ebitda"), prev.metrics.get("revenue")) if prev else None
    pat_m_cur = margin_pct(cur.metrics.get("pat"), cur.metrics.get("revenue"))
    pat_m_yoy = margin_pct(yoy.metrics.get("pat"), yoy.metrics.get("revenue")) if yoy else None

    exceptional = cur.metrics.get("exceptional")
    flags = []
    if exceptional:
        flags.append(f"Exceptional items of ₹{exceptional:,.0f} Cr this quarter — PAT growth may not reflect the core business.")
    if cur.metrics.get("other_income") and cur.metrics.get("pbt"):
        share = cur.metrics["other_income"] / cur.metrics["pbt"] * 100 if cur.metrics["pbt"] else 0
        if share > 25:
            flags.append(f"Other income is {share:.0f}% of PBT — profit leans on non-operating income.")

    trend = [
        {
            "label": quarter_label(q.period_end),
            "revenue": q.metrics.get("revenue"),
            "ebitda": q.metrics.get("ebitda"),
            "pat": q.metrics.get("pat"),
            "pbt": q.metrics.get("pbt"),
            "ebitda_margin": margin_pct(q.metrics.get("ebitda"), q.metrics.get("revenue")),
        }
        for q in qs[max(0, idx - 7) : idx + 1]
    ]
    return {
        "ticker": ticker,
        "period": quarter_label(cur.period_end),
        "period_end_label": cur.label,
        "previous_period": quarter_label(prev.period_end) if prev else None,
        "year_ago_period": quarter_label(yoy.period_end) if yoy else None,
        "basis": cur.basis,
        "unit": cur.unit,
        "rows": rows,
        "margins": {
            "ebitda_margin": m_cur,
            "ebitda_margin_prev": m_prev,
            "ebitda_margin_yoy": m_yoy,
            "ebitda_margin_change_bps_yoy": round((m_cur - m_yoy) * 100) if m_cur is not None and m_yoy is not None else None,
            "pat_margin": pat_m_cur,
            "pat_margin_yoy": pat_m_yoy,
        },
        "flags": flags,
        "trend": trend,
        "source": cur.source,
        "source_url": cur.source_url,
        "is_financial": fin,
    }


# ---------------------------------------------------------------- filing parser

_ROW_PATTERNS = {
    "revenue": r"^\s*(?:\(?[ivx]+\)?\.?\s*|\d+\.?\s*|[a-z]\)\s*)?(revenue from operations|income from operations|total revenue from operations|net sales)",
    "other_income": r"^\s*(?:\(?[ivx]+\)?\.?\s*|\d+\.?\s*|[a-z]\)\s*)?other income",
    "finance_cost": r"^\s*(?:\(?[ivx]+\)?\.?\s*|\d+\.?\s*|[a-z]\)\s*)?(finance costs?|interest expenses?)",
    "depreciation": r"^\s*(?:\(?[ivx]+\)?\.?\s*|\d+\.?\s*|[a-z]\)\s*)?depreciation",
    "pbt": r"^\s*(?:\(?[ivx]+\)?\.?\s*|\d+\.?\s*|[a-z]\)\s*)?(profit|\(loss\)|profit\s*/\s*\(loss\)).{0,25}before tax",
    "pat": r"^\s*(?:\(?[ivx]+\)?\.?\s*|\d+\.?\s*|[a-z]\)\s*)?((net )?profit|profit\s*/\s*\(loss\)).{0,40}(for the (period|quarter)|after tax)",
}
_NUM = re.compile(r"\(?-?[\d,]+\.\d+\)?|\(?-?\d{1,3}(?:,\d{2,3})+\)?")


def _to_num(tok: str) -> float:
    neg = tok.startswith("(") or tok.startswith("-")
    v = float(tok.strip("()").replace(",", "").lstrip("-"))
    return -v if neg else v


def _unit_divisor(text: str) -> tuple[float, str]:
    t = text.lower()
    if re.search(r"in\s*(rs\.?|₹|inr)?\s*lakhs?|lakhs", t):
        return 100.0, "lakh"
    if re.search(r"in\s*(rs\.?|₹|inr)?\s*millions?|\(million\)|in mn", t):
        return 10.0, "million"
    return 1.0, "crore"


def parse_results_pages(pages: list[str]) -> dict | None:
    """Deterministic parser for SEBI-format results statements. Returns cur/prev/yoy per metric + page."""
    best = None
    for pno, text in enumerate(pages, start=1):
        if not re.search(r"before tax", text, re.I) or not re.search(r"revenue|income from operations", text, re.I):
            continue
        div, unit = _unit_divisor(text[:3000])
        basis = "consolidated" if re.search(r"consolidated", text[:1500], re.I) else "standalone"
        found: dict[str, list[float]] = {}
        for line in text.splitlines():
            low = line.lower()
            for key, pat in _ROW_PATTERNS.items():
                if key in found or not re.search(pat, low):
                    continue
                nums = [_to_num(t) for t in _NUM.findall(line)]
                if len(nums) >= 3:
                    found[key] = [n / div for n in nums[:3]]
        if {"revenue", "pbt", "pat"} <= found.keys():
            cand = {"page": pno, "unit_in_filing": unit, "basis": basis, "values": found}
            # Prefer consolidated statements when both are in the same PDF.
            if best is None or (basis == "consolidated" and best["basis"] != "consolidated"):
                best = cand
    if not best:
        return None
    v = best["values"]
    out = {}
    for i, col in enumerate(["current", "previous", "year_ago"]):
        ebitda = None
        if all(k in v for k in ("pbt", "finance_cost", "depreciation")):
            ebitda = v["pbt"][i] + v["finance_cost"][i] + v["depreciation"][i] - v.get("other_income", [0, 0, 0])[i]
        out[col] = {
            "revenue": round(v["revenue"][i], 2),
            "ebitda": round(ebitda, 2) if ebitda is not None else None,
            "pbt": round(v["pbt"][i], 2),
            "pat": round(v["pat"][i], 2),
        }
    return {"page": best["page"], "basis": best["basis"], "unit_in_filing": best["unit_in_filing"], "method": "rules", **out}


def llm_parse_results(pages: list[str]) -> dict | None:
    """Fallback for non-standard layouts: cheap model reads only the single most relevant page."""
    if not llm.available():
        return None
    scored = sorted(
        enumerate(pages, 1),
        key=lambda p: -len(re.findall(r"before tax|revenue|finance cost|depreciation", p[1], re.I)),
    )
    if not scored:
        return None
    pno, text = scored[0]
    out = llm.complete_json(
        [
            {
                "role": "system",
                "content": "Extract numbers from an Indian quarterly results statement. Copy figures exactly as printed; "
                "do not compute anything. Columns are usually: quarter ended (current), preceding quarter, corresponding quarter last year. "
                'Reply JSON {"unit":"crore|lakh|million","basis":"consolidated|standalone","current":{"revenue":n,"other_income":n,"finance_cost":n,"depreciation":n,"pbt":n,"pat":n},"previous":{...},"year_ago":{...}}. Use null if absent.',
            },
            {"role": "user", "content": text[:6000]},
        ],
        tier="fast",
        max_tokens=500,
    )
    if not out or "current" not in out:
        return None
    div = {"lakh": 100.0, "million": 10.0}.get(out.get("unit", "crore"), 1.0)
    res = {"page": pno, "basis": out.get("basis"), "unit_in_filing": out.get("unit"), "method": "llm"}
    for col in ("current", "previous", "year_ago"):
        r = out.get(col) or {}
        f = lambda k: (r.get(k) / div) if isinstance(r.get(k), (int, float)) else None  # noqa: E731
        ebitda = None
        if None not in (f("pbt"), f("finance_cost"), f("depreciation")):
            ebitda = f("pbt") + f("finance_cost") + f("depreciation") - (f("other_income") or 0)
        res[col] = {"revenue": f("revenue"), "ebitda": ebitda, "pbt": f("pbt"), "pat": f("pat")}
    return res


def card_from_filing(parsed: dict, period_label: str, source_url: str | None) -> dict:
    rows = []
    for k in HEADLINE:
        c, p, y = (parsed[col].get(k) for col in ("current", "previous", "year_ago"))
        rows.append({"metric": k, "label": LABELS[k], "current": c, "previous": p, "year_ago": y,
                     "qoq_pct": growth_pct(c, p), "yoy_pct": growth_pct(c, y), "note": None})
    return {
        "period": period_label,
        "basis": parsed.get("basis"),
        "unit": "INR crore",
        "rows": rows,
        "source": "pdf",
        "source_url": source_url,
        "page": parsed.get("page"),
        "method": parsed.get("method"),
    }


def reconcile(card: dict, filing: dict | None) -> dict:
    """Cross-check structured-table numbers against the filing. Adds `verification` to the card."""
    if not filing:
        card["verification"] = {"status": "single_source", "detail": "Not cross-checked against the filing PDF."}
        return card
    mismatches = []
    for row in card["rows"]:
        fv = filing["current"].get(row["metric"])
        if fv is None or row["current"] is None:
            continue
        if abs(fv - row["current"]) > max(1.0, abs(row["current"]) * 0.02):
            mismatches.append(f"{row['label']}: table {row['current']:,.0f} vs filing {fv:,.0f}")
    card["verification"] = (
        {"status": "verified", "detail": f"Matches the results filing (p.{filing['page']}, {filing['basis']}) within 2%."}
        if not mismatches
        else {"status": "mismatch", "detail": "; ".join(mismatches) + " — check basis (consolidated vs standalone) or restatement."}
    )
    card["filing_page"] = filing.get("page")
    return card
