"""Clearly labelled ILLUSTRATIVE demo dataset, used when live sources are unreachable.

Every row has source="demo"; every generated PDF page carries a watermark; people are fictional.
Frozen at DEMO_TODAY so the brief, alerts and guidance grading are reproducible.
"""
from __future__ import annotations

import hashlib
import math
import random
import shutil
import textwrap
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import settings
from .db import set_meta
from .models import (AlertEvent, AlertRule, Announcement, Chunk, Company, Document, FinancialPeriod, Guidance, Holding,
                     Meta, Price, ResearchLog)
from .research import guidance as G, ingest
from .research.periods import fy_label, month_end, month_label, quarter_label
from .services import alerts, signals
from .services.numbers import indian_group
from .universe import PORTFOLIO, RESEARCH

DEMO_TODAY = date(2026, 11, 3)
WATERMARK = ingest.WATERMARK
TAX = 0.252
N_SESSIONS = 270
QUARTER_ENDS = [month_end(2024 + (6 + 3 * i - 1) // 12, (6 + 3 * i - 1) % 12 + 1) for i in range(10)]  # Jun-24..Sep-26
SEASON = {6: 0.96, 9: 1.00, 12: 1.06, 3: 0.98}

# (revenue ₹ cr latest quarter, YoY growth, EBITDA margin %, D/E, CFO/PAT, debtor days, inventory days)
PROFILES: dict[str, tuple] = {
    "RELIANCE": (258000, 0.07, 17.5, 0.42, 1.25, 12, 70), "HDFCBANK": (86000, 0.11), "ICICIBANK": (49000, 0.12),
    "SBIN": (121000, 0.09), "INFY": (44500, 0.06, 24.5, 0.05, 1.05, 68, 0), "TCS": (66500, 0.05, 27, 0.04, 1.02, 75, 0),
    "KPITTECH": (1620, 0.14, 21, 0.10, 0.95, 62, 0), "TMPV": (98000, -0.03, 11, 0.65, 1.40, 18, 55),
    "MARUTI": (40200, 0.09, 12, 0.01, 1.10, 9, 14), "M&M": (45800, 0.16, 14, 0.95, 0.85, 22, 45),
    "LT": (67500, 0.12, 10.5, 1.10, 0.90, 95, 12), "ITC": (21200, 0.07, 35, 0, 1.05, 14, 160),
    "HINDUNILVR": (16100, 0.03, 23, 0, 1.10, 12, 33), "SUNPHARMA": (14100, 0.09, 28, 0.02, 0.95, 95, 210),
    "BHARTIARTL": (52500, 0.18, 55, 1.25, 1.80, 25, 0), "NTPC": (45200, 0.04, 28, 1.45, 1.70, 55, 40),
    "ASIANPAINT": (8600, -0.01, 18.5, 0.08, 1.15, 34, 105), "POLYCAB": (6700, 0.22, 13.5, 0.02, 0.75, 42, 85),
    "PERSISTENT": (3750, 0.22, 17, 0.05, 1.0, 70, 0), "HAL": (7600, 0.11, 28, 0, 1.2, 80, 300),
    "BAJFINANCE": (19500, 0.24), "DMART": (16800, 0.15, 8, 0.05, 0.9, 1, 30),
}

STORY = {
    "DIXON": {"rev": [6580, 11534, 10454, 10293, 12836, 14855, 13200, 12739, 15900, 20500],
              "margin": [3.9, 3.7, 3.9, 4.1, 4.0, 3.7, 4.1, 4.2, 3.7, 4.0],
              "de": [0.12, 0.10, 0.15, 0.14, 0.11], "cfo_pat": 1.12, "debtor": [48, 45, 42, 39, 36],
              "inventory": [28, 27, 25, 24, 22], "payable": [62, 60, 60, 58, 57]},
    "TITAN": {"rev": [13266, 14656, 17740, 14916, 15520, 16830, 20560, 17370, 17100, 18300],
              "margin": [11.0, 10.9, 11.6, 11.1, 11.2, 10.6, 11.9, 11.0, 10.9, 10.2],
              "de": [0.55, 0.62, 0.78, 0.95, 1.18], "cfo_pat": 0.42, "debtor": [6, 5, 7, 6, 6],
              "inventory": [205, 210, 222, 236, 262], "payable": [20, 20, 20, 20, 20], "cfi_mult": 1.6},
    "TRENT": {"rev": [4104, 4157, 4657, 4217, 4883, 5105, 5800, 5145, 5700, 6050],
              "margin": [16.0, 16.4, 17.2, 16.9, 17.1, 17.4, 18.3, 17.6, 17.0, 17.8],
              "de": [0.35, 0.31, 0.27, 0.22, 0.18], "cfo_pat": 0.98, "debtor": [2, 2, 2, 2, 2],
              "inventory": [74, 72, 70, 69, 67], "payable": [40, 41, 40, 42, 41]},
}

PRICE_BASE = {"RELIANCE": 1480, "HDFCBANK": 1010, "ICICIBANK": 1395, "SBIN": 905, "INFY": 1540, "TCS": 3120,
              "KPITTECH": 1290, "TMPV": 410, "MARUTI": 15800, "M&M": 3550, "LT": 3920, "ITC": 418, "HINDUNILVR": 2480,
              "SUNPHARMA": 1710, "BHARTIARTL": 2050, "NTPC": 342, "TITAN": 3660, "ASIANPAINT": 2390, "DIXON": 16800,
              "POLYCAB": 7450, "TRENT": 4720, "PERSISTENT": 6120, "HAL": 4810, "BAJFINANCE": 1035, "DMART": 4290}
PLANTED = {"DIXON": (0, 6.8, 3.4), "SUNPHARMA": (0, -4.6, 2.3), "KPITTECH": (0, 3.1, 2.6), "POLYCAB": (1, 5.1, 2.1),
           "ASIANPAINT": (6, -4.3, 1.9), "RELIANCE": (4, 1.2, 2.2), "LT": (0, 2.4, 1.6), "TITAN": (3, -1.8, 1.4)}

ABOUT = {
    "RELIANCE": "Conglomerate spanning oil-to-chemicals, retail and digital services.",
    "HDFCBANK": "Private-sector bank with retail, wholesale and treasury businesses.",
    "ICICIBANK": "Private-sector bank with retail and corporate lending.", "SBIN": "India's largest public-sector bank.",
    "INFY": "IT services and consulting.", "TCS": "IT services, consulting and business solutions.",
    "KPITTECH": "Automotive software and engineering services.", "TMPV": "Passenger and electric vehicles.",
    "MARUTI": "Passenger cars.", "M&M": "Utility vehicles, tractors and farm equipment.",
    "LT": "Engineering, procurement and construction.", "ITC": "Cigarettes, FMCG, hotels, paperboards and agri.",
    "HINDUNILVR": "Home and personal care, foods.", "SUNPHARMA": "Specialty and generic pharmaceuticals.",
    "BHARTIARTL": "Mobile, broadband and enterprise telecom services.", "NTPC": "Thermal and renewable power generation.",
    "TITAN": "Jewellery, watches and eyecare retail.", "ASIANPAINT": "Decorative and industrial paints.",
    "DIXON": "Electronics manufacturing services: mobiles, consumer electronics, appliances, lighting.",
    "POLYCAB": "Wires, cables and fast-moving electrical goods.", "TRENT": "Fashion retail (Westside, Zudio).",
    "PERSISTENT": "Software product engineering services.", "HAL": "Aircraft, helicopters and aero-engines for defence.",
    "BAJFINANCE": "Consumer and SME lending NBFC.", "DMART": "Value-retail supermarket chain.",
}


def _rng(*key) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:12], 16))


