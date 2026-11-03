"""EOD prices via yfinance (Yahoo Finance). NSE tickers use the .NS suffix."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from ..models import Price

log = logging.getLogger("finn.prices")


def yahoo_symbol(ticker: str) -> str:
    return ticker if "." in ticker else f"{ticker}.NS"


def fetch(tickers: list[str], period: str = "1y") -> dict[str, list[dict]]:
    import yfinance as yf

    out: dict[str, list[dict]] = {}
    syms = [yahoo_symbol(t) for t in tickers]
    df = yf.download(syms, period=period, interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    for t, sym in zip(tickers, syms):
        try:
            sub = df[sym] if len(syms) > 1 else df
            sub = sub.dropna(subset=["Close"])
            out[t] = [
                {"date": idx.date(), "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]),
                 "close": float(r["Close"]), "adj_close": float(r.get("Adj Close", r["Close"])), "volume": float(r["Volume"])}
                for idx, r in sub.iterrows()
            ]
        except Exception as e:
            log.warning("no price data for %s: %s", t, e)
            out[t] = []
    return out


def store(s: Session, ticker: str, rows: list[dict], source: str = "yfinance") -> int:
    if not rows:
        return 0
    if s.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(Price).values([{**r, "ticker": ticker, "source": source} for r in rows])
    stmt = stmt.on_conflict_do_update(index_elements=["ticker", "date"], set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "adj_close", "volume", "source")})
    s.execute(stmt)
    return len(rows)


def company_info(ticker: str) -> dict | None:
    """Name / sector for ad-hoc tickers outside the seed list."""
    try:
        import yfinance as yf

        info = yf.Ticker(yahoo_symbol(ticker)).info
        if not info or not info.get("longName") and not info.get("shortName"):
            return None
        sector = info.get("sector") or "Unknown"
        return {"name": info.get("longName") or info.get("shortName"), "sector": sector,
                "is_financial": sector == "Financial Services" and "bank" in (info.get("industry") or "").lower(),
                "about": info.get("longBusinessSummary")}
    except Exception as e:
        log.warning("yfinance info failed for %s: %s", ticker, e)
        return None


def last_trading_day(rows: list[dict]) -> date | None:
    return rows[-1]["date"] if rows else None
