"""screener.in fundamentals connector: quarterly + annual tables and links to primary documents
(annual reports, concall transcripts). Numbers are ₹ crore as published by the company.

Usage note: screener.in is used only to *locate* primary documents and read standardised statements,
at a polite rate, for personal research — as the challenge brief suggests.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("finn.screener")
BASE = "https://www.screener.in"
UA = {"User-Agent": "Mozilla/5.0 (FINN research prototype)"}

ROW_MAP = {
    # quarterly / P&L
    "sales": "revenue", "revenue": "revenue", "expenses": "expenses", "operating profit": "ebitda",
    "financing profit": "ebitda", "other income": "other_income", "interest": "interest", "depreciation": "depreciation",
    "profit before tax": "pbt", "tax %": "tax_pct", "net profit": "pat", "eps in rs": "eps", "exceptional items": "exceptional",
    # balance sheet
    "equity capital": "equity_capital", "reserves": "reserves", "borrowings": "borrowings", "deposits": "deposits",
    "other liabilities": "other_liabilities", "total liabilities": "total_assets", "fixed assets": "fixed_assets",
    "cwip": "cwip", "investments": "investments", "other assets": "other_assets",
    # cash flow
    "cash from operating activity": "cfo", "cash from investing activity": "cfi", "cash from financing activity": "cff",
    "net cash flow": "net_cash_flow", "free cash flow": "fcf",
    # ratios
    "debtor days": "debtor_days", "inventory days": "inventory_days", "days payable": "payable_days",
    "cash conversion cycle": "ccc", "working capital days": "wc_days", "roce %": "roce", "roe %": "roe",
}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _num(t: str) -> float | None:
    t = t.strip().replace(",", "").replace("%", "")
    if not t or t in ("-", "--"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _period_end(label: str) -> date | None:
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", label.strip())
    if not m:
        return None
    mon, yr = MONTHS.get(m.group(1).lower()), int(m.group(2))
    if not mon:
        return None
    import calendar

    return date(yr, mon, calendar.monthrange(yr, mon)[1])


def _table(soup: BeautifulSoup, section_id: str) -> list[dict]:
    sec = soup.find("section", id=section_id)
    if not sec or not sec.find("table"):
        return []
    tbl = sec.find("table")
    heads = [th.get_text(" ", strip=True) for th in tbl.find("thead").find_all("th")][1:]
    cols = [{"label": h, "period_end": _period_end(h), "metrics": {}} for h in heads]
    for tr in tbl.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        name = re.sub(r"\s*\+\s*$", "", tds[0].get_text(" ", strip=True)).strip().lower()
        key = ROW_MAP.get(name)
        if not key:
            continue
        for col, td in zip(cols, tds[1:]):
            col["metrics"][key] = _num(td.get_text(strip=True))
    return [c for c in cols if c["period_end"]]


class ScreenerClient:
    def __init__(self, delay_s: float = 1.2):
        self.c = httpx.Client(headers=UA, timeout=30, follow_redirects=True)
        self.delay = delay_s

    def page(self, ticker: str) -> tuple[BeautifulSoup, str, str]:
        for basis, path in (("consolidated", f"/company/{ticker}/consolidated/"), ("standalone", f"/company/{ticker}/")):
            r = self.c.get(BASE + path)
            time.sleep(self.delay)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            q = soup.find("section", id="quarters")
            if q and q.find("tbody") and len(q.find("tbody").find_all("tr")) > 3:
                return soup, basis, BASE + path
        raise LookupError(f"{ticker} not found on screener.in")

    def fundamentals(self, ticker: str) -> dict:
        soup, basis, url = self.page(ticker)
        name = soup.find("h1").get_text(strip=True) if soup.find("h1") else ticker
        about = soup.select_one(".company-profile .about p") or soup.select_one(".about p")
        quarters = _table(soup, "quarters")
        annual = _table(soup, "profit-loss")
        for extra in ("balance-sheet", "cash-flow", "ratios"):
            for col in _table(soup, extra):
                tgt = next((a for a in annual if a["period_end"] == col["period_end"]), None)
                if tgt:
                    tgt["metrics"].update({k: v for k, v in col["metrics"].items() if v is not None})
        for a in annual:
            m = a["metrics"]
            if m.get("equity_capital") is not None and m.get("reserves") is not None:
                m["net_worth"] = m["equity_capital"] + m["reserves"]
        annual = [a for a in annual if "ttm" not in a["label"].lower()]
        is_fin = bool(soup.find("td", string=re.compile(r"Financing Profit")))
        return {"name": name, "basis": basis, "url": url, "about": about.get_text(" ", strip=True) if about else None,
                "is_financial": is_fin, "quarters": quarters, "annual": annual, "documents": self._documents(soup)}

    def _documents(self, soup: BeautifulSoup) -> list[dict]:
        docs = []
        ar = soup.select_one(".documents.annual-reports") or soup.find("div", class_=re.compile("annual-reports"))
        if ar:
            for a in ar.find_all("a", href=True)[:3]:
                t = a.get_text(" ", strip=True)
                m = re.search(r"(?:Financial )?Year\s+(\d{4})", t)
                fy = int(m.group(1)) if m else None
                docs.append({"doc_type": "annual_report", "title": f"Annual Report {t}", "url": a["href"],
                             "period_label": f"FY{fy % 100:02d}" if fy else None, "period_end": date(fy, 3, 31) if fy else None})
        cc = soup.select_one(".documents.concalls") or soup.find("div", class_=re.compile("concalls"))
        if cc:
            for li in cc.find_all("li")[:6]:
                when = li.find("div", class_=re.compile("ink-600")) or li
                txt = when.get_text(" ", strip=True)
                pe = None
                m = re.search(r"([A-Za-z]{3})\s+(\d{4})", txt)
                if m:
                    try:
                        pe = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%b %Y").date()
                    except ValueError:
                        pe = None
                for a in li.find_all("a", href=True):
                    if "transcript" in a.get_text(" ", strip=True).lower():
                        docs.append({"doc_type": "transcript", "title": f"Earnings call transcript ({txt[:8]})", "url": a["href"], "call_date": pe})
        return docs

    def download(self, url: str, dest) -> bool:
        try:
            with self.c.stream("GET", url, headers={**UA, "Accept": "application/pdf"}) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for b in r.iter_bytes():
                        f.write(b)
            with open(dest, "rb") as f:
                return f.read(5) == b"%PDF-"
        except Exception as e:
            log.warning("download failed %s: %s", url, e)
            return False