def sessions() -> list[date]:
    out, d = [], DEMO_TODAY - timedelta(days=1)
    while len(out) < N_SESSIONS:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def weekday_back(n: int) -> date:
    return sessions()[-1 - n]


# ---------------------------------------------------------------- financials
def _quarter_rows(ticker: str, is_fin: bool) -> list[dict]:
    r = _rng("fin", ticker)
    if ticker in STORY:
        revs, margins = STORY[ticker]["rev"], STORY[ticker]["margin"]
    else:
        p = PROFILES[ticker]
        rev0, g = p[0], p[1]
        margin = p[2] if len(p) > 2 else None
        revs, margins = [], []
        for i, qe in enumerate(QUARTER_ENDS):
            k = 9 - i
            trend = rev0 / (1 + g) ** (k / 4)
            noise = 1.0 if k == 0 else 1 + r.uniform(-0.025, 0.025)
            revs.append(round(trend * SEASON[qe.month] / SEASON[9] * noise, 0))
            margins.append(None if margin is None else margin + (0 if k == 0 else r.uniform(-0.6, 0.6)))
    oi_r, dep_r, int_r = r.uniform(0.002, 0.008), r.uniform(0.12, 0.26), r.uniform(0.02, 0.10)
    bank_pbt = r.uniform(0.24, 0.30)
    rows = []
    for i, qe in enumerate(QUARTER_ENDS):
        rev = float(revs[i])
        j = lambda: 1 + r.uniform(-0.03, 0.03)  # noqa: E731
        if is_fin:
            pbt = rev * bank_pbt * j()
            m = {"revenue": rev, "ebitda": None, "other_income": None, "interest": None, "depreciation": None,
                 "pbt": pbt, "expenses": rev - pbt}
        else:
            ebitda = rev * margins[i] / 100
            oi, dep, intr = rev * oi_r * j(), ebitda * dep_r * j(), ebitda * int_r * j()
            pbt = ebitda + oi - dep - intr
            m = {"revenue": rev, "ebitda": ebitda, "other_income": oi, "interest": intr, "depreciation": dep, "pbt": pbt,
                 "expenses": rev - ebitda}
        m["tax_pct"] = TAX * 100
        m["pat"] = m["pbt"] * (1 - TAX)
        m["exceptional"] = 0.0
        m["eps"] = None
        rows.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()})
    return rows


