"""screener.in: standardised financials plus links to annual reports and concall transcripts."""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from ..research.periods import month_end

BASE = "https://www.screener.in"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

ROW_MAP = [
    (r"^(sales|revenue)$", "revenue"), (r"^expenses$", "expenses"),
    (r"^(operating profit|financing profit)$", "ebitda"), (r"^other income$", "other_income"),
    (r"^interest$", "interest"), (r"^depreciation$", "depreciation"), (r"^profit before tax$", "pbt"),
    (r"^tax %$", "tax_pct"), (r"^net profit$", "pat"), (r"^eps in rs$", "eps"), (r"^exceptional items$", "exceptional"),
    (r"^equity capital$", "equity_capital"), (r"^reserves$", "reserves"), (r"^borrowings$", "borrowings"),
    (r"^deposits$", "deposits"), (r"^other liabilities$", "other_liabilities"), (r"^total liabilities$", "total_assets"),
    (r"^fixed assets$", "fixed_assets"), (r"^cwip$", "cwip"), (r"^investments$", "investments"),
    (r"^other assets$", "other_assets"), (r"^cash from operating activity$", "cfo"),
    (r"^cash from investing activity$", "cfi"), (r"^cash from financing activity$", "cff"),
    (r"^net cash flow$", "net_cash_flow"), (r"^free cash flow$", "fcf"), (r"^debtor days$", "debtor_days"),
    (r"^inventory days$", "inventory_days"), (r"^days payable$", "payable_days"),
    (r"^cash conversion cycle$", "ccc"), (r"^working capital days$", "working_capital_days"),
    (r"^roce %$", "roce"), (r"^roe %$", "roe"),
]
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"], 1)}


def _num(t: str) -> Optional[float]:
    t = (t or "").replace(",", "").replace("%", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _col_date(h: str) -> Optional[date]:
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", h.strip())
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    return month_end(int(m.group(2)), _MONTHS[m.group(1).lower()])


def _key(name: str) -> Optional[str]:
    n = re.sub(r"\s*\+\s*$", "", name.strip()).strip().lower()
    for rx, k in ROW_MAP:
        if re.match(rx, n):
            return k
    return None


def parse_table(section) -> dict[date, dict[str, float]]:
    out: dict[date, dict[str, float]] = {}
    if section is None:
        return out
    table = section.find("table")
    if table is None:
        return out
    heads = [th.get_text(" ", strip=True) for th in table.find("thead").find_all("th")] if table.find("thead") else []
    cols = [_col_date(h) for h in heads]
    for tr in table.find("tbody").find_all("tr") if table.find("tbody") else []:
        tds = tr.find_all("td")
        if not tds:
            continue
        k = _key(tds[0].get_text(" ", strip=True))
        if not k:
            continue
        for i, td in enumerate(tds[1:], 1):
            if i < len(cols) and cols[i]:
                v = _num(td.get_text(strip=True))
                if v is not None:
                    out.setdefault(cols[i], {})[k] = v
    return out


def fetch_company(ticker: str, client: Optional[httpx.Client] = None) -> dict[str, Any]:
    c = client or httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
    page = basis = url = None
    for suffix, b in (("consolidated/", "consolidated"), ("", "standalone")):
        u = f"{BASE}/company/{ticker}/{suffix}"
        r = c.get(u)
        time.sleep(1.2)
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        q = soup.select_one("section#quarters")
        if q and len(q.select("tbody tr")) > 3:
            page, basis, url = soup, b, u
            break
    if page is None:
        raise RuntimeError(f"screener.in has no usable page for {ticker}")
    quarters = parse_table(page.select_one("section#quarters"))
    annual: dict[date, dict[str, float]] = {}
    for sid in ("profit-loss", "balance-sheet", "cash-flow", "ratios"):
        for d, m in parse_table(page.select_one(f"section#{sid}")).items():
            annual.setdefault(d, {}).update(m)
    is_fin = bool(page.find("td", string=re.compile(r"Financing Profit", re.I)))
    for m in annual.values():
        if "equity_capital" in m or "reserves" in m:
            m["net_worth"] = m.get("equity_capital", 0) + m.get("reserves", 0)
    docs = []
    for a in page.select("#documents a, section#documents a, .documents a"):
        text = a.get_text(" ", strip=True)
        href = a.get("href") or ""
        fy = re.search(r"Financial Year (\d{4})", text)
        if fy and len([d for d in docs if d["doc_type"] == "annual_report"]) < 3:
            docs.append({"doc_type": "annual_report", "title": f"Annual Report FY{int(fy.group(1)) % 100:02d}",
                         "url": href, "period_label": f"FY{int(fy.group(1)) % 100:02d}",
                         "period_end": date(int(fy.group(1)), 3, 31)})
    for li in page.select(".concalls li, #documents .concalls li"):
        month = li.find("div")
        mtxt = month.get_text(" ", strip=True) if month else ""
        for a in li.find_all("a"):
            if "transcript" in a.get_text(" ", strip=True).lower() and len(
                    [d for d in docs if d["doc_type"] == "transcript"]) < 6:
                docs.append({"doc_type": "transcript", "title": f"Concall transcript {mtxt}", "url": a.get("href"),
                             "call_month": mtxt})
    about = page.select_one(".company-profile .about p, .about p")
    name = page.select_one("h1")
    return {"ticker": ticker, "basis": basis, "url": url, "quarters": quarters, "annual": annual,
            "is_financial": is_fin, "documents": docs, "about": about.get_text(" ", strip=True) if about else None,
            "name": name.get_text(strip=True) if name else None}


def download(url: str, dest: Path, client: Optional[httpx.Client] = None) -> Path:
    c = client or httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True)
    r = c.get(url)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF-"):
        raise RuntimeError("not a PDF (missing %PDF- magic bytes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest
