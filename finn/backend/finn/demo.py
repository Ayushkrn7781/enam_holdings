"""ILLUSTRATIVE demo dataset — clearly labelled, never presented as real.

Why it exists: evaluators must be able to open FINN without API keys, and exchange sites block
cloud IPs. Every row written here has source="demo"; every generated PDF page carries an
"ILLUSTRATIVE DEMO DOCUMENT" header; the UI shows a persistent DEMO badge.

Dates are relative to the day the dataset is generated (last weekday = latest EOD session).
Planted scenarios exercise each workflow: a results beat (DIXON), a results miss with a
margin squeeze and late filing (TITAN), a CFO change with appointee profile (SUNPHARMA),
an acquisition (KPITTECH), an order win (LT), duplicate filings (TCS), routine noise, volume and
price anomalies, and three companies with four quarters of transcripts for promise-vs-delivered.
People named in demo filings are fictional.
"""
from __future__ import annotations

import calendar
import hashlib
import math
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import settings
from .models import (AlertEvent, AlertRule, Announcement, Chunk, Company, Document, FinancialPeriod, Guidance,
                     Holding, Meta, Price, ResearchLog)
from .universe import ADHOC, ALL, PORTFOLIO

BANNER = "ILLUSTRATIVE DEMO DOCUMENT - NOT A REAL COMPANY FILING - FIGURES ARE SYNTHETIC"

# latest-quarter revenue (Rs cr), YoY growth, EBITDA margin %, D/E, CFO/PAT, debtor days, inventory days
PROFILE = {
    "RELIANCE": (258000, 0.07, 17.5, 0.42, 1.25, 12, 70), "HDFCBANK": (86000, 0.11, None, None, None, None, None),
    "ICICIBANK": (49000, 0.12, None, None, None, None, None), "SBIN": (121000, 0.09, None, None, None, None, None),
    "INFY": (44500, 0.06, 24.5, 0.05, 1.05, 68, 0), "TCS": (66500, 0.05, 27.0, 0.04, 1.02, 75, 0),
    "KPITTECH": (1620, 0.14, 21.0, 0.10, 0.95, 62, 0), "TMPV": (98000, -0.03, 11.0, 0.65, 1.40, 18, 55),
    "MARUTI": (40200, 0.09, 12.0, 0.01, 1.10, 9, 14), "M&M": (45800, 0.16, 14.0, 0.95, 0.85, 22, 45),
    "LT": (67500, 0.12, 10.5, 1.10, 0.90, 95, 12), "ITC": (21200, 0.07, 35.0, 0.0, 1.05, 14, 160),
    "HINDUNILVR": (16100, 0.03, 23.0, 0.0, 1.10, 12, 33), "SUNPHARMA": (14100, 0.09, 28.0, 0.02, 0.95, 95, 210),
    "BHARTIARTL": (52500, 0.18, 55.0, 1.25, 1.80, 25, 0), "NTPC": (45200, 0.04, 28.0, 1.45, 1.70, 55, 40),
    "ASIANPAINT": (8600, -0.01, 18.5, 0.08, 1.15, 34, 105), "POLYCAB": (6700, 0.22, 13.5, 0.02, 0.75, 42, 85),
    "PERSISTENT": (3750, 0.22, 17.0, 0.05, 1.00, 70, 0), "HAL": (7600, 0.11, 28.0, 0.0, 1.20, 80, 300),
    "BAJFINANCE": (19500, 0.24, None, None, None, None, None), "DMART": (16800, 0.15, 8.0, 0.05, 0.90, 1, 30),
}

# Story companies: explicit quarterly paths (Q1 FY25 .. Q2 FY27) so guidance vs. actuals is meaningful.
STORY = {
    "DIXON": {"rev": [6580, 11534, 10454, 10293, 12836, 14855, 13200, 12739, 15900, 20500],
              "m":   [3.9, 3.7, 3.9, 4.1, 4.0, 3.7, 4.1, 4.2, 3.7, 4.0], "de": [0.12, 0.10, 0.15, 0.14, 0.11], "conv": 1.12,
              "dd": [48, 45, 41, 38, 36], "inv": [28, 27, 25, 24, 22]},
    "TITAN": {"rev": [13266, 14656, 17740, 14916, 15520, 16830, 20560, 17370, 17100, 18300],
              "m":   [11.0, 10.9, 11.6, 11.1, 11.2, 10.6, 11.9, 11.0, 10.9, 10.2], "de": [0.55, 0.62, 0.78, 0.95, 1.18], "conv": 0.42,
              "dd": [5, 5, 6, 6, 7], "inv": [205, 210, 222, 236, 262]},
    "TRENT": {"rev": [4104, 4157, 4657, 4217, 4883, 5105, 5800, 5145, 5700, 6050],
              "m":   [16.0, 16.4, 17.2, 16.9, 17.1, 17.4, 18.3, 17.6, 17.0, 17.8], "de": [0.35, 0.30, 0.26, 0.22, 0.18], "conv": 0.98,
              "dd": [3, 3, 3, 2, 2], "inv": [70, 68, 66, 64, 63]},
}

SEASON = {6: 0.96, 9: 1.0, 12: 1.06, 3: 0.98}


def _rng(*key) -> random.Random:
    return random.Random(int(hashlib.md5("|".join(map(str, key)).encode()).hexdigest()[:8], 16))