def _annual_rows(ticker: str, q: list[dict], is_fin: bool) -> list[tuple[date, dict]]:
    r = _rng("annual", ticker)
    fys = []
    for fe in (date(2025, 3, 31), date(2026, 3, 31)):
        idx = [i for i, qe in enumerate(QUARTER_ENDS) if fe - timedelta(days=360) < qe <= fe]
        if len(idx) == 4:
            tot = {}
            for k in ("revenue", "ebitda", "other_income", "interest", "depreciation", "pbt", "pat", "expenses",
                      "exceptional"):
                vals = [q[i][k] for i in idx]
                tot[k] = None if any(v is None for v in vals) else round(sum(vals), 2)
            fys.append((fe, tot))
    g = (fys[-1][1]["revenue"] / fys[-2][1]["revenue"] - 1) if len(fys) == 2 else 0.1
    g = max(min(g, 0.25), -0.05) if ticker not in STORY else g * 0.8
    while len(fys) < 5:
        fe0, t0 = fys[0]
        prev = {k: (None if v is None else round(v / (1 + g) * (1 + r.uniform(-0.02, 0.02)), 2)) for k, v in t0.items()}
        fys.insert(0, (date(fe0.year - 1, 3, 31), prev))
    story = STORY.get(ticker)
    p = PROFILES.get(ticker, ())
    nw = fys[-1][1]["pat"] * r.uniform(5.5, 7.5)
    out = []
    for i, (fe, m) in enumerate(fys):
        k = len(fys) - 1 - i
        m = dict(m)
        m["tax_pct"] = TAX * 100
        m["eps"] = None
        net_worth = nw / (1.08 ** k)
        m["net_worth"] = round(net_worth, 2)
        m["roe"] = round(m["pat"] / net_worth * 100, 1)
        if is_fin:
            m.update(borrowings=None, cfo=None, cfi=None, fcf=None, debtor_days=None, inventory_days=None,
                     payable_days=None, ccc=None, roce=None)
        else:
            de = story["de"][i] if story else max(0.0, p[3] * (1 + r.uniform(-0.04, 0.04)))
            conv = story["cfo_pat"] if story else p[4]
            m["borrowings"] = round(net_worth * de, 2)
            cfo = m["pat"] * conv * (1 + r.uniform(-0.15, 0.15))
            cfi = -abs(cfo) * r.uniform(0.45, 0.85) * (story.get("cfi_mult", 1.0) if story else 1.0)
            m["cfo"], m["cfi"] = round(cfo, 2), round(cfi, 2)
            m["fcf"] = round(cfo + cfi, 2)
            if story:
                dd, inv, pay = story["debtor"][i], story["inventory"][i], story["payable"][i]
            else:
                dd = round(p[5] + r.uniform(-2, 2), 0)
                inv = round(p[6] + r.uniform(-3, 3), 0) if p[6] else 0
                pay = round(45 + r.uniform(-3, 3), 0)
            m.update(debtor_days=dd, inventory_days=inv, payable_days=pay, ccc=dd + inv - pay)
            m["roce"] = round((m["pbt"] + (m["interest"] or 0)) / (net_worth + m["borrowings"]) * 100, 1)
        out.append((fe, m))
    return out


# ---------------------------------------------------------------- prices
PRICE_SALT = "px78"  # seed salt for the synthetic walks (chosen so the planted scenario reads as designed)


def _prices(ticker: str) -> list[dict]:
    r = _rng(PRICE_SALT, ticker)
    days = sessions()
    n = len(days)
    vol = r.uniform(1.0, 1.7)
    rets = [max(-3.2, min(3.2, r.gauss(0.03, vol))) for _ in range(n)]
    base_v = 10 ** r.uniform(5.6, 7.0)
    vols = [base_v * math.exp(max(-0.45, min(0.45, r.gauss(0, 0.22)))) for _ in range(n)]
    plant = PLANTED.get(ticker)
    if plant:
        ago, ret, vm = plant
        i = n - 1 - ago
        rets[i] = ret
        vols[i] = vm * (sum(vols[i - 20:i]) / 20)
    closes = [0.0] * n
    closes[-1] = PRICE_BASE[ticker]
    for i in range(n - 1, 0, -1):
        closes[i - 1] = closes[i] / (1 + rets[i] / 100)
    rows = []
    for i, d in enumerate(days):
        c = closes[i]
        o = (closes[i - 1] if i else c) * (1 + r.uniform(-0.004, 0.004))
        hi = max(o, c) * (1 + r.uniform(0, 0.006))
        lo = min(o, c) * (1 - r.uniform(0, 0.006))
        rows.append({"ticker": ticker, "date": d, "open": round(o, 2), "high": round(hi, 2), "low": round(lo, 2),
                     "close": round(c, 2), "adj_close": round(c, 2), "volume": float(round(vols[i])), "source": "demo"})
    return rows


# ---------------------------------------------------------------- results filing text
def _f2(x: float) -> str:
    neg = x < 0
    whole, frac = f"{abs(x):.2f}".split(".")
    s = f"{indian_group(int(whole))}.{frac}"
    return f"({s})" if neg else s


def results_attachment(company: str, q: list[dict], idx: int) -> str:
    cur, prev, ya = q[idx], q[idx - 1], q[idx - 4]
    qe = QUARTER_ENDS[idx]
    p1 = (f"Outcome of Board Meeting\n\n{company}\n\nThe Board of Directors at its meeting held today approved the "
          f"unaudited consolidated and standalone financial results for the quarter ended {qe:%d %B %Y}. The results "
          f"and the limited review report of the statutory auditors are enclosed.\n\n{WATERMARK}")

    def row(no, label, key=None, vals=None):
        vs = vals or [m[key] for m in (cur, prev, ya)]
        return f"{no} {label} " + " ".join(_f2(v) for v in vs)

    exp_total = [m["revenue"] + m["other_income"] - (m["pbt"]) for m in (cur, prev, ya)]
    other_exp = [exp_total[i] - m["interest"] - m["depreciation"] for i, m in enumerate((cur, prev, ya))]
    tax = [m["pbt"] - m["pat"] for m in (cur, prev, ya)]
    p2 = "\n".join([
        f"{company}",
        f"Statement of Unaudited Consolidated Financial Results for the quarter ended {qe:%d %B %Y}",
        "(Rs. in crore)",
        f"Particulars | Quarter ended {qe:%d.%m.%Y} | Preceding quarter | Corresponding quarter of previous year",
        row("1", "Revenue from operations", "revenue"),
        row("2", "Other income", "other_income"),
        row("3", "Total income", vals=[m["revenue"] + m["other_income"] for m in (cur, prev, ya)]),
        "4 Expenses",
        row("a)", "Cost of materials and other expenses", vals=other_exp),
        row("b)", "Finance costs", "interest"),
        row("c)", "Depreciation and amortisation expense", "depreciation"),
        row("", "Total expenses", vals=exp_total),
        row("5", "Profit before exceptional items and tax", "pbt"),
        row("6", "Exceptional items", vals=[0.0, 0.0, 0.0]),
        row("7", "Profit before tax", "pbt"),
        row("8", "Tax expense", vals=tax),
        row("9", "Net profit for the period", "pat"),
        WATERMARK,
    ])
    return p1 + "\f" + p2


