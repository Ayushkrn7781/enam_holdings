"""Live data refresh. Run on a machine with normal internet access (exchange sites block many cloud IPs):

    python -m finn.refresh                       # portfolio prices + 7 days of NSE filings + fundamentals
    python -m finn.refresh --research TRENT HAL  # also download & index annual report + last 4 concall transcripts
    python -m finn.refresh --days 3 --no-docs

Schedule it after market close (e.g. 18:30 IST via cron) for the EOD push cycle.
"""
import argparse
import json
import logging

from .db import init_db, session_scope
from .services.pipeline import refresh_all
from .universe import ADHOC

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*", help="portfolio tickers (default: current holdings / seed portfolio)")
    ap.add_argument("--research", nargs="*", default=[t for t, *_ in ADHOC[:3]], help="tickers to ingest documents for")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-docs", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    with session_scope() as s:
        print(json.dumps(refresh_all(s, a.tickers, a.research, a.days, not a.no_docs), indent=2, default=str))
