"""Rule-based financial-health early warning. Explicitly NOT a probability of default."""
from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Company
from ..services import numbers as N
from ..services.results import periods as fin_periods
from . import retrieval
from .periods import fy_label

DISCLAIMER = ("A rule-based early-warning screen over reported financials and annual-report text. It is not a "
              "credit rating and not a probability of default.")
LENDER_NOTE = ("For banks and NBFCs, leverage, cash-flow and working-capital ratios are not meaningful. NIM, GNPA "
               "and capital adequacy (CAR) are the right lenses, but they are not in this data source.")


def _dir(vals: list[float]) -> str:
    v = [x for x in vals if x is not None]
    if len(v) < 2 or v[0] == 0:
        return "flat"
    ch = (v[-1] - v[0]) / abs(v[0])
    return "rising" if ch > 0.05 else "falling" if ch < -0.05 else "flat"


def _check(pillar, metric, current, unit, history, label, interp, source="financials", completeness=1.0, **extra):
    return {"pillar": pillar, "metric": metric, "current": current, "unit": unit,
            "history": [[h[0], h[1]] for h in history], "direction": _dir([h[1] for h in history]),
            "label": label, "interpretation": interp, "source": source, "completeness": completeness, **extra}


def _insufficient(pillar, metric, why):
    return _check(pillar, metric, None, None, [], "insufficient", why, completeness=0.0)