# ---------------------------------------------------------------- announcements
def _at(n: int, hh: int, mm: int) -> datetime:
    return datetime.combine(weekday_back(n), time(hh, mm))


def announcements(fin: dict[str, list[dict]]) -> list[dict]:
    rev = lambda t, i=9: fin[t][i]["revenue"]  # noqa: E731,F841
    A = []

    def add(n, hh, mm, t, label, subject, body="", attachment=None):
        A.append({"ticker": t, "published_at": _at(n, hh, mm), "exchange_category": label, "subject": subject,
                  "body": body or subject, "attachment_text": attachment,
                  "attachment_url": None, "source": "demo"})

    add(0, 12, 40, "DIXON", "Outcome of Board Meeting",
        "Outcome of Board Meeting - Unaudited financial results for the quarter ended 30 September 2026",
        "The Board approved the unaudited consolidated financial results for the quarter ended 30 September 2026.",
        results_attachment("Dixon Technologies (India) Ltd", fin["DIXON"], 9))
    add(0, 16, 20, "TITAN", "Financial Result Updates",
        "Unaudited financial results for the quarter ended 30 September 2026",
        "Unaudited consolidated financial results for the quarter ended 30 September 2026 are enclosed.",
        results_attachment("Titan Company Ltd", fin["TITAN"], 9))
    add(0, 8, 15, "SUNPHARMA", "Change in Directors/Key Managerial Personnel/Auditor/Compliance Officer/Share Transfer Agent",
        "Change in Key Managerial Personnel - resignation of Chief Financial Officer and appointment of new CFO",
        "Pursuant to Regulation 30 of the SEBI (LODR) Regulations, 2015, we inform you that Mr. Kunal Mehrotra has "
        "tendered his resignation as Chief Financial Officer of the Company to pursue opportunities outside the Company, "
        "w.e.f. close of business hours on 30 November 2026. The Board of Directors, on the recommendation of the "
        "Nomination and Remuneration Committee, has approved the appointment of Ms. Ritika Sharan as Chief Financial "
        "Officer and Key Managerial Personnel of the Company w.e.f. 1 December 2026.\n\n"
        "Brief profile of Ms. Ritika Sharan: Ms. Sharan is a Chartered Accountant with 22 years of experience in finance, "
        "treasury and investor relations. She was previously CFO of the India business of a multinational generics "
        "company, and before that spent 11 years at a large Indian IT services firm. She holds a B.Com degree from "
        "Delhi University.\n\n(Names are fictional - illustrative demo.)")
    add(0, 9, 5, "KPITTECH", "Acquisition",
        "Acquisition of 100% stake in a Munich-based automotive middleware company",
        "KPIT Technologies Ltd has signed a definitive agreement to acquire 100% of a Munich-based automotive middleware "
        "company for a total consideration of up to Rs. 950 crore in cash, payable in two tranches. The target reported "
        "revenue of EUR 96 million in CY2025 and has about 800 engineers.")
    add(0, 10, 15, "LT", "Press Release",
        "L&T secures 'significant' order for an elevated metro rail project",
        "Larsen & Toubro's Heavy Civil Infrastructure business has secured a 'significant' order (Rs. 2,500 crore to "
        "Rs. 5,000 crore as per L&T's classification) to build an elevated metro corridor with 14 stations.")
    add(1, 14, 30, "POLYCAB", "Updates",
        "Board approves capex of Rs. 1,200 crore for brownfield capacity expansion at Halol",
        "The Board approved capital expenditure of Rs. 1,200 crore over FY27-FY28 for brownfield capacity expansion of "
        "the wires and cables plant at Halol, to be funded through internal accruals.")
    add(0, 11, 0, "ICICIBANK", "Credit Rating",
        "CRISIL reaffirms AAA/Stable rating on long-term debt instruments",
        "CRISIL Ratings has reaffirmed its AAA/Stable rating on the Bank's long-term debt instruments.")
    add(0, 13, 45, "ASIANPAINT", "Updates",
        "Receipt of GST demand order of Rs. 118.6 crore",
        "The Company has received a GST demand order of Rs. 118.6 crore including interest and penalty. The Company "
        "believes it has a strong case on merits and will file an appeal.")
    add(0, 15, 5, "TCS", "Analysts/Institutional Investor Meet/Con. Call Updates",
        "Schedule of analyst / institutional investor meetings",
        "Schedule of analyst / institutional investor meetings to be held during the week.")
    add(0, 15, 9, "TCS", "Analysts/Institutional Investor Meet/Con. Call Updates",
        "Schedule of analyst / institutional investor meetings",
        "Schedule of analyst / institutional investor meetings to be held during the week.")
    add(0, 17, 30, "M&M", "Board Meeting Intimation",
        "Intimation of Board Meeting to consider and approve the unaudited financial results for the quarter ended "
        "30 September 2026")
    add(0, 18, 0, "BHARTIARTL", "Updates",
        "Allotment of Non-Convertible Debentures aggregating Rs. 2,000 crore",
        "The Company has allotted listed, unsecured, rated non-convertible debentures aggregating Rs. 2,000 crore on a "
        "private placement basis.")
    add(0, 18, 20, "ITC", "Record Date", "Record date for interim dividend of Rs. 7 per share",
        "The Board has fixed the record date for the interim dividend of Rs. 7 per ordinary share.")
    add(0, 18, 40, "HDFCBANK", "ESOP/ESOS/ESPS", "Allotment of equity shares under ESOS")
    add(0, 18, 45, "INFY", "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
        "Certificate under Regulation 74(5) of SEBI (DP) Regulations, 2018")
    add(0, 19, 0, "RELIANCE", "Copy of Newspaper Publication", "Copy of newspaper publication")
    add(0, 19, 10, "MARUTI", "Trading Window", "Closure of trading window")
    add(0, 19, 15, "NTPC", "Updates",
        "Declaration of commercial operation of 660 MW Unit-2",
        "Unit-2 (660 MW) of the station has been declared on commercial operation from 00:00 hours today.")
    add(0, 19, 30, "TMPV", "Analysts/Institutional Investor Meet/Con. Call Updates",
        "Transcript of the earnings conference call for Q2 FY27",
        "Transcript of the earnings conference call held to discuss the results for the quarter ended 30 September 2026.")
    add(3, 16, 45, "ICICIBANK", "Financial Result Updates",
        "Standalone unaudited financial results for the quarter ended 30 September 2026",
        "Standalone unaudited financial results for the quarter ended 30 September 2026.")
    add(3, 14, 0, "SBIN", "Updates", "Raising of funds through Basel III compliant bonds of up to Rs. 20,000 crore",
        "The Board approved raising of funds through Basel III compliant AT1 and Tier 2 bonds of up to Rs. 20,000 crore.")
    add(4, 12, 0, "HINDUNILVR", "Press Release", "Press release - launch of a premium skincare range",
        "Hindustan Unilever announced the launch of a premium skincare range across modern trade and e-commerce.")
    add(4, 17, 0, "TITAN", "Board Meeting Intimation",
        "Intimation of Board Meeting to consider financial results for the quarter ended 30 September 2026")
    add(5, 15, 30, "RELIANCE", "Analysts/Institutional Investor Meet/Con. Call Updates",
        "Intimation of participation in an investor conference")
    add(5, 12, 10, "SUNPHARMA", "Updates",
        "USFDA inspection at the Halol facility concludes with Form 483 with 3 observations",
        "The USFDA conducted an inspection at the Company's Halol facility, which concluded with a Form 483 with "
        "3 observations. The Company will respond within the stipulated time.")
    add(6, 18, 0, "DIXON", "Board Meeting Intimation",
        "Intimation of Board Meeting to consider and approve financial results for the quarter ended 30 September 2026")
    add(6, 10, 0, "M&M", "Press Release", "Press release - October 2026 total auto sales up 17% year-on-year")
    add(7, 11, 30, "ASIANPAINT", "Shareholders meeting", "Postal ballot notice",
        "Notice of postal ballot seeking shareholder approval for re-appointment of an independent director.")
    add(7, 16, 0, "ITC", "Insider Trading - SAST",
        "Disclosure under Regulation 7(2) of SEBI (PIT) Regulations - sale of shares by a designated person")
    for a in A:
        a["dedupe_key"] = hashlib.sha256(f"demo|{a['ticker']}|{a['subject']}|{a['published_at']}".encode()).hexdigest()
    return A


