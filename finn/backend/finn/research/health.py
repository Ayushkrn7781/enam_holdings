"""Financial-health early warning. Explainable rules over multi-year statements — not a credit model.

Each check returns: metric, current value, history, direction, label (stable|monitor|elevated|insufficient),
interpretation and source. The overall label needs signals in >=2 pillars before saying "Elevated":
one bad metric alone never implies distress.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Company
from ..services.numbers import cagr_pct, growth_pct, margin_pct, ratio
from ..services.results import periods
from . import retrieval


def _series(ys, key):
    return [(y.label, y.metrics.get(key)) for y in ys]


def _dir(vals: list[float | None]) -> str:
    v = [x for x in vals if x is not None]
    if len(v) < 2:
        return "n/a"
    if v[-1] > v[0] * 1.05 if v[0] >= 0 else v[-1] > v[0]:
        return "rising"
    if v[-1] < v[0] * 0.95 if v[0] >= 0 else v[-1] < v[0]:
        return "falling"
    return "flat"


def _check(pillar, metric, current, hist, label, interp, unit="", src=None, completeness=None):
    return {
        "pillar": pillar,
        "metric": metric,
        "current": current,
        "unit": unit,
        "history": hist,
        "direction": _dir([h[1] for h in hist]) if hist else "n/a",
        "label": label,
        "interpretation": interp,
        "source": src,
        "completeness": completeness if completeness is not None else (sum(h[1] is not None for h in hist) / len(hist) if hist else 0),
    }


def analyse(s: Session, ticker: str) -> dict:
    ys = periods(s, ticker, "Y")[-6:]
    co = s.get(Company, ticker)
    fin = bool(co and co.is_financial)
    src = {"type": ys[-1].source, "url": ys[-1].source_url} if ys else None
    checks: list[dict] = []
    if len(ys) < 2:
        return {"ticker": ticker, "overall": "insufficient", "checks": [], "note": "Fewer than two annual periods available.", "is_financial": fin}

    rev = _series(ys, "revenue")
    pat = _series(ys, "pat")
    # ---------- profitability
    g = cagr_pct(rev[-1][1], rev[0][1], len(rev) - 1)
    last_g = growth_pct(rev[-1][1], rev[-2][1])
    lbl = "insufficient" if g is None else ("elevated" if (last_g or 0) < -10 else "monitor" if (last_g or 0) < 0 else "stable")
    checks.append(_check("Profitability", "Revenue growth", last_g, [(y.label, growth_pct(y.metrics.get("revenue"), p.metrics.get("revenue"))) for p, y in zip(ys, ys[1:])],
                         lbl, f"{len(rev)-1}-yr revenue CAGR {g if g is not None else 'N/A'}%; latest year {last_g if last_g is not None else 'N/A'}%.", "%", src))
    if not fin:
        m = [(y.label, margin_pct(y.metrics.get("ebitda"), y.metrics.get("revenue"))) for y in ys]
        mv = [x[1] for x in m if x[1] is not None]
        delta = (mv[-1] - max(mv[:-1])) if len(mv) >= 3 else None
        lbl = "insufficient" if delta is None else ("elevated" if delta < -5 else "monitor" if mv[-1] < mv[-2] - 1.5 else "stable")
        checks.append(_check("Profitability", "EBITDA margin", mv[-1] if mv else None, m, lbl,
                             "Margin vs. its recent peak" + (f": {delta:+.1f} pp." if delta is not None else "."), "%", src))
    pm = [(y.label, margin_pct(y.metrics.get("pat"), y.metrics.get("revenue"))) for y in ys]
    checks.append(_check("Profitability", "PAT margin", pm[-1][1], pm, "stable" if (pm[-1][1] or 0) > 0 else "elevated",
                         "Bottom-line margin trend.", "%", src))
    roe = _series(ys, "roe")
    if any(v is not None for _, v in roe):
        cur = roe[-1][1]
        checks.append(_check("Profitability", "ROE", cur, roe, "insufficient" if cur is None else "monitor" if cur < 10 else "stable",
                             "Return on shareholders' equity; <10% is weak for most Indian large caps.", "%", src))
    roce = _series(ys, "roce")
    if not fin and any(v is not None for _, v in roce):
        cur = roce[-1][1]
        checks.append(_check("Profitability", "ROCE", cur, roce, "insufficient" if cur is None else "monitor" if cur < 12 else "stable",
                             "Return on capital employed; compare against cost of capital (~11–13%).", "%", src))

    # ---------- leverage
    if fin:
        checks.append(_check("Leverage", "Debt / equity", None, [], "insufficient",
                             "Not meaningful for lenders — borrowings are raw material. Capital adequacy, NIM and asset quality (GNPA) are the right lenses but are not in this data source.", "", src, 0))
    else:
        de = [(y.label, ratio(y.metrics.get("borrowings"), y.metrics.get("net_worth"))) for y in ys]
        cur = de[-1][1]
        trend_up = len([x for x in de if x[1] is not None]) >= 3 and de[-1][1] is not None and de[-3][1] is not None and de[-1][1] > de[-3][1] + 0.3
        lbl = "insufficient" if cur is None else "elevated" if cur > 1.5 else "monitor" if cur > 0.8 or trend_up else "stable"
        checks.append(_check("Leverage", "Debt / equity", cur, de, lbl, "Total borrowings ÷ net worth." + (" Rising over 3 years." if trend_up else ""), "×", src))
        ic = [(y.label, ratio((y.metrics.get("pbt") or 0) + (y.metrics.get("interest") or 0), y.metrics.get("interest"))) for y in ys]
        cur = ic[-1][1]
        lbl = "insufficient" if cur is None else "elevated" if cur < 2 else "monitor" if cur < 4 else "stable"
        checks.append(_check("Leverage", "Interest coverage", cur, ic, lbl, "EBIT ÷ interest; <2× means a thin cushion if earnings dip.", "×", src))
        bor = _series(ys, "borrowings")
        checks.append(_check("Leverage", "Total debt", bor[-1][1], bor, "stable" if _dir([b[1] for b in bor]) != "rising" else "monitor",
                             "Absolute borrowings trend (₹ Cr).", "₹ Cr", src))

    # ---------- cash quality
    cfo = _series(ys, "cfo")
    if any(v is not None for _, v in cfo):
        n = min(3, len(ys))
        sum_cfo = sum((y.metrics.get("cfo") or 0) for y in ys[-n:])
        sum_pat = sum((y.metrics.get("pat") or 0) for y in ys[-n:])
        conv = ratio(sum_cfo, sum_pat, 100, "0.1")
        lbl = "insufficient" if conv is None else "elevated" if conv < 50 else "monitor" if conv < 80 else "stable"
        if fin:
            lbl, interp = "insufficient", "Operating cash flow of lenders swings with loan growth and deposits; conversion is not a meaningful quality test."
        else:
            interp = f"{n}-yr cumulative CFO ÷ PAT. Persistent <80% means profits are not turning into cash."
        checks.append(_check("Cash quality", "Cash conversion (CFO/PAT)", conv, [(y.label, ratio(y.metrics.get("cfo"), y.metrics.get("pat"), 100, "0.1")) for y in ys], lbl, interp, "%", src))
        if not fin:
            fcf = [(y.label, y.metrics.get("fcf") if y.metrics.get("fcf") is not None else ((y.metrics.get("cfo") or 0) + (y.metrics.get("cfi") or 0) if y.metrics.get("cfo") is not None and y.metrics.get("cfi") is not None else None)) for y in ys]
            neg = sum(1 for _, v in fcf[-3:] if v is not None and v < 0)
            checks.append(_check("Cash quality", "Free cash flow", fcf[-1][1], fcf, "elevated" if neg >= 3 else "monitor" if neg == 2 else "stable",
                                 "CFO minus investing outflows (proxy where capex is not broken out). Negative FCF during a capex cycle is normal; persistent negative FCF is not.", "₹ Cr", src))

    # ---------- working capital
    if not fin:
        for key, name, bad in (("debtor_days", "Receivable days", 20), ("inventory_days", "Inventory days", 25), ("ccc", "Cash conversion cycle", 25)):
            sr = _series(ys, key)
            vals = [v for _, v in sr if v is not None]
            if len(vals) >= 2:
                chg = vals[-1] - min(vals[:-1])
                lbl = "elevated" if chg > bad * 1.5 else "monitor" if chg > bad else "stable"
                checks.append(_check("Working capital", name, vals[-1], sr, lbl, f"{chg:+.0f} days vs. the best of the prior years.", "days", src))

    # ---------- disclosed risks (text-detected from the annual report)
    for metric, q in (
        ("Auditor qualification", "qualified opinion basis for qualified opinion emphasis of matter"),
        ("Contingent liabilities", "contingent liabilities claims not acknowledged as debts guarantees"),
        ("Related-party transactions", "related party transactions material related party"),
        ("Promoter pledging", "pledge encumbrance promoter shares pledged"),
    ):
        hits = retrieval.search(s, ticker, q, k=1, doc_types=["annual_report"])
        if hits:
            c, _ = hits[0]
            text = c.text
            lbl = "monitor"
            if metric == "Auditor qualification":
                lbl = "elevated" if "basis for qualified opinion" in text.lower() or "adverse opinion" in text.lower() else "stable"
            if metric == "Promoter pledging" and ("nil" in text.lower() or "not pledged" in text.lower() or "no shares" in text.lower()):
                lbl = "stable"
            checks.append({
                "pillar": "Disclosed risks", "metric": metric, "current": None, "unit": "", "history": [], "direction": "n/a",
                "label": lbl, "interpretation": "Text-detected in the annual report — read the excerpt; FINN does not quantify this.",
                "evidence": {"excerpt": text[:420], "page": c.page, "document": c.document.title, "url": c.document.url},
                "source": {"type": "annual_report", "url": c.document.url}, "completeness": 0.5,
            })
        else:
            checks.append({"pillar": "Disclosed risks", "metric": metric, "current": None, "unit": "", "history": [], "direction": "n/a",
                           "label": "insufficient", "interpretation": "No indexed annual report text to check.", "source": None, "completeness": 0})

    pillars_elev = {c["pillar"] for c in checks if c["label"] == "elevated"}
    # text-detected disclosures are "read this" prompts, not quantitative stress signals
    n_monitor = sum(c["label"] == "monitor" for c in checks if c["pillar"] != "Disclosed risks")
    overall = "elevated" if len(pillars_elev) >= 2 else "monitor" if pillars_elev or n_monitor >= 3 else "stable"
    known = [c for c in checks if c["label"] != "insufficient"]
    return {
        "ticker": ticker,
        "is_financial": fin,
        "overall": overall,
        "overall_reason": (
            f"Elevated signals in {', '.join(sorted(pillars_elev))}." if len(pillars_elev) >= 2
            else f"{len(pillars_elev)} elevated and {n_monitor} monitor signal(s); no multi-pillar stress." if overall == "monitor"
            else "No pillar shows stress."
        ),
        "data_completeness": round(len(known) / len(checks), 2) if checks else 0,
        "periods": [y.label for y in ys],
        "checks": checks,
        "disclaimer": "Rule-based indicator for triage. Not a probability of default or a regulated credit-risk model.",
    }