def assess(s: Session, ticker: str) -> dict[str, Any]:
    comp = s.get(Company, ticker)
    lender = bool(comp and comp.is_financial)
    ys = fin_periods(s, ticker, "Y")[-6:]
    if not ys:
        return {"ticker": ticker, "overall": "insufficient", "reason": "No annual financials available.",
                "pillars": [], "checks": [], "disclaimer": DISCLAIMER, "data_completeness": 0.0,
                "lender_note": LENDER_NOTE if lender else None}
    lab = [fy_label(y.period_end) for y in ys]
    m = lambda k: [(y.metrics or {}).get(k) for y in ys]  # noqa: E731
    rev, ebitda, pat, pbt, interest = m("revenue"), m("ebitda"), m("pat"), m("pbt"), m("interest")
    nw, debt, cfo, cfi, fcf = m("net_worth"), m("borrowings"), m("cfo"), m("cfi"), m("fcf")
    src = ys[-1].source
    checks: list[dict] = []

    # ---- profitability
    growth = [(lab[i], N.growth_pct(rev[i], rev[i - 1])) for i in range(1, len(ys))]
    g_last = growth[-1][1] if growth else None
    cagr = N.cagr_pct(rev[-1], rev[0], len(ys) - 1) if len(ys) > 1 else None
    if g_last is None:
        checks.append(_insufficient("Profitability", "Revenue growth", "Need two years of revenue."))
    else:
        lbl = "elevated" if g_last < -10 else "monitor" if g_last < 0 else "stable"
        checks.append(_check("Profitability", "Revenue growth", g_last, "%", growth, lbl,
                             f"Revenue {'fell' if g_last < 0 else 'grew'} {abs(g_last):.1f}% in {lab[-1]}"
                             + (f"; {cagr:.1f}% a year over {len(ys) - 1} years." if cagr is not None else "."),
                             source=src))
    if not lender:
        em = [(lab[i], N.margin_pct(ebitda[i], rev[i])) for i in range(len(ys))]
        vals = [v for _, v in em if v is not None]
        if vals:
            cur, peak = vals[-1], max(vals)
            prev = vals[-2] if len(vals) > 1 else cur
            lbl = "elevated" if peak - cur > 5 else "monitor" if prev - cur > 1.5 else "stable"
            checks.append(_check("Profitability", "EBITDA margin", cur, "%", em, lbl,
                                 f"{cur:.1f}% versus a recent peak of {peak:.1f}%; {cur - prev:+.1f} pp YoY.", source=src))
    pm = [(lab[i], N.margin_pct(pat[i], rev[i])) for i in range(len(ys))]
    if pm[-1][1] is not None:
        checks.append(_check("Profitability", "PAT margin", pm[-1][1], "%", pm, "stable",
                             f"{pm[-1][1]:.1f}% of revenue reached the bottom line in {lab[-1]}.", source=src))
    roe = [(lab[i], (ys[i].metrics or {}).get("roe")) for i in range(len(ys))]
    if roe[-1][1] is not None:
        checks.append(_check("Profitability", "ROE", roe[-1][1], "%", roe, "monitor" if roe[-1][1] < 10 else "stable",
                             f"Return on equity {roe[-1][1]:.1f}%" + (" is below 10%." if roe[-1][1] < 10 else "."),
                             source=src))
    if not lender:
        roce = [(lab[i], (ys[i].metrics or {}).get("roce")) for i in range(len(ys))]
        if roce[-1][1] is not None:
            checks.append(_check("Profitability", "ROCE", roce[-1][1], "%", roce,
                                 "monitor" if roce[-1][1] < 12 else "stable",
                                 f"Return on capital employed {roce[-1][1]:.1f}%"
                                 + (" is below 12%." if roce[-1][1] < 12 else "."), source=src))

    # ---- leverage
    if lender:
        for metric in ("Debt to equity", "Interest coverage", "Total debt"):
            checks.append(_insufficient("Leverage", metric, LENDER_NOTE))
    else:
        de = [(lab[i], N.ratio(debt[i], nw[i])) for i in range(len(ys))]
        dv = [v for _, v in de if v is not None]
        if dv:
            cur = dv[-1]
            base3 = dv[-4] if len(dv) >= 4 else dv[0]
            lbl = "elevated" if cur > 1.5 else "monitor" if (cur > 0.8 or cur - base3 > 0.3) else "stable"
            checks.append(_check("Leverage", "Debt to equity", cur, "x", de, lbl,
                                 f"Borrowings are {cur:.2f}× net worth"
                                 + (f", up from {base3:.2f}× three years earlier." if cur - base3 > 0.05 else "."),
                                 source=src))
        ic = [(lab[i], N.ratio((pbt[i] or 0) + (interest[i] or 0), interest[i], 1) if interest[i] else None)
              for i in range(len(ys))]
        if ic[-1][1] is not None:
            v = ic[-1][1]
            checks.append(_check("Leverage", "Interest coverage", v, "x", ic,
                                 "elevated" if v < 2 else "monitor" if v < 4 else "stable",
                                 f"Operating profit covers interest {v:.1f}×.", source=src))
        dh = [(lab[i], debt[i]) for i in range(len(ys)) if debt[i] is not None]
        if dh:
            d = _dir([v for _, v in dh])
            checks.append(_check("Leverage", "Total debt", dh[-1][1], "INR cr", dh,
                                 "monitor" if d == "rising" and dh[-1][1] > 0 else "stable",
                                 f"Borrowings {N.fmt_cr(dh[-1][1])}, trend {d}.", source=src))

    # ---- cash quality
    if lender:
        checks.append(_insufficient("Cash quality", "CFO / PAT", LENDER_NOTE))
    else:
        if all(v is not None for v in cfo[-3:]) and all(v is not None for v in pat[-3:]) and len(ys) >= 3:
            conv = N.ratio(sum(cfo[-3:]), sum(pat[-3:]), 2)
            hist = [(lab[i], N.ratio(cfo[i], pat[i], 2)) for i in range(len(ys))]
            if conv is not None:
                pct = conv * 100
                checks.append(_check("Cash quality", "CFO / PAT (3-yr)", N.rnd(pct, 0), "%", hist,
                                     "elevated" if pct < 50 else "monitor" if pct < 80 else "stable",
                                     f"Over three years, {pct:.0f}% of reported profit arrived as operating cash.",
                                     source=src))
        f = [(lab[i], fcf[i] if fcf[i] is not None else ((cfo[i] or 0) + (cfi[i] or 0) if cfo[i] is not None else None))
             for i in range(len(ys))]
        last3 = [v for _, v in f[-3:] if v is not None]
        if last3:
            neg = sum(1 for v in last3 if v < 0)
            checks.append(_check("Cash quality", "Free cash flow", f[-1][1], "INR cr", f,
                                 "elevated" if neg >= 3 else "monitor" if neg == 2 else "stable",
                                 f"Free cash flow (CFO + CFI proxy) was negative in {neg} of the last {len(last3)} years.",
                                 source=src))

    # ---- working capital
    if lender:
        checks.append(_insufficient("Working capital", "Cash conversion cycle", LENDER_NOTE))
    else:
        for key, metric, thr in (("debtor_days", "Receivable days", 20), ("inventory_days", "Inventory days", 25),
                                 ("ccc", "Cash conversion cycle", 25)):
            h = [(lab[i], (ys[i].metrics or {}).get(key)) for i in range(len(ys))]
            vals = [v for _, v in h if v is not None]
            if len(vals) < 2:
                continue
            cur, best = vals[-1], min(vals[:-1])
            inc = cur - best
            lbl = "elevated" if inc > 1.5 * thr else "monitor" if inc > thr else "stable"
            if key == "inventory_days" and max(vals) == 0:
                continue
            checks.append(_check("Working capital", metric, cur, "days", h, lbl,
                                 f"{cur:.0f} days versus a best of {best:.0f} in the period ({inc:+.0f})."
                                 if inc > 0 else f"{cur:.0f} days, at or better than the period's best.", source=src))

    # ---- disclosed risks (text-detected from the annual report)
    checks += disclosed_risks(s, ticker)

    # ---- overall
    numeric = [c for c in checks if not c.get("text_detected")]
    elevated_pillars = {c["pillar"] for c in numeric if c["label"] == "elevated"}
    monitors = sum(1 for c in numeric if c["label"] == "monitor")
    if len(elevated_pillars) >= 2:
        overall = "elevated"
        reason = f"Elevated signals in {len(elevated_pillars)} pillars: {', '.join(sorted(elevated_pillars))}."
    elif elevated_pillars or monitors >= 3:
        overall = "monitor"
        reason = (f"Elevated signal in {next(iter(elevated_pillars))}" if elevated_pillars else
                  f"{monitors} metrics to monitor") + "; not enough breadth to call it stress."
    else:
        overall = "stable"
        reason = "No pillar shows an elevated signal" + (f"; {monitors} metric(s) to monitor." if monitors else ".")
    complete = [c["completeness"] for c in numeric]
    pillars = []
    for p in ("Profitability", "Leverage", "Cash quality", "Working capital", "Disclosed risks"):
        cs = [c for c in checks if c["pillar"] == p]
        if cs:
            rank = {"elevated": 3, "monitor": 2, "stable": 1, "insufficient": 0}
            pillars.append({"pillar": p, "label": max(cs, key=lambda c: rank[c["label"]])["label"], "checks": cs})
    return {"ticker": ticker, "overall": overall, "reason": reason, "pillars": pillars, "checks": checks,
            "data_completeness": N.rnd(sum(complete) / len(complete), 2) if complete else 0.0,
            "years": lab, "disclaimer": DISCLAIMER, "lender_note": LENDER_NOTE if lender else None,
            "is_financial": lender, "source": src}