# ---------------------------------------------------------------- PDFs
def write_pdf(path: Path, title: str, sections: list[tuple[str, list[str]]]) -> int:
    """A4, Helvetica; watermark + title header on every page; each paragraph a separate textbox."""
    import pymupdf
    doc = pymupdf.open()
    W, H, M = 595, 842, 50
    width_chars = 92
    page = None
    y = 0.0

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=W, height=H)
        page.insert_text((M, 28), WATERMARK, fontsize=6.5, fontname="helv", color=(0.75, 0.2, 0.2))
        page.insert_text((M, 40), title, fontsize=7.5, fontname="helv", color=(0.4, 0.4, 0.4))
        y = 64

    def box(text, size=10.0, bold=False, gap=10.0):
        nonlocal y
        fn = "hebo" if bold else "helv"
        lines = textwrap.wrap(text, width=width_chars if size <= 10 else int(width_chars * 10 / size)) or [""]
        h = len(lines) * size * 1.25 + 4
        if page is None or y + h > H - 60:
            new_page()
        # insert_textbox writes nothing when the text overflows, so grow the box until it fits
        while True:
            shape = page.new_shape()
            rc = shape.insert_textbox(pymupdf.Rect(M, y, W - M, y + h), text, fontsize=size, fontname=fn)
            if rc >= 0:
                shape.commit()
                h -= rc
                break
            h += size * 1.25
        y += h + gap

    for heading, pars in sections:
        if heading == "<pagebreak>":
            new_page()
            continue
        if heading:
            box(heading, size=12.5, bold=True, gap=6)
        for p in pars:
            box(p)
    total = len(doc)
    for i, pg in enumerate(doc, 1):
        pg.insert_text((W / 2 - 20, H - 28), f"Page {i} of {total}", fontsize=7, fontname="helv", color=(0.5, 0.5, 0.5))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return total


def _cr(x: float) -> str:
    return f"Rs. {indian_group(int(round(x)))} crore"


