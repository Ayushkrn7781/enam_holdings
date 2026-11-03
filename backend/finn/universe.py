"""Portfolio universe and ad-hoc research names. The engine itself works for any NSE symbol."""
from __future__ import annotations

import re

TICKER_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")

# (ticker, name, sector, is_financial)
PORTFOLIO = [
    ("RELIANCE", "Reliance Industries Ltd", "Energy & Conglomerate", False),
    ("HDFCBANK", "HDFC Bank Ltd", "Banking", True),
    ("ICICIBANK", "ICICI Bank Ltd", "Banking", True),
    ("SBIN", "State Bank of India", "Banking", True),
    ("INFY", "Infosys Ltd", "IT Services", False),
    ("TCS", "Tata Consultancy Services Ltd", "IT Services", False),
    ("KPITTECH", "KPIT Technologies Ltd", "IT Services", False),
    ("TMPV", "Tata Motors Passenger Vehicles Ltd", "Automobiles", False),
    ("MARUTI", "Maruti Suzuki India Ltd", "Automobiles", False),
    ("M&M", "Mahindra & Mahindra Ltd", "Automobiles", False),
    ("LT", "Larsen & Toubro Ltd", "Infrastructure", False),
    ("ITC", "ITC Ltd", "FMCG", False),
    ("HINDUNILVR", "Hindustan Unilever Ltd", "FMCG", False),
    ("SUNPHARMA", "Sun Pharmaceutical Industries Ltd", "Pharmaceuticals", False),
    ("BHARTIARTL", "Bharti Airtel Ltd", "Telecom", False),
    ("NTPC", "NTPC Ltd", "Power", False),
    ("TITAN", "Titan Company Ltd", "Consumer Discretionary", False),
    ("ASIANPAINT", "Asian Paints Ltd", "Consumer Discretionary", False),
    ("DIXON", "Dixon Technologies (India) Ltd", "Electronics Manufacturing", False),
    ("POLYCAB", "Polycab India Ltd", "Capital Goods", False),
]

RESEARCH = [
    ("TRENT", "Trent Ltd", "Retail", False),
    ("PERSISTENT", "Persistent Systems Ltd", "IT Services", False),
    ("HAL", "Hindustan Aeronautics Ltd", "Defence", False),
    ("BAJFINANCE", "Bajaj Finance Ltd", "NBFC", True),
    ("DMART", "Avenue Supermarts Ltd", "Retail", False),
]

ALL = PORTFOLIO + RESEARCH
BY_TICKER = {t: (t, n, s, f) for (t, n, s, f) in ALL}


def valid_ticker(t: str) -> bool:
    return bool(TICKER_RE.match(t or ""))


def normalise(t: str) -> str:
    return (t or "").strip().upper().removesuffix(".NS").removesuffix(".BO")
