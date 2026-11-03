"""NSE corporate announcements (public JSON endpoint behind a cookie warm-up)."""
from __future__ import annotations

import hashlib
import io
import time
from datetime import date, datetime
from typing import Optional

import httpx

BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE}/companies-listing/corporate-filings-announcements",
}


class NSE:
    def __init__(self, timeout: float = 20):
        self.client = httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True)
        self._warm = False

    def warm(self) -> None:
        self.client.get(BASE)
        self.client.get(f"{BASE}/companies-listing/corporate-filings-announcements")
        self._warm = True

    def announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        if not self._warm:
            self.warm()
        params = {"index": "equities", "symbol": symbol, "from_date": start.strftime("%d-%m-%Y"),
                  "to_date": end.strftime("%d-%m-%Y")}
        last_err: Optional[Exception] = None
        for _ in range(3):
            r = self.client.get(f"{BASE}/api/corporate-announcements", params=params)
            if r.status_code in (401, 403):
                time.sleep(1.0)
                self.warm()
                continue
            try:
                r.raise_for_status()
                data = r.json()
                return [normalise(symbol, x) for x in (data if isinstance(data, list) else data.get("data", []))]
            except Exception as e:
                last_err = e
                break
        raise RuntimeError(f"NSE announcements failed for {symbol}: {last_err or 'blocked (401/403)'}")

    def pdf_text(self, url: str, max_pages: int = 12) -> Optional[str]:
        try:
            r = self.client.get(url)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF-"):
                return None
            import pymupdf
            doc = pymupdf.open(stream=io.BytesIO(r.content), filetype="pdf")
            pages = [doc[i].get_text() for i in range(min(max_pages, len(doc)))]
            doc.close()
            return "\f".join(pages)
        except Exception:
            return None


def _parse_time(x: dict) -> Optional[datetime]:
    for k in ("an_dt", "sort_date", "dt"):
        v = x.get(k)
        if not v:
            continue
        for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                continue
    return None


def normalise(symbol: str, x: dict) -> dict:
    subject = (x.get("attchmntText") or x.get("desc") or "").strip()
    ts = _parse_time(x)
    key = hashlib.sha256(f"nse|{symbol}|{x.get('seq_id')}|{subject}|{ts}".encode()).hexdigest()
    return {"ticker": symbol, "published_at": ts, "subject": subject, "body": x.get("attchmntText"),
            "exchange_category": x.get("desc"), "attachment_url": x.get("attchmntFile"), "source": "nse",
            "dedupe_key": key}