AR_TEXT = {
    "DIXON": {
        "name": "Dixon Technologies (India) Ltd",
        "industry": "Dixon is India's largest home-grown electronics manufacturing services (EMS) company. It designs and "
                    "manufactures products for leading consumer-electronics and mobile brands, which sell them under "
                    "their own names.",
        "segments": "The Company operates four segments: mobile phones and EMS, consumer electronics (LED televisions), "
                    "home appliances (washing machines) and lighting products.",
        "mix": "In FY26 the revenue mix was mobile and EMS 72%, consumer electronics 16%, home appliances 7%, lighting and "
               "others 5%.",
        "outlook": "Management expects the production-linked incentive (PLI) scheme and new customer additions in mobile "
                   "phones to support growth in FY27. The Company is investing in display modules and component "
                   "manufacturing to deepen value addition.",
        "risks": ["Customer concentration: the top five customers contribute a large share of revenue, and the loss of "
                  "any one could affect volumes.",
                  "Input and commodity volatility: component prices, especially memory and display panels, can move "
                  "sharply and are passed through with a lag.",
                  "Changes to government incentive schemes such as PLI could affect profitability.",
                  "Competition from other EMS providers, domestic and global, could pressure margins.",
                  "Foreign exchange: a large share of components is imported and priced in US dollars.",
                  "Execution risk in scaling new plants and product lines on schedule."],
        "emphasis": None,
    },
    "TITAN": {
        "name": "Titan Company Ltd",
        "industry": "Titan is a consumer lifestyle company with a retail network of branded stores across India.",
        "segments": "The Company operates jewellery (Tanishq, Mia, Zoya), watches and wearables, eyecare, and emerging "
                    "businesses including fragrances and Indian dress wear.",
        "mix": "In FY26 the revenue mix was jewellery 88%, watches and wearables 7%, eyecare 2%, emerging businesses and "
               "others 3%.",
        "outlook": "Management expects store additions and wedding demand to support growth, while elevated gold prices "
                   "may weigh on volumes in the near term.",
        "risks": ["Gold-price volatility affects consumer demand and inventory valuation.",
                  "Gold metal loans: a significant part of gold inventory is funded through gold metal loans, exposing "
                  "the Company to gold-price and interest-rate movements.",
                  "Input and commodity volatility in diamonds and other materials.",
                  "Changes in import duties and government regulation on gold.",
                  "Competition from national and regional jewellers and new entrants.",
                  "Execution risk in the store expansion programme."],
        "emphasis": "Emphasis of matter: We draw attention to the note on gold metal loans, which describes the "
                    "accounting for gold taken on loan from banks. Our opinion is not modified in respect of this matter.",
    },
    "TRENT": {
        "name": "Trent Ltd",
        "industry": "Trent is a fashion and lifestyle retailer operating Westside, Zudio and other formats through "
                    "company-owned stores.",
        "segments": "The Company's formats are Zudio (value fashion), Westside (premium fashion and home) and others "
                    "including Star grocery and international brands.",
        "mix": "In FY26 the revenue mix was Zudio 58%, Westside 37%, others 5%.",
        "outlook": "Management expects continued store additions in Zudio and Westside, with a focus on productivity per "
                   "square foot.",
        "risks": ["Customer concentration is low, but demand is sensitive to discretionary spending.",
                  "Input and commodity volatility in cotton and other fabrics affects product costs.",
                  "Changes in incentive schemes or GST rates on apparel could affect pricing.",
                  "Competition from value-fashion chains and online platforms is intensifying.",
                  "Foreign exchange exposure is limited to imported merchandise.",
                  "Execution risk in opening several hundred stores a year."],
        "emphasis": None,
    },
}


def annual_report(ticker: str, annual: list[tuple[date, dict]], path: Path) -> int:
    t = AR_TEXT[ticker]
    fy26, fy25 = annual[-1][1], annual[-2][1]
    g = (fy26["revenue"] / fy25["revenue"] - 1) * 100
    em = fy26["ebitda"] / fy26["revenue"] * 100
    de = fy26["borrowings"] / fy26["net_worth"]
    sections = [
        ("", [f"{t['name']}", "Annual Report FY26 (financial year ended 31 March 2026)",
              "This is an illustrative demo document generated for the FINN prototype. It is not a real company filing."]),
        ("Business Overview", [t["industry"], t["segments"], t["mix"]]),
        ("<pagebreak>", []),
        ("Management Discussion and Analysis", [
            f"Financial performance: Consolidated revenue from operations for FY26 was {_cr(fy26['revenue'])} against "
            f"{_cr(fy25['revenue'])} in FY25, a growth of {g:.1f}%.",
            f"EBITDA for FY26 was {_cr(fy26['ebitda'])}, an EBITDA margin of {em:.1f}%. Profit after tax was "
            f"{_cr(fy26['pat'])} against {_cr(fy25['pat'])} in FY25.",
            f"Borrowings at the end of FY26 were {_cr(fy26['borrowings'])} and net worth was {_cr(fy26['net_worth'])}, a "
            f"debt-to-equity ratio of {de:.2f}. Cash flow from operating activities was {_cr(fy26['cfo'])}.",
        ]),
        ("Outlook", [t["outlook"]]),
        ("Risks and Concerns", t["risks"]),
        ("<pagebreak>", []),
        ("Key Financial Ratios", [
            f"Ratio FY26 FY25 | EBITDA margin % {em:.1f} {fy25['ebitda'] / fy25['revenue'] * 100:.1f} | "
            f"ROE % {fy26['roe']:.1f} {fy25['roe']:.1f} | ROCE % {fy26['roce']:.1f} {fy25['roce']:.1f} | "
            f"Debt to equity {de:.2f} {fy25['borrowings'] / fy25['net_worth']:.2f} | Debtor days {fy26['debtor_days']:.0f} "
            f"{fy25['debtor_days']:.0f} | Inventory days {fy26['inventory_days']:.0f} {fy25['inventory_days']:.0f}"]),
        ("Notes to the Consolidated Financial Statements", [
            f"Contingent liabilities: Claims against the Company not acknowledged as debts, including disputed tax "
            f"demands and guarantees, amount to {_cr(fy26['revenue'] * 0.011)} as at 31 March 2026.",
            f"Related party transactions: Transactions with related parties during FY26 amounted to "
            f"{_cr(fy26['revenue'] * 0.004)}. All related party transactions were in the ordinary course of business and "
            "at arm's length.",
        ]),
        ("<pagebreak>", []),
        ("Independent Auditor's Report", [
            "Opinion: In our opinion, the consolidated financial statements give a true and fair view in conformity with "
            "Indian Accounting Standards. We have issued an unmodified opinion.",
        ] + ([t["emphasis"]] if t["emphasis"] else [])),
        ("Report on Corporate Governance", [
            "Shareholding of promoters: Promoter shares pledged or otherwise encumbered: Nil.",
        ]),
    ]
    return write_pdf(path, f"{t['name']} - Annual Report FY26", sections)