RISK_PROBES = [
    ("Auditor qualification", "independent auditor's report opinion qualified unmodified emphasis of matter",
     r"basis for qualified opinion|adverse opinion", "elevated"),
    ("Contingent liabilities", "contingent liabilities claims not acknowledged as debts guarantees", r"contingent liabilit",
     "monitor"),
    ("Related-party transactions", "related party transactions arm's length", r"related part", "monitor"),
    ("Promoter pledging", "promoter shares pledged encumbered", r"pledg|encumb", "monitor"),
]


def disclosed_risks(s: Session, ticker: str) -> list[dict]:
    out = []
    for metric, query, pat, flag in RISK_PROBES:
        hits = retrieval.search(s, ticker, query, k=3, doc_types=["annual_report"])
        hit = next((h for h in hits if re.search(pat if metric != "Auditor qualification" else r"opinion", h["text"], re.I)),
                   None)
        if not hit:
            continue
        text = hit["text"]
        if metric == "Auditor qualification":
            bad = re.search(pat, text, re.I) and not re.search(r"opinion is not modified|not modified in respect", text, re.I)
            label = "elevated" if bad else "stable"
            interp = ("The auditor qualified the opinion; read the basis paragraph." if bad else
                      "Unmodified audit opinion" + (" with an emphasis of matter (opinion not modified)."
                                                    if re.search(r"emphasis of matter", text, re.I) else "."))
        elif metric == "Promoter pledging":
            nil = re.search(r"pledg\w*[^.]{0,40}\bnil\b|\bnil\b[^.]{0,40}pledg|no shares[^.]{0,30}pledg", text, re.I)
            label = "stable" if nil else "monitor"
            interp = "Promoter shares pledged: nil." if nil else "Promoter pledging disclosed; read this."
        else:
            label = flag
            interp = f"{metric} are disclosed in the notes; read this."
        out.append(_check("Disclosed risks", metric, None, None, [], label, interp, source=hit["source"],
                          text_detected=True,
                          evidence={"excerpt": text[:420], "page": hit["page"], "document": hit["document"],
                                    "document_id": hit["document_id"], "url": hit["url"]}))
    return out
