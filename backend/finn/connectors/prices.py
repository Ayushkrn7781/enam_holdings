"""End-of-day prices from Yahoo Finance (yfinance, imported lazily)."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Price


def _insert(s: Session):
    name = s.get_bind().dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def upsert_prices(s: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    insert = _insert(s)
    stmt = insert(Price).values(rows)
    stmt = stmt.on_conflict_do_update(index_elements=["ticker", "date"], set_={
        k: getattr(stmt.excluded, k) for k in ("open", "high", "low", "close", "adj_close", "volume", "source")})
    s.execute(stmt)
    return len(rows)


def fetch(tickers: list[str], period: str = "1y") -> dict[str, list[dict]]:
    import yfinance as yf  # lazy: only needed for live data
    syms = [f"{t}.NS" for t in tickers]
    df = yf.download(syms, period=period, interval="1d", group_by="ticker", auto_adjust=False, progress=False,
                     threads=True)
    out: dict[str, list[dict]] = {}
    for t, sym in zip(tickers, syms):
        try:
            sub = df[sym] if len(syms) > 1 else df
        except KeyError:
            continue
        rows = []
        for idx, r in sub.dropna(subset=["Close"]).iterrows():
            rows.append({"ticker": t, "date": idx.date(), "open": float(r["Open"]), "high": float(r["High"]),
                         "low": float(r["Low"]), "close": float(r["Close"]),
                         "adj_close": float(r.get("Adj Close", r["Close"])), "volume": float(r["Volume"]),
                         "source": "yfinance"})
        if rows:
            out[t] = rows
    return out


def company_info(ticker: str) -> Optional[dict[str, Any]]:
    try:
        import yfinance as yf
        info = yf.Ticker(f"{ticker}.NS").info or {}
    except Exception:
        return None
    name = info.get("longName") or info.get("shortName")
    if not name:
        return None
    sector = info.get("sector") or info.get("industry")
    fin = bool(sector and "financial" in sector.lower())
    return {"ticker": ticker, "name": name, "sector": sector, "is_financial": fin,
            "about": info.get("longBusinessSummary"), "source": "yfinance"}
