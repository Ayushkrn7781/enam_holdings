"""NSE corporate announcements connector.

NSE's public JSON endpoint requires a cookie from a normal page visit first. We fetch politely
(one request per symbol, small delay) and only what an investor could see on the website.
If NSE blocks the request, the refresh reports the failure — it never substitutes fake filings.
"""
from __future__ import annotations

import hashlib
import io
import logging
import time
from datetime import date, datetime

import httpx

log = logging.getLogger("finn.nse")
BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE}/companies-listing/corporate-filings-announcements",
}


class NSEClient:
    def __init__(self, delay_s: float = 0.7):
        self.c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True, http2=False)
        self.delay = delay_s
        self._warm = False

    def _warmup(self):
        if not self._warm:
            self.c.get(BASE)
            self.c.get(f"{BASE}/companies-listing/corporate-filings-announcements")
            self._warm = True

    def announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        self._warmup()
        params = {"index": "equities", "symbol": symbol, "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
        for attempt in range(3):
            r = self.c.get(f"{BASE}/api/corporate-announcements", params=params)
            if r.status_code in (401, 403):
                self._warm = False
                self._warmup()
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
            time.sleep(self.delay)
            data = r.json()
            return [normalise(symbol, x) for x in (data if isinstance(data, list) else data.get("data", []))]
        raise RuntimeError(f"NSE refused announcements for {symbol}")

    def pdf_text(self, url: str, max_pages: int = 12) -> str | None:
        """Download a filing attachment and return page texts joined by form-feeds."""
        try:
            r = self.c.get(url)
            r.raise_for_status()
            if b"%PDF" not in r.content[:1024]:
                return None
            import fitz

            with fitz.open(stream=io.BytesIO(r.content), filetype="pdf") as doc:
                return "\f".join(p.get_text("text") for p in list(doc)[:max_pages])
        except Exception as e:
            log.info("attachment fetch failed %s: %s", url, e)
            return None


def _parse_dt(x: dict) -> datetime:
    for key in ("an_dt", "sort_date", "dt"):
        v = x.get(key)
        if not v:
            continue
        for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d%m%Y%H%M%S"):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                pass
    return datetime.utcnow()


def normalise(symbol: str, x: dict) -> dict:
    subject = (x.get("attchmntText") or x.get("desc") or "").strip()
    published = _parse_dt(x)
    url = x.get("attchmntFile") or None
    key = hashlib.sha256(f"nse|{symbol}|{x.get('seq_id') or ''}|{subject[:120]}|{published:%Y%m%d%H%M}".encode()).hexdigest()
    return {
        "ticker": symbol,
        "published_at": published,
        "subject": subject[:1000] or (x.get("desc") or "Announcement"),
        "body": None,
        "exchange_category": x.get("desc"),
        "attachment_url": url,
        "source": "nse",
        "dedupe_key": key,
    }