TRANSCRIPTS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "DIXON": {
        "Q3 FY26": [
            ("Moderator", "Ladies and gentlemen, good day and welcome to the Dixon Technologies Q3 FY26 earnings conference call."),
            ("Managing Director", "Thank you. Demand from our mobile customers remained healthy through the festive season. For FY26 we expect revenue growth of 30% to 35%, driven by mobile phones and new EMS customers."),
            ("Chief Financial Officer", "On profitability, we expect EBITDA margin for FY26 in the range of 3.9% to 4.1%. Working capital remains tight and we continue to manage it carefully."),
            ("Analyst A", "Could you talk about investments in new capacity and how you plan to fund them?"),
            ("Managing Director", "Capex for FY26 will be about Rs. 1,000 crore, largely for display modules and mobile capacity. We will fund it from internal accruals."),
        ],
        "Q4 FY26": [
            ("Moderator", "Good day and welcome to the Dixon Technologies Q4 FY26 earnings conference call."),
            ("Managing Director", "FY26 was an exceptional year and revenue grew about 38%. For FY27 we are guiding revenue growth of 30% to 35%."),
            ("Chief Financial Officer", "For Q1 FY27 we expect EBITDA margin of 4.0% to 4.2%, helped by a richer mix."),
            ("Analyst B", "How do you think about customer concentration risk in the mobile business?"),
            ("Managing Director", "Customer concentration is a real risk for any EMS company. We are adding new customers across categories to reduce dependence on any single brand."),
        ],
        "Q1 FY27": [
            ("Moderator", "Good day and welcome to the Dixon Technologies Q1 FY27 earnings conference call."),
            ("Managing Director", "Q1 margins came in below our expectation because of component costs. Demand has been strong, so we are raising our FY27 guidance and now expect revenue growth of 35% to 40% for FY27."),
            ("Chief Financial Officer", "For the next quarter we expect revenue growth of at least 30% year-on-year. We expect FY27 EBITDA margin of 3.8% to 4.0%."),
            ("Analyst A", "What is happening with working capital as you scale up?"),
            ("Chief Financial Officer", "Working capital days have improved as receivable days came down. We will keep a close eye on inventory as new lines ramp up."),
        ],
        "Q2 FY27": [
            ("Moderator", "Good day and welcome to the Dixon Technologies Q2 FY27 earnings conference call."),
            ("Managing Director", "Q2 revenue grew 38% year-on-year on strong mobile volumes. We maintain the FY27 guidance of revenue growth of 35% to 40%."),
            ("Chief Financial Officer", "Over the medium term we aspire to an EBITDA margin of 4.5% as backward integration into components matures."),
            ("Analyst B", "Thank you, that is helpful."),
        ],
    },
    "TITAN": {
        "Q3 FY26": [
            ("Moderator", "Good day and welcome to the Titan Company Q3 FY26 earnings conference call."),
            ("Managing Director", "The festive and wedding season was healthy for jewellery. We expect to close FY26 with revenue growth of around 20%."),
            ("Chief Financial Officer", "We expect EBITDA margin for FY26 to be in the 11% to 11.5% band. Gold metal loans remain an important source of funding for our gold inventory."),
            ("Analyst A", "Is the high gold price affecting buyer behaviour?"),
            ("Managing Director", "Buyers are shifting to lighter-weight designs and exchange programmes when gold prices rise."),
        ],
        "Q4 FY26": [
            ("Moderator", "Good day and welcome to the Titan Company Q4 FY26 earnings conference call."),
            ("Managing Director", "FY26 revenue grew about 16%, below the 20% we had indicated. For FY27 we are guiding revenue growth of 18% to 20%."),
            ("Chief Financial Officer", "For Q1 FY27 we expect revenue growth of 14% to 16%. We are targeting FY27 EBITDA margin of 11% to 11.5%."),
            ("Analyst B", "Inventory seems to have gone up. Can you explain?"),
            ("Chief Financial Officer", "Inventory has risen with new stores and higher gold prices. We are working to improve inventory turns."),
        ],
        "Q1 FY27": [
            ("Moderator", "Good day and welcome to the Titan Company Q1 FY27 earnings conference call."),
            ("Managing Director", "Given the gold price environment, we now expect FY27 revenue growth of 15% to 17%, lower than our earlier guidance."),
            ("Chief Financial Officer", "We maintain the FY27 EBITDA margin guidance of 11% to 11.5%."),
            ("Managing Director", "We plan to open around 60 new stores this year across formats."),
            ("Analyst A", "Thank you for the clarity."),
        ],
        "Q2 FY27": [
            ("Moderator", "Good day and welcome to the Titan Company Q2 FY27 earnings conference call."),
            ("Managing Director", "Q2 revenue grew about 9% as high gold prices weighed on volumes."),
            ("Chief Financial Officer", "With the festive season ahead, we expect the second half to show double-digit revenue growth with margins recovering."),
            ("Analyst B", "Thank you."),
        ],
    },
    "TRENT": {
        "Q3 FY26": [
            ("Moderator", "Good day and welcome to the Trent Ltd Q3 FY26 earnings conference call."),
            ("Managing Director", "Zudio continues to lead our growth. We expect FY26 revenue growth of upwards of 25%."),
            ("Chief Financial Officer", "We expect FY26 EBITDA margin of 16% to 17% on a pre-Ind AS 116 basis."),
            ("Managing Director", "We plan to add about 200 Zudio stores in FY26."),
            ("Analyst A", "How are like-for-like sales trending?"),
        ],
        "Q4 FY26": [
            ("Moderator", "Good day and welcome to the Trent Ltd Q4 FY26 earnings conference call."),
            ("Managing Director", "FY26 revenue grew about 22%. For FY27 we expect revenue growth of around 20%."),
            ("Chief Financial Officer", "For Q1 FY27 we expect revenue growth of at least 15% year-on-year. Capex for FY27 will be about Rs. 1,500 crore, mainly for new stores and distribution centres."),
            ("Analyst B", "Thank you."),
        ],
        "Q1 FY27": [
            ("Moderator", "Good day and welcome to the Trent Ltd Q1 FY27 earnings conference call."),
            ("Managing Director", "Q1 revenue grew about 17%. We maintain our FY27 guidance of revenue growth of around 20%."),
            ("Chief Financial Officer", "We expect FY27 EBITDA margin of 17% to 18%."),
            ("Managing Director", "We are piloting quick-commerce fashion delivery in two cities."),
            ("Analyst A", "Thank you."),
        ],
        "Q2 FY27": [
            ("Moderator", "Good day and welcome to the Trent Ltd Q2 FY27 earnings conference call."),
            ("Managing Director", "Q2 revenue grew about 18.5% with Zudio crossing 900 stores."),
            ("Chief Financial Officer", "We expect the next quarter to deliver revenue growth of 18% to 20%. We are confident of sustaining margins in the 17% to 18% range over the medium term."),
            ("Analyst B", "Thank you."),
        ],
    },
}
CALL_QE = {"Q3 FY26": date(2025, 12, 31), "Q4 FY26": date(2026, 3, 31), "Q1 FY27": date(2026, 6, 30),
           "Q2 FY27": date(2026, 9, 30)}


