"""Results intelligence: structured quarter cards, a deterministic SEBI-format PDF parser, reconciliation."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, FinancialPeriod
from ..research.periods import fy_label, month_label, quarter_label
from . import llm
from . import numbers as N

HEADLINE = [("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pbt", "PBT"), ("pat", "PAT")]
LENDER_NOTE = ("Not meaningful for lenders: banks and NBFCs earn from interest spread, so EBITDA is not reported. "
               "Use NIM, credit costs and asset quality instead.")


def periods(s: Session, ticker: str, ptype: str = "Q") -> list[FinancialPeriod]:
    """Periods ascending, preferring the consolidated basis per period end."""
    rows = s.scalars(select(FinancialPeriod).where(FinancialPeriod.ticker == ticker,
                                                   FinancialPeriod.period_type == ptype)
                     .order_by(FinancialPeriod.period_end)).all()
    best: dict[date, FinancialPeriod] = {}
    for r in rows:
        cur = best.get(r.period_end)
        if cur is None or (r.basis == "consolidated" and cur.basis != "consolidated"):
            best[r.period_end] = r
    return [best[k] for k in sorted(best)]


def _find(rows: list[FinancialPeriod], target: date, tol_days: int = 20) -> Optional[FinancialPeriod]:
    for r in rows:
        if abs((r.period_end - target).days) <= tol_days:
            return r
    return None


def _m(r: Optional[FinancialPeriod], k: str):
    return (r.metrics or {}).get(k) if r else None


def results_card(s: Session, ticker: str, period_end: Optional[date] = None) -> Optional[dict]:
    qs = periods(s, ticker, "Q")
    if not qs:
        return None
    cur = _find(qs, period_end) if period_end else qs[-1]
    if cur is None:
        return None
    prev = _find(qs, cur.period_end - timedelta(days=91))
    ya = _find(qs, cur.period_end - timedelta(days=365))
    comp = s.get(Company, ticker)
    lender = bool(comp and comp.is_financial)
    rows = []
    for key, label in HEADLINE:
        c, p, y = _m(cur, key), _m(prev, key), _m(ya, key)
        na = lender and key == "ebitda"
        rows.append({"key": key, "label": label, "current": None if na else c, "previous": None if na else p,
                     "year_ago": None if na else y, "qoq": None if na else N.growth_pct(c, p),
                     "yoy": None if na else N.growth_pct(c, y), "note": LENDER_NOTE if na else None})
    em = lambda r: None if lender else N.margin_pct(_m(r, "ebitda"), _m(r, "revenue"))  # noqa: E731
    pm = lambda r: N.margin_pct(_m(r, "pat"), _m(r, "revenue"))  # noqa: E731
    flags = []
    exc = _m(cur, "exceptional")
    if exc not in (None, 0, 0.0):
        flags.append(f"Exceptional items of {N.fmt_cr(exc)} this quarter")
    oi, pbt = _m(cur, "other_income"), _m(cur, "pbt")
    if oi and pbt and pbt > 0 and oi / pbt > 0.25:
        flags.append(f"Other income is {oi / pbt:.0%} of PBT, so core profit is weaker than PBT suggests")
    trend = []
    for r in qs[-8:]:
        trend.append({"label": quarter_label(r.period_end), "period_end": r.period_end.isoformat(),
                      "revenue": _m(r, "revenue"), "pat": _m(r, "pat"), "ebitda_margin": em(r)})
    return {
        "ticker": ticker, "period_end": cur.period_end.isoformat(), "period_label": quarter_label(cur.period_end),
        "period_end_label": month_label(cur.period_end),
        "previous_label": quarter_label(prev.period_end) if prev else None,
        "year_ago_label": quarter_label(ya.period_end) if ya else None,
        "basis": cur.basis, "unit": cur.unit, "source": cur.source, "source_url": cur.source_url,
        "is_financial": lender, "rows": rows,
        "margins": {"ebitda_margin": em(cur), "ebitda_margin_prev": em(prev), "ebitda_margin_year_ago": em(ya),
                    "ebitda_margin_yoy_bps": N.bps(em(cur), em(ya)), "pat_margin": pm(cur)},
        "lender_note": LENDER_NOTE if lender else None, "flags": flags, "trend": trend,
    }


def card_from_filing(filing: dict, ticker: str, published: date, is_financial: bool) -> dict:
    """Results card from the filing alone when no structured quarter is available (status single_source)."""
    rows = []
    for key, label in HEADLINE:
        c, p, y = filing.get(key), filing.get(f"{key}_prev"), filing.get(f"{key}_ya")
        na = is_financial and key == "ebitda"
        rows.append({"key": key, "label": label, "current": None if na else c, "previous": None if na else p,
                     "year_ago": None if na else y, "qoq": None if na else N.growth_pct(c, p),
                     "yoy": None if na else N.growth_pct(c, y), "note": LENDER_NOTE if na else None})
    em = None if is_financial else N.margin_pct(filing.get("ebitda"), filing.get("revenue"))
    em_ya = None if is_financial else N.margin_pct(filing.get("ebitda_ya"), filing.get("revenue_ya"))
    return {"ticker": ticker, "period_end": None, "period_label": "Latest quarter (from filing)",
            "period_end_label": None, "basis": filing.get("basis"), "unit": "INR crore", "source": "pdf",
            "is_financial": is_financial, "rows": rows,
            "margins": {"ebitda_margin": em, "ebitda_margin_year_ago": em_ya, "ebitda_margin_yoy_bps": N.bps(em, em_ya),
                        "pat_margin": N.margin_pct(filing.get("pat"), filing.get("revenue"))},
            "lender_note": LENDER_NOTE if is_financial else None, "flags": [], "trend": [],
            "verification": {"status": "single_source",
                             "detail": "Built from the results filing alone; no structured financials to cross-check"}}


# ---------------------------------------------------------------- PDF parser
_NUM = r"\(?-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?\)?"
_NUM_RE = re.compile(_NUM)
_PFX = r"^\s*(?:\(?[ivx]+\)|\(?[a-h]\)|\d{1,2}[.)]?)?\s*"
ROWS = {
    "revenue": re.compile(_PFX + r"(revenue from operations|income from operations|net sales)\b", re.I),
    "other_income": re.compile(_PFX + r"other income\b", re.I),
    "interest": re.compile(_PFX + r"(finance costs?|interest expenses?)\b", re.I),
    "depreciation": re.compile(_PFX + r"depreciation", re.I),
    "pbt": re.compile(_PFX + r"(?!.*exceptional items and tax)(net\s+)?profit.{0,30}before tax", re.I),
    "pat": re.compile(_PFX + r"(net\s+)?profit.{0,40}(for the period|after tax)", re.I),
}


def _to_num(tok: str) -> Optional[float]:
    neg = tok.startswith("(") and tok.endswith(")")
    t = tok.strip("()").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _numbers(line: str) -> list[float]:
    out = []
    for m in _NUM_RE.finditer(line):
        tok = m.group(0)
        if "." not in tok and "," not in tok:  # bare integers: only Indian-grouped or decimals count
            continue
        v = _to_num(tok)
        if v is not None:
            out.append(v)
    return out


def _page_unit(text: str) -> float:
    head = text[:2500].lower()
    if "lakh" in head or "lac" in head:
        return 0.01
    if "million" in head:
        return 0.1
    return 1.0


def parse_results_pages(pages: list[str]) -> Optional[dict]:
    """Parse a SEBI-format results table. Returns current/prev/year-ago for the headline metrics (INR crore)."""
    cands = []
    for i, txt in enumerate(pages):
        low = txt.lower()
        if "before tax" in low and re.search(r"revenue|income from operations", low):
            basis = "consolidated" if "consolidated" in low[:1500] else "standalone"
            cands.append((0 if basis == "consolidated" else 1, i, basis))
    for _, idx, basis in sorted(cands):
        text = pages[idx]
        unit = _page_unit(text)
        lines = [ln.strip() for ln in text.splitlines()]
        found: dict[str, list[float]] = {}
        for j, ln in enumerate(lines):
            for key, rx in ROWS.items():
                if key in found or not rx.search(ln):
                    continue
                if key == "pbt" and re.search(r"exceptional items and tax", ln, re.I):
                    continue
                nums = _numbers(ln)
                k = j + 1
                while len(nums) < 3 and k < len(lines) and k <= j + 4:  # numbers may wrap onto following lines
                    if any(r.search(lines[k]) for r in ROWS.values()):
                        break
                    nums += _numbers(lines[k])
                    k += 1
                if len(nums) >= 3:
                    found[key] = [n * unit for n in nums[:3]]
        if not {"revenue", "pbt", "pat"} <= found.keys():
            continue
        out: dict[str, Any] = {"page": idx + 1, "basis": basis, "unit_factor": unit}
        for slot, suf in ((0, ""), (1, "_prev"), (2, "_ya")):
            g = lambda k: found[k][slot] if k in found else 0.0  # noqa: E731
            for k in ("revenue", "other_income", "interest", "depreciation", "pbt", "pat"):
                if k in found:
                    out[k + suf] = round(found[k][slot], 2)
            out["ebitda" + suf] = round(g("pbt") + g("interest") + g("depreciation") - g("other_income"), 2)
        return out
    return None


def llm_read_page(pages: list[str]) -> Optional[dict]:
    """Fallback: the fast LLM reads the single most relevant page (numbers only, no maths)."""
    if not llm.available() or not pages:
        return None
    best = max(range(len(pages)), key=lambda i: sum(pages[i].lower().count(w) for w in
                                                    ("revenue", "profit", "tax", "expenses")))
    out = llm.complete_json([
        {"role": "system", "content": "Copy numbers from an Indian results table. Do no arithmetic. JSON only."},
        {"role": "user", "content": "From this page return JSON with keys revenue, other_income, interest, depreciation, "
                                    "pbt, pat for the current quarter, each also with suffix _prev (preceding quarter) "
                                    "and _ya (same quarter last year), in the units printed, plus unit "
                                    f"('crore'|'lakh'|'million') and basis.\n\n{pages[best][:6000]}"},
    ], tier="fast")
    if not isinstance(out, dict):
        return None
    factor = {"lakh": 0.01, "million": 0.1}.get(str(out.get("unit", "")).lower(), 1.0)
    res: dict[str, Any] = {"page": best + 1, "basis": out.get("basis") or "unknown", "method": "llm"}
    for suf in ("", "_prev", "_ya"):
        vals = {}
        for k in ("revenue", "other_income", "interest", "depreciation", "pbt", "pat"):
            try:
                vals[k] = float(out.get(k + suf)) * factor
            except (TypeError, ValueError):
                vals[k] = None
        for k, v in vals.items():
            if v is not None:
                res[k + suf] = round(v, 2)
        if None not in (vals["pbt"], vals["interest"], vals["depreciation"], vals["other_income"]):
            res["ebitda" + suf] = round(vals["pbt"] + vals["interest"] + vals["depreciation"] - vals["other_income"], 2)
    return res if "revenue" in res and "pat" in res else None


def reconcile(card: dict, filing: Optional[dict]) -> dict:
    if not filing:
        return {"status": "unverified", "detail": "No results table could be read from the filing"}
    mism = []
    checked = 0
    for row in card["rows"]:
        k = row["key"]
        if row["current"] is None or filing.get(k) is None:
            continue
        checked += 1
        a, b = row["current"], filing[k]
        if abs(a - b) > max(1.0, 0.02 * abs(a)):
            mism.append(f"{row['label']}: structured {N.fmt_cr(a)} vs filing {N.fmt_cr(b)}")
    if not checked:
        return {"status": "unverified", "detail": "No overlapping metrics to compare"}
    where = f"p.{filing.get('page')}, {filing.get('basis')}"
    if mism:
        return {"status": "mismatch", "detail": "; ".join(mism) + " (check basis or restatement)", "page": filing.get("page")}
    return {"status": "verified", "detail": f"Matches the results filing ({where}) within 2%", "page": filing.get("page")}


def annual_label(d: date) -> str:
    return fy_label(d)