def quarter_ends(last: date, n: int = 10) -> list[date]:
    out = []
    y, m = last.year, last.month
    for _ in range(n):
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
    return list(reversed(out))


def _qlabel(d: date) -> str:
    return d.strftime("%b %Y")


def _weekdays_back(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def last_session(today: date | None = None) -> date:
    d = (today or date.today()) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def latest_reported_quarter(sess: date) -> date:
    """Quarter whose results season we're in (results land ~2-7 weeks after quarter end)."""
    y, m = sess.year, sess.month
    qm = ((m - 1) // 3) * 3  # previous quarter-end month
    if qm == 0:
        qm, y = 12, y - 1
    return date(y, qm, calendar.monthrange(y, qm)[1])


# ------------------------------------------------------------------------------------ financials

def _q_metrics(rev: float, margin: float | None, rng: random.Random, fin: bool, k: dict) -> dict:
    """k = per-company cost structure, so quarters differ by operations, not random noise."""
    j = lambda: rng.uniform(0.97, 1.03)  # noqa: E731
    if fin:
        pbt = rev * k["bank_pbt"] * j()
        return {"revenue": round(rev, 1), "ebitda": None, "other_income": round(rev * 0.12, 1), "interest": round(rev * 0.48, 1),
                "depreciation": round(rev * 0.012, 1), "pbt": round(pbt, 1), "tax_pct": 25.0, "pat": round(pbt * 0.75, 1), "exceptional": 0}
    ebitda = rev * margin / 100
    oi = rev * k["oi"] * j()
    dep = ebitda * k["dep"] * j()
    intr = ebitda * k["int"] * j()
    pbt = ebitda + oi - dep - intr
    tax = 25.2
    return {"revenue": round(rev, 1), "expenses": round(rev - ebitda, 1), "ebitda": round(ebitda, 1), "other_income": round(oi, 1),
            "interest": round(intr, 1), "depreciation": round(dep, 1), "pbt": round(pbt, 1), "tax_pct": tax,
            "pat": round(pbt * (1 - tax / 100), 1), "exceptional": 0}


def build_financials(ticker: str, fin: bool, qends: list[date]) -> tuple[list[dict], list[dict]]:
    rng = _rng("fin", ticker)
    k = {"oi": rng.uniform(0.002, 0.008), "dep": rng.uniform(0.12, 0.26), "int": rng.uniform(0.02, 0.10), "bank_pbt": rng.uniform(0.24, 0.30)}
    if ticker in STORY:
        st = STORY[ticker]
        qs = [_q_metrics(r, m, rng, fin, k) for r, m in zip(st["rev"], st["m"])]
    else:
        R, g, m, *_ = PROFILE[ticker]
        qs = []
        for i, qe in enumerate(qends):
            t = len(qends) - 1 - i
            rev = R / ((1 + g) ** (t / 4)) * SEASON[qe.month] / SEASON[qends[-1].month] * (1 + rng.uniform(-0.025, 0.025))
            mm = None if m is None else m + rng.uniform(-0.6, 0.6)
            qs.append(_q_metrics(rev, mm, rng, fin, k))
    quarters = [{"period_end": qe, "label": _qlabel(qe), "metrics": q} for qe, q in zip(qends, qs)]

    # annual: the two most recent full FYs are sums of their quarters; earlier years back-extrapolated
    fy_ends = [q for q in qends if q.month == 3]
    annual = []
    for fe in fy_ends:
        four = [q for q in quarters if fe - timedelta(days=360) < q["period_end"] <= fe]
        if len(four) == 4:
            annual.append({"period_end": fe, "metrics": {k: round(sum((q["metrics"].get(k) or 0) for q in four), 1) if not fin or k != "ebitda" else None
                                                        for k in ("revenue", "ebitda", "other_income", "interest", "depreciation", "pbt", "pat")}})
    g_back = (annual[-1]["metrics"]["revenue"] / annual[0]["metrics"]["revenue"] - 1) if len(annual) >= 2 else PROFILE.get(ticker, (0, 0.1))[1]
    g_back = max(0.04, min(0.35, g_back))
    while len(annual) < 5:
        first = annual[0]
        f = 1 / (1 + g_back * rng.uniform(0.8, 1.2))
        mfac = rng.uniform(0.94, 1.04)
        annual.insert(0, {"period_end": date(first["period_end"].year - 1, 3, 31),
                          "metrics": {k: (round(v * f * (mfac if k in ("ebitda", "pbt", "pat") else 1), 1) if v is not None else None) for k, v in first["metrics"].items()}})
    # balance sheet, cash flow, working capital
    st = STORY.get(ticker)
    prof = PROFILE.get(ticker)
    for i, a in enumerate(annual):
        m = a["metrics"]
        nw = m["pat"] * (rng.uniform(5.5, 7.5) if not fin else 6.5) * (1 + 0.08 * i)
        de = st["de"][i] if st else (prof[3] if prof and prof[3] is not None else None)
        conv = st["conv"] if st else (prof[4] if prof and prof[4] is not None else None)
        m["net_worth"] = round(nw, 1)
        m["borrowings"] = round(nw * de * rng.uniform(0.9, 1.1), 1) if de is not None else round(m["revenue"] * 6.5, 1)
        if conv is not None:
            m["cfo"] = round(m["pat"] * conv * rng.uniform(0.85, 1.15), 1)
            m["cfi"] = round(-abs(m["cfo"]) * (1.6 if ticker == "TITAN" else rng.uniform(0.45, 0.85)), 1)
        else:
            m["cfo"] = round(m["pat"] * rng.uniform(-1.5, 2.5), 1)
            m["cfi"] = round(-m["pat"] * rng.uniform(0.2, 0.6), 1)
        if not fin:
            dd = st["dd"][i] if st else (prof[5] + rng.uniform(-4, 4))
            inv = st["inv"][i] if st else (prof[6] + rng.uniform(-6, 6))
            pay = 45 + rng.uniform(-8, 8) if not st else (40 if ticker != "TITAN" else 20)
            m.update({"debtor_days": round(dd), "inventory_days": round(inv), "payable_days": round(pay), "ccc": round(dd + inv - pay)})
            ebit = m["pbt"] + m["interest"]
            m["roce"] = round(ebit / (nw + m["borrowings"]) * 100, 1)
        m["roe"] = round(m["pat"] / nw * 100, 1)
        a["label"] = f"Mar {a['period_end'].year}"
    return quarters, annual


# ------------------------------------------------------------------------------------ prices

PLANTS: dict[str, dict[int, tuple[float, float]]] = {
    # sessions-ago -> (return %, volume multiple)
    "DIXON": {0: (6.8, 3.4)},
    "SUNPHARMA": {0: (-4.6, 2.3)},
    "KPITTECH": {0: (3.1, 2.6)},
    "POLYCAB": {1: (5.1, 2.1)},
    "ASIANPAINT": {6: (-4.3, 1.9)},
    "RELIANCE": {4: (1.2, 2.2)},
    "LT": {0: (2.4, 1.6)},
    "TITAN": {3: (-1.8, 1.4)},
}
BASE_PX = {"RELIANCE": 1480, "HDFCBANK": 1010, "ICICIBANK": 1395, "SBIN": 905, "INFY": 1540, "TCS": 3120, "KPITTECH": 1290,
           "TMPV": 410, "MARUTI": 15800, "M&M": 3550, "LT": 3920, "ITC": 418, "HINDUNILVR": 2480, "SUNPHARMA": 1710,
           "BHARTIARTL": 2050, "NTPC": 342, "TITAN": 3660, "ASIANPAINT": 2390, "DIXON": 16800, "POLYCAB": 7450,
           "TRENT": 4720, "PERSISTENT": 6120, "HAL": 4810, "BAJFINANCE": 1035, "DMART": 4290}


def build_prices(ticker: str, sessions: list[date]) -> list[dict]:
    rng = _rng("px", ticker)
    n = len(sessions)
    drift = rng.uniform(-0.0002, 0.0008)
    vol = rng.uniform(0.010, 0.017)
    px = [0.0] * n
    rets = []
    for i in range(n):
        ago = n - 1 - i
        plant = PLANTS.get(ticker, {}).get(ago)
        r = plant[0] / 100 if plant else max(-0.032, min(0.032, rng.gauss(drift, vol)))
        rets.append(r)
    level = BASE_PX.get(ticker, 1000)
    # walk backwards from today's level so the latest close is near BASE_PX
    px[-1] = level
    for i in range(n - 1, 0, -1):
        px[i - 1] = px[i] / (1 + rets[i])
    base_vol = rng.uniform(1.5e6, 9e6) * (1000 / max(level, 100)) ** 0.5
    out = []
    for i, d in enumerate(sessions):
        ago = n - 1 - i
        plant = PLANTS.get(ticker, {}).get(ago)
        vm = plant[1] if plant else math.exp(max(-0.45, min(0.45, rng.gauss(0, 0.22))))
        c = px[i]
        o = px[i - 1] * (1 + rng.uniform(-0.004, 0.004)) if i else c
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        out.append({"date": d, "open": round(o, 2), "high": round(hi, 2), "low": round(lo, 2), "close": round(c, 2), "adj_close": round(c, 2), "volume": round(base_vol * vm)})
    return out


# ------------------------------------------------------------------------------------ filings

def _results_filing(name: str, qe: date, prev: date, ya: date, cur: dict, pr: dict, yy: dict) -> str:
    f = lambda v: f"{v:,.2f}"  # noqa: E731
    rows = [
        ("1 Revenue from operations", "revenue"), ("2 Other income", "other_income"),
    ]
    lines = [BANNER, f"{name.upper()} LIMITED", f"Statement of Unaudited Consolidated Financial Results for the quarter ended {qe:%d %B %Y}",
             "(Rs. in crore)", f"Particulars    Quarter ended {qe:%d.%m.%Y}    {prev:%d.%m.%Y}    {ya:%d.%m.%Y}",
             "                (Unaudited)    (Unaudited)    (Unaudited)"]
    for lbl, k in rows:
        lines.append(f"{lbl}    {f(cur[k])}    {f(pr[k])}    {f(yy[k])}")
    tot = lambda m: m["revenue"] + m["other_income"]  # noqa: E731
    lines.append(f"3 Total income    {f(tot(cur))}    {f(tot(pr))}    {f(tot(yy))}")
    lines.append("4 Expenses")
    lines.append(f"  a) Cost of materials consumed and other operating expenses    {f(cur['expenses'])}    {f(pr['expenses'])}    {f(yy['expenses'])}")
    lines.append(f"  b) Finance costs    {f(cur['interest'])}    {f(pr['interest'])}    {f(yy['interest'])}")
    lines.append(f"  c) Depreciation and amortisation expense    {f(cur['depreciation'])}    {f(pr['depreciation'])}    {f(yy['depreciation'])}")
    te = lambda m: m["expenses"] + m["interest"] + m["depreciation"]  # noqa: E731
    lines.append(f"  Total expenses    {f(te(cur))}    {f(te(pr))}    {f(te(yy))}")
    lines.append(f"5 Profit before exceptional items and tax    {f(cur['pbt'])}    {f(pr['pbt'])}    {f(yy['pbt'])}")
    lines.append(f"6 Exceptional items    0.00    0.00    0.00")
    lines.append(f"7 Profit before tax    {f(cur['pbt'])}    {f(pr['pbt'])}    {f(yy['pbt'])}")
    tx = lambda m: m["pbt"] - m["pat"]  # noqa: E731
    lines.append(f"8 Tax expense    {f(tx(cur))}    {f(tx(pr))}    {f(tx(yy))}")
    lines.append(f"9 Net profit for the period    {f(cur['pat'])}    {f(pr['pat'])}    {f(yy['pat'])}")
    return "Outcome of Board Meeting - approval of unaudited financial results.\f" + "\n".join(lines)


def build_announcements(sess: date, fins: dict, prev_session: date) -> list[dict]:
    d0, d1 = sess, prev_session
    d = lambda day, hh, mm: datetime.combine(day, time(hh, mm))  # noqa: E731
    days = _weekdays_back(sess, 8)
    qe = latest_reported_quarter(sess)

    def res(t):
        qs = fins[t][0]
        cur, pr = qs[-1], qs[-2]
        ya = next(q for q in qs if q["period_end"].year == cur["period_end"].year - 1 and q["period_end"].month == cur["period_end"].month)
        name = dict((x[0], x[1]) for x in ALL)[t]
        return _results_filing(name, cur["period_end"], pr["period_end"], ya["period_end"], cur["metrics"], pr["metrics"], ya["metrics"])

    A = [
        # --- the last 24 hours
        ("DIXON", d(d0, 12, 40), "Outcome of Board Meeting", f"Outcome of Board Meeting - Unaudited Financial Results for the quarter ended {qe:%d %B %Y}", res("DIXON")),
        ("TITAN", d(d0, 16, 20), "Financial Result Updates", f"Unaudited consolidated financial results for the quarter ended {qe:%d %B %Y}", res("TITAN")),
        ("SUNPHARMA", d(d0, 8, 15), "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
         "Resignation of Chief Financial Officer and appointment of new Chief Financial Officer",
         "Pursuant to Regulation 30 of SEBI (LODR) Regulations, 2015, we inform that Mr. Kunal Mehrotra has tendered his resignation as Chief Financial Officer "
         "of the Company to pursue opportunities outside the Company, with effect from close of business hours on 30 November 2026. "
         "The Board of Directors, on the recommendation of the Nomination and Remuneration Committee, has appointed Ms. Ritika Sharan as Chief Financial Officer "
         "and Key Managerial Personnel with effect from 1 December 2026.\n\nBrief profile of Ms. Ritika Sharan:\nMs. Ritika Sharan is a Chartered Accountant with 22 years of experience in "
         "finance, treasury and investor relations. She was most recently Chief Financial Officer of the India business of a multinational generics company, and earlier spent "
         "eleven years in corporate finance roles at a large Indian IT services firm. She holds a bachelor's degree in commerce from the University of Delhi.\n\n"
         "Disclosure of relationships between directors: Ms. Ritika Sharan is not related to any Director of the Company. (Names are fictional - illustrative demo.)"),
        ("KPITTECH", d(d0, 9, 5), "Acquisition", "Acquisition of 100% stake in an automotive software engineering company in Germany",
         "The Company has entered into a definitive agreement to acquire 100% of the share capital of an automotive middleware engineering company headquartered in Munich, "
         "Germany, for a total consideration of up to Rs. 950 crore, payable in cash in two tranches. The target reported revenue of EUR 96 million in CY2025 and employs about 800 engineers. "
         "The acquisition is expected to be completed by 31 March 2027, subject to regulatory approvals."),
        ("LT", d(d0, 10, 15), "Press Release", "L&T bags 'significant' order for a metro rail project",
         "The Heavy Civil Infrastructure business of the Company has secured a significant order (Rs. 2,500 crore to Rs. 5,000 crore as per the Company's classification) "
         "for design and construction of an elevated metro corridor including 14 stations."),
        ("POLYCAB", d(d1, 14, 30), "Updates", "Board approves capex of Rs. 1,200 crore for capacity expansion of wires and cables",
         "The Board approved capital expenditure of Rs. 1,200 crore over FY27-FY28 for brownfield capacity expansion of the wires and cables business at Halol, funded through internal accruals."),
        ("ICICIBANK", d(d0, 11, 0), "Credit Rating", "Credit rating reaffirmed by CRISIL",
         "CRISIL has reaffirmed its rating of CRISIL AAA/Stable on the Bank's long-term debt programme and CRISIL A1+ on certificates of deposit."),
        ("ASIANPAINT", d(d0, 13, 45), "Updates", "Receipt of GST demand order",
         "The Company has received an order from the GST authorities raising a demand of Rs. 118.6 crore including interest and penalty, relating to input tax credit for FY2020-21. "
         "The Company believes it has a strong case on merits and intends to file an appeal. No material impact on financial or other operations is expected."),
        ("TCS", d(d0, 15, 5), "Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of analyst / institutional investor meetings", "Schedule of meetings with investors during the week."),
        ("TCS", d(d0, 15, 9), "Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of analyst / institutional investor meetings", "Schedule of meetings with investors during the week."),
        ("M&M", d(d0, 17, 30), "Board Meeting Intimation", f"Intimation of Board Meeting to consider and approve financial results for the quarter ended {qe:%d %B %Y}", None),
        ("BHARTIARTL", d(d0, 18, 0), "Updates", "Allotment of non-convertible debentures aggregating Rs. 2,000 crore on private placement basis",
         "The Company has allotted 20,000 listed, rated, unsecured, redeemable non-convertible debentures of face value Rs. 10 lakh each aggregating Rs. 2,000 crore."),
        ("ITC", d(d0, 18, 20), "Record Date", "Record date for interim dividend", "Interim dividend of Rs. 7.00 per share; record date fixed as the coming Friday."),
        ("HDFCBANK", d(d0, 18, 40), "ESOP/ESOS/ESPS", "Allotment of equity shares under ESOS", "Allotment of 4,12,300 equity shares pursuant to exercise of stock options."),
        ("INFY", d(d0, 18, 45), "Certificate under SEBI (Depositories and Participants) Regulations, 2018", "Compliance certificate under Regulation 74(5)", None),
        ("RELIANCE", d(d0, 19, 0), "Copy of Newspaper Publication", "Copy of newspaper publication of financial results", None),
        ("MARUTI", d(d0, 19, 10), "Trading Window", "Closure of trading window", None),
        ("NTPC", d(d0, 19, 15), "Updates", "Declaration of commercial operation of 660 MW Unit-2 of a supercritical thermal project",
         "Unit-2 (660 MW) has been declared on commercial operation, taking the group's installed capacity to 82,410 MW."),
        ("TMPV", d(d0, 19, 30), "Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript of the earnings conference call", "Transcript of the earnings call held for the quarter is attached."),
        # --- earlier in the week
        ("ICICIBANK", d(days[-3], 16, 45), "Financial Result Updates", f"Unaudited standalone financial results for the quarter ended {qe:%d %B %Y}", None),
        ("SBIN", d(days[-3], 14, 0), "Updates", "Board approves raising of up to Rs. 20,000 crore through Basel III compliant bonds", "Raising of funds via Basel III compliant AT1 and Tier 2 bonds in FY27."),
        ("HINDUNILVR", d(days[-4], 12, 0), "Press Release", "Launch of new premium skincare range", "New premium skincare range launched across e-commerce and modern trade."),
        ("TITAN", d(days[-4], 17, 0), "Board Meeting Intimation", f"Intimation of Board Meeting to consider financial results for the quarter ended {qe:%d %B %Y}", None),
        ("RELIANCE", d(days[-5], 15, 30), "Analysts/Institutional Investor Meet/Con. Call Updates", "Intimation of participation in an investor conference", None),
        ("SUNPHARMA", d(days[-5], 12, 10), "Updates", "USFDA inspection of a formulation facility concluded with three observations (Form 483)",
         "The USFDA conducted an inspection at one of the Company's formulation facilities and issued a Form 483 with three observations. The Company will respond within 15 business days."),
        ("DIXON", d(days[-6], 18, 0), "Board Meeting Intimation", f"Intimation of Board Meeting to consider results for the quarter ended {qe:%d %B %Y}", None),
        ("M&M", d(days[-6], 10, 0), "Press Release", "Monthly auto sales: total vehicle sales up 17% YoY", "Total vehicle sales of 92,400 units, up 17% year-on-year."),
        ("ASIANPAINT", d(days[-7], 11, 30), "Shareholders meeting", "Notice of postal ballot", None),
        ("ITC", d(days[-7], 16, 0), "Insider Trading", "Disclosure under Regulation 7(2) of SEBI (Prohibition of Insider Trading) Regulations", "Sale of 12,000 shares by a designated person."),
    ]
    out = []
    for t, when, excat, subject, text in A:
        out.append({"ticker": t, "published_at": when, "subject": subject, "exchange_category": excat, "attachment_text": text,
                    "body": None, "attachment_url": None, "source": "demo",
                    "dedupe_key": hashlib.sha256(f"demo|{t}|{subject}|{when:%Y%m%d%H%M}".encode()).hexdigest()})
    return out


# ------------------------------------------------------------------------------------ documents

TX = {
    "DIXON": {
        "industry": "electronics manufacturing services (EMS)",
        "segments": "mobile phones and EMS, consumer electronics (LED TVs), home appliances (washing machines), lighting, and security systems",
        "mix": "mobile and EMS 72%, consumer electronics 16%, home appliances 7%, lighting and others 5%",
        "calls": {
            "Q3 FY26": [
                ("Managing Director", "For FY26 we expect revenue growth of 30% to 35%, led by mobile phones where our new customer programmes ramp up through the fourth quarter."),
                ("Chief Financial Officer", "We expect EBITDA margin for FY26 in the range of 3.9% to 4.1% as the mix shifts towards mobiles, which carry lower margins but very high return on capital."),
                ("Analyst A", "Could you talk about the component ecosystem and backward integration?"),
                ("Managing Director", "We are investing in display module and camera module capacity. Capex for FY26 will be about Rs. 1,000 crore, largely in mobile and display."),
            ],
            "Q4 FY26": [
                ("Managing Director", "FY26 was an exceptional year; revenue grew about 38% and every segment contributed. Looking ahead, for FY27 we are guiding revenue growth of 30% to 35%."),
                ("Chief Financial Officer", "For Q1 FY27 we expect EBITDA margin of 4.0% to 4.2% as display module volumes begin to contribute."),
                ("Analyst B", "Is there any risk from customer concentration in mobiles?"),
                ("Managing Director", "Concentration is a risk we monitor closely; we are adding two new brand customers this year to diversify the order book."),
            ],
            "Q1 FY27": [
                ("Managing Director", "Q1 margins came in below our expectation because the display module line took longer to stabilise. We are raising our FY27 guidance and now expect revenue growth of 35% to 40% for FY27."),
                ("Chief Financial Officer", "For the next quarter we expect revenue growth of at least 30% year-on-year, with the festive season build for televisions and phones."),
                ("Chief Financial Officer", "We expect FY27 EBITDA margin of 3.8% to 4.0%, slightly lower than earlier because of the display start-up costs."),
                ("Analyst A", "What is the working-capital outlook?"),
                ("Chief Financial Officer", "Working-capital days should stay negative to flat; our customers fund a large part of inventory under the EMS model."),
            ],
            "Q2 FY27": [
                ("Managing Director", "Q2 revenue grew 38% year-on-year, our highest quarterly revenue so far. We maintain the FY27 guidance of revenue growth of 35% to 40%."),
                ("Chief Financial Officer", "Over the medium term we aspire to an EBITDA margin of 4.5% as components scale up, but that is a multi-year journey."),
                ("Analyst B", "Any update on the production-linked incentive scheme?"),
                ("Managing Director", "PLI accruals are in line with plan and are recognised as other operating income."),
            ],
        },
    },
    "TITAN": {
        "industry": "jewellery, watches and wearables, and eyecare retail",
        "segments": "jewellery (Tanishq and other brands), watches and wearables, eyecare, and emerging businesses including fragrances and Indian dress wear",
        "mix": "jewellery 88%, watches and wearables 7%, eyecare 2%, emerging businesses and others 3%",
        "calls": {
            "Q3 FY26": [
                ("Managing Director", "The festive quarter was strong. We expect to close FY26 with revenue growth of around 20%, supported by wedding demand and new store additions."),
                ("Chief Financial Officer", "We expect EBITDA margin for FY26 to be in the 11% to 11.5% band despite gold price volatility."),
                ("Analyst A", "How are you managing gold price volatility?"),
                ("Chief Financial Officer", "We continue to use gold metal loans to hedge inventory; these are reflected in borrowings and will rise with inventory."),
            ],
            "Q4 FY26": [
                ("Managing Director", "FY26 revenue grew about 16%, below the 20% we had indicated, as high gold prices dampened buying in the last quarter. For FY27 we are guiding revenue growth of 18% to 20%."),
                ("Chief Financial Officer", "For Q1 FY27 we expect revenue growth of 14% to 16% given a high base and fewer wedding dates."),
                ("Chief Financial Officer", "We are targeting FY27 EBITDA margin of 11% to 11.5%."),
                ("Analyst B", "Inventory days have gone up. Is that a concern?"),
                ("Chief Financial Officer", "Inventory went up because of store additions and higher gold prices; we expect it to normalise over the next two to three quarters."),
            ],
            "Q1 FY27": [
                ("Managing Director", "Q1 was softer than planned. Given gold price trends we now expect FY27 revenue growth of 15% to 17%, lower than our earlier guidance."),
                ("Chief Financial Officer", "We maintain the FY27 EBITDA margin guidance of 11% to 11.5%, though Q2 will be seasonally weaker."),
                ("Analyst A", "What is the store addition plan?"),
                ("Managing Director", "We plan to add around 60 jewellery stores this year, mostly in smaller towns."),
            ],
            "Q2 FY27": [
                ("Managing Director", "Q2 revenue grew about 9% year-on-year. Studded jewellery remained weak while gold coins grew."),
                ("Chief Financial Officer", "Margins were impacted by higher promotional spend; we expect the second half to show double-digit revenue growth with margins recovering."),
                ("Analyst B", "Do you still stand by the margin guidance?"),
                ("Chief Financial Officer", "We will review the margin guidance after the festive quarter; it is too early to change it."),
            ],
        },
    },
    "TRENT": {
        "industry": "apparel and lifestyle retail",
        "segments": "Westside (lifestyle), Zudio (value fashion), Star (food and grocery, joint venture) and other formats",
        "mix": "Zudio 58%, Westside 37%, others 5% (standalone)",
        "calls": {
            "Q3 FY26": [
                ("Managing Director", "We expect FY26 revenue growth of upwards of 25% as Zudio store additions continue at a fast pace."),
                ("Chief Financial Officer", "We expect FY26 EBITDA margin of 16% to 17% on a pre-Ind AS 116 basis."),
                ("Analyst A", "How many stores will you add?"),
                ("Managing Director", "We plan to add about 200 Zudio stores in FY26 and enter two new international markets."),
            ],
            "Q4 FY26": [
                ("Managing Director", "FY26 revenue grew about 22%. Like-for-like growth moderated in the second half. For FY27 we expect revenue growth of around 20%."),
                ("Chief Financial Officer", "For Q1 FY27 we expect revenue growth of at least 15% year-on-year."),
                ("Analyst B", "Any change to capex plans?"),
                ("Chief Financial Officer", "Capex for FY27 will be about Rs. 1,500 crore, funded through internal accruals."),
            ],
            "Q1 FY27": [
                ("Managing Director", "Q1 revenue grew about 17% year-on-year. We maintain our FY27 guidance of revenue growth of around 20%."),
                ("Chief Financial Officer", "We expect FY27 EBITDA margin of 17% to 18%."),
                ("Analyst A", "How is competition from quick-commerce fashion?"),
                ("Managing Director", "We see it as additive to category growth; our stores remain the primary channel."),
            ],
            "Q2 FY27": [
                ("Managing Director", "Q2 revenue grew about 18.5% year-on-year with Zudio crossing 900 stores."),
                ("Chief Financial Officer", "We expect the next quarter to deliver revenue growth of 18% to 20% with the festive season."),
                ("Analyst B", "Will margins sustain?"),
                ("Chief Financial Officer", "We are confident of sustaining margins in the 17% to 18% range over the medium term."),
            ],
        },
    },
}


def _write_pdf(path: Path, title: str, sections: list[tuple[str | None, list[str]]]) -> None:
    import fitz

    doc = fitz.open()
    page, y = None, 0.0
    W, H, M = 595, 842, 48

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=W, height=H)
        page.insert_text((M, 28), BANNER, fontsize=7, color=(0.7, 0.1, 0.1))
        page.insert_text((M, 40), title, fontsize=7, color=(0.4, 0.4, 0.4))
        y = 60

    def put(text, size=9.5, bold=False):
        nonlocal y
        for _ in range(2):
            rect = fitz.Rect(M, y, W - M, H - M)
            rc = page.insert_textbox(rect, text, fontsize=size, fontname="hebo" if bold else "helv")
            if rc >= 0:
                y += (rect.height - rc) + 8
                return
            new_page()

    new_page()
    for head, paras in sections:
        if head == "__PAGE__":
            new_page()
            continue
        if head:
            put(head, 12, True)
        for p in paras:
            put(p)
    doc.save(path)
    doc.close()


def _ar_sections(t: str, name: str, ann: list[dict]) -> list[tuple[str | None, list[str]]]:
    info = TX[t]
    a = ann[-1]["metrics"]
    p = ann[-2]["metrics"]
    g = (a["revenue"] / p["revenue"] - 1) * 100
    em = a["ebitda"] / a["revenue"] * 100
    cl = round(a["revenue"] * 0.011, 1)
    rpt = round(a["revenue"] * 0.004, 1)
    sec = [
        (f"{name} - Annual Report FY26", ["Integrated Annual Report for the financial year ended 31 March 2026."]),
        ("Business Overview", [
            f"{name} operates in {info['industry']}. The Company's businesses comprise {info['segments']}.",
            f"Revenue mix for FY26 by segment: {info['mix']}.",
            "Our strategy is to grow market share through new customers and formats, deepen backward integration, and keep the balance sheet conservative.",
        ]),
        ("__PAGE__", []),
        ("Management Discussion and Analysis", [
            f"Financial performance: Consolidated revenue from operations for FY26 was Rs. {a['revenue']:,.0f} crore compared with Rs. {p['revenue']:,.0f} crore in FY25, growth of {g:.1f}%. "
            f"EBITDA was Rs. {a['ebitda']:,.0f} crore, an EBITDA margin of {em:.1f}%. Profit after tax was Rs. {a['pat']:,.0f} crore.",
            f"Borrowings at the end of FY26 stood at Rs. {a['borrowings']:,.0f} crore and net worth at Rs. {a['net_worth']:,.0f} crore.",
            f"Cash flow from operating activities was Rs. {a['cfo']:,.0f} crore during the year.",
        ]),
        ("Outlook", [
            "The Company remains optimistic about demand in the coming year, supported by new customers and capacity additions. "
            "Management will continue to focus on execution, cost discipline and working capital.",
        ]),
        ("Risks and Concerns", [
            "Key risks include customer concentration, volatility in input and commodity prices, changes in government incentive schemes, competition, "
            "foreign exchange movements and execution risk on new capacity. "
            + ("Gold price volatility affects demand and inventory value; gold metal loans used for hedging are part of borrowings." if t == "TITAN" else ""),
        ]),
        ("__PAGE__", []),
        ("Key Financial Ratios", [
            f"Debtor days {a.get('debtor_days')} {p.get('debtor_days')} Inventory days {a.get('inventory_days')} {p.get('inventory_days')} "
            f"ROE % {a.get('roe')} {p.get('roe')} ROCE % {a.get('roce')} {p.get('roce')} Debt equity {a['borrowings']/a['net_worth']:.2f} {p['borrowings']/p['net_worth']:.2f}",
        ]),
        ("Notes to the Consolidated Financial Statements", [
            f"Contingent liabilities: Claims against the Company not acknowledged as debts amount to Rs. {cl:,.1f} crore, primarily indirect tax and income tax matters under appeal. "
            "Corporate guarantees given on behalf of subsidiaries are disclosed separately. Management believes the outcome will not have a material adverse effect.",
            f"Related party transactions: Transactions with related parties during the year aggregated Rs. {rpt:,.1f} crore, principally purchase of goods and services from joint ventures "
            "and associates, conducted at arm's length and in the ordinary course of business. All material related party transactions were approved by the Audit Committee.",
        ]),
        ("__PAGE__", []),
        ("Independent Auditor's Report", [
            "Opinion: In our opinion and to the best of our information and according to the explanations given to us, the consolidated financial statements give a true and fair view "
            "in conformity with Indian Accounting Standards. We have issued an unmodified opinion.",
            "Key audit matters: revenue recognition and inventory valuation." + (" Emphasis of matter: we draw attention to the note on gold metal loans and inventory valuation; our opinion is not modified in respect of this matter." if t == "TITAN" else ""),
        ]),
        ("Report on Corporate Governance", [
            "Shareholding of promoters: As on 31 March 2026, no shares held by the promoter and promoter group were pledged or otherwise encumbered (pledged shares: Nil).",
        ]),
    ]
    return sec


def _call_date(label: str) -> date:
    from .research.periods import quarter_end

    qe = quarter_end(label)
    return qe + timedelta(days=33)


def build_documents(s: Session, fins: dict) -> list[Document]:
    from .research.ingest import index_pdf
    from .research.periods import quarter_end

    out_dir = settings.docs_dir / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    names = dict((x[0], x[1]) for x in ALL)
    docs = []
    for t, info in TX.items():
        name = names[t]
        # Annual report
        ar_path = out_dir / f"{t}_AR_FY26.pdf"
        _write_pdf(ar_path, f"{name} Annual Report FY26", _ar_sections(t, name, fins[t][1]))
        docs.append(Document(ticker=t, doc_type="annual_report", title=f"{name} Annual Report FY26 (illustrative)", period_label="FY26",
                             period_end=date(2026, 3, 31), url=f"demo://{t}/annual-report-FY26", local_path=str(ar_path), source="demo"))
        # Transcripts: only calls that have already happened relative to the dataset date
        for label, turns in info["calls"].items():
            qe = quarter_end(label)
            if qe is None or qe > fins[t][0][-1]["period_end"]:
                continue
            p = out_dir / f"{t}_concall_{label.replace(' ', '_')}.pdf"
            paras = [f"Moderator: Ladies and gentlemen, welcome to the {name} earnings conference call for {label}."]
            paras += [f"{sp}: {txt}" for sp, txt in turns]
            paras.append("Moderator: That concludes the conference. Thank you for joining.")
            _write_pdf(p, f"{name} {label} earnings call transcript", [(f"{name} - {label} Earnings Conference Call", paras)])
            docs.append(Document(ticker=t, doc_type="transcript", title=f"{name} {label} earnings call transcript (illustrative)", period_label=label,
                                 period_end=qe, url=f"demo://{t}/concall-{label.replace(' ', '-')}", local_path=str(p), source="demo"))
    for d in docs:
        s.add(d)
        s.flush()
        index_pdf(s, d)
    s.flush()
    return docs


# ------------------------------------------------------------------------------------ main

DEMO_TODAY = date(2026, 11, 3)  # frozen so the planted scenarios line up with fiscal quarters


def reset(s: Session, today: date | None = None) -> dict:
    """Wipe and rebuild the illustrative dataset. Idempotent; used by `python -m finn.seed` and POST /api/system/demo-reset."""
    for M in (AlertEvent, AlertRule, Guidance, Chunk, Document, Announcement, Price, FinancialPeriod, Holding, ResearchLog, Company, Meta):
        s.execute(delete(M))
    # LLM cache is kept on purpose: it is content-addressed and saves free-tier quota.
    s.commit()
    sess = last_session(today or DEMO_TODAY)
    prev_sess = _weekdays_back(sess, 2)[0]
    qe = latest_reported_quarter(sess)
    qends = quarter_ends(qe, 10)
    sessions = _weekdays_back(sess, 270)

    fins = {}
    for t, name, sector, fin in ALL:
        s.add(Company(ticker=t, name=name, sector=sector, is_financial=fin, source="demo",
                      about=f"{name} — {sector}. (Profile from the seed universe; illustrative demo mode.)"))
        q, a = build_financials(t, fin, qends)
        fins[t] = (q, a)
        for row in q:
            s.add(FinancialPeriod(ticker=t, period_type="Q", period_end=row["period_end"], label=row["label"], basis="consolidated",
                                  metrics=row["metrics"], source="demo", source_url=None))
        for row in a:
            s.add(FinancialPeriod(ticker=t, period_type="Y", period_end=row["period_end"], label=row["label"], basis="consolidated",
                                  metrics=row["metrics"], source="demo", source_url=None))
        for p in build_prices(t, sessions):
            s.add(Price(ticker=t, source="demo", **p))
    s.flush()
    for t, *_ in PORTFOLIO:
        s.add(Holding(ticker=t))
    for a in build_announcements(sess, fins, prev_sess):
        s.add(Announcement(**a))
    s.flush()
    build_documents(s, fins)
    s.add(Meta(key="data_mode", value={"mode": "demo", "as_of": sess.isoformat(), "generated_at": datetime.utcnow().isoformat(),
                                       "note": "Illustrative synthetic data. Run `python -m finn.refresh` for live NSE/Yahoo/screener data."}))
    s.commit()

    from .research import guidance
    from .services import alerts, signals

    alerts.seed_defaults(s)
    signals.process(s, force=True)
    alerts.evaluate(s)
    for t in TX:
        guidance.extract(s, t)
    return {"as_of": sess.isoformat(), "companies": len(ALL), "portfolio": len(PORTFOLIO), "adhoc": len(ADHOC)}
