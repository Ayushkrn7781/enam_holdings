"""CLI: python -m finn.refresh [--tickers ...] [--research TRENT HAL PERSISTENT] [--days 7] [--no-docs]"""
from __future__ import annotations

import argparse
import json

from .db import init_db, session_scope
from .services.pipeline import refresh_all


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh FINN from live sources (NSE, screener.in, Yahoo Finance).")
    ap.add_argument("--tickers", nargs="*", help="portfolio tickers (default: the 20-name universe)")
    ap.add_argument("--research", nargs="*", default=["TRENT", "HAL", "PERSISTENT"],
                    help="ad-hoc research names; their documents are downloaded and indexed")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-docs", action="store_true")
    a = ap.parse_args()
    init_db()
    with session_scope() as s:
        rep = refresh_all(s, a.tickers or None, a.research, a.days, with_docs=not a.no_docs)
    print(json.dumps(rep, indent=2, default=str))


if __name__ == "__main__":
    main()