def transcript_pdf(ticker: str, call: str, path: Path) -> int:
    name = AR_TEXT[ticker]["name"]
    turns = TRANSCRIPTS[ticker][call]
    sections = [("", [f"{name} {call} earnings conference call transcript"]),
                ("Opening Remarks", [f"{sp}: {tx}" for sp, tx in turns[:3]]),
                ("Q&A Session", [f"{sp}: {tx}" for sp, tx in turns[3:]])]
    return write_pdf(path, f"{name} - {call} Earnings Call Transcript", sections)


# ---------------------------------------------------------------- reset
def _wipe(s: Session) -> None:
    for model in (AlertEvent, AlertRule, Guidance, Chunk, Document, Announcement, FinancialPeriod, Price, Holding,
                  ResearchLog, Meta, Company):
        s.execute(delete(model))
    s.flush()


def reset(s: Session) -> dict[str, Any]:
    _wipe(s)
    docs_dir = settings.docs_dir / "demo"
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    universe = PORTFOLIO + RESEARCH
    for t, n, sec, f in universe:
        s.add(Company(ticker=t, name=n, sector=sec, is_financial=f, about=ABOUT.get(t), source="demo"))
    for t, *_ in PORTFOLIO:
        s.add(Holding(ticker=t, source="demo"))
    s.flush()
    fin: dict[str, list[dict]] = {}
    annual: dict[str, list] = {}
    for t, n, sec, f in universe:
        q = _quarter_rows(t, f)
        fin[t] = q
        for qe, m in zip(QUARTER_ENDS, q):
            s.add(FinancialPeriod(ticker=t, period_type="Q", period_end=qe, label=month_label(qe), basis="consolidated",
                                  metrics=m, source="demo", source_url=f"demo://{t}/financials"))
        annual[t] = _annual_rows(t, q, f)
        for fe, m in annual[t]:
            s.add(FinancialPeriod(ticker=t, period_type="Y", period_end=fe, label=month_label(fe), basis="consolidated",
                                  metrics=m, source="demo", source_url=f"demo://{t}/financials"))
        for row in _prices(t):
            s.add(Price(**row))
    s.flush()
    for a in announcements(fin):
        s.add(Announcement(**a))
    s.flush()
    for t in STORY:
        path = docs_dir / f"{t}_AR_FY26.pdf"
        annual_report(t, annual[t], path)
        d = Document(ticker=t, doc_type="annual_report", title=f"{AR_TEXT[t]['name']} Annual Report FY26",
                     url=f"demo://{t}/annual-report/FY26", period_label="FY26", period_end=date(2026, 3, 31),
                     local_path=str(path), status="downloaded", source="demo")
        s.add(d)
        for call, qe in CALL_QE.items():
            p = docs_dir / f"{t}_concall_{call.replace(' ', '_')}.pdf"
            transcript_pdf(t, call, p)
            s.add(Document(ticker=t, doc_type="transcript", title=f"{t} {call} earnings call transcript",
                           url=f"demo://{t}/transcript/{call.replace(' ', '-')}", period_label=call, period_end=qe,
                           local_path=str(p), status="downloaded", source="demo"))
    s.flush()
    for d in s.query(Document).all():
        ingest.ingest_document(s, d)
    set_meta(s, "data_mode", "demo")
    set_meta(s, "source_status", {
        "demo": {"ok": True, "detail": f"Illustrative dataset frozen at {DEMO_TODAY.isoformat()}",
                 "at": datetime.now().isoformat(timespec="seconds")}})
    alerts.seed_defaults(s)
    signals.process(s, force=True)
    alerts.evaluate(s)
    for t in STORY:
        G.extract(s, t)
    s.flush()
    return {"companies": len(universe), "announcements": s.query(Announcement).count(),
            "documents": s.query(Document).count(), "chunks": s.query(Chunk).count()}
