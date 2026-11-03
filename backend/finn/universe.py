"""Seed universe: demo portfolio (20 NSE names, mixed sectors and sizes) + ad-hoc research names.

The engine is ticker-driven: any NSE symbol can be added at runtime; this list only seeds names/sectors.
Note: Tata Motors demerged in Oct 2025 — the listed passenger-vehicle entity trades as TMPV.
"""

PORTFOLIO = [
    ("RELIANCE", "Reliance Industries", "Energy & Conglomerate", False),
    ("HDFCBANK", "HDFC Bank", "Banking", True),
    ("ICICIBANK", "ICICI Bank", "Banking", True),
    ("SBIN", "State Bank of India", "Banking", True),
    ("INFY", "Infosys", "IT Services", False),
    ("TCS", "Tata Consultancy Services", "IT Services", False),
    ("KPITTECH", "KPIT Technologies", "IT Services", False),
    ("TMPV", "Tata Motors Passenger Vehicles", "Automobiles", False),
    ("MARUTI", "Maruti Suzuki India", "Automobiles", False),
    ("M&M", "Mahindra & Mahindra", "Automobiles", False),
    ("LT", "Larsen & Toubro", "Infrastructure", False),
    ("ITC", "ITC", "FMCG", False),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG", False),
    ("SUNPHARMA", "Sun Pharmaceutical Industries", "Pharmaceuticals", False),
    ("BHARTIARTL", "Bharti Airtel", "Telecom", False),
    ("NTPC", "NTPC", "Power", False),
    ("TITAN", "Titan Company", "Consumer Discretionary", False),
    ("ASIANPAINT", "Asian Paints", "Consumer Discretionary", False),
    ("DIXON", "Dixon Technologies (India)", "Electronics Manufacturing", False),
    ("POLYCAB", "Polycab India", "Capital Goods", False),
]

ADHOC = [
    ("TRENT", "Trent", "Retail", False),
    ("PERSISTENT", "Persistent Systems", "IT Services", False),
    ("HAL", "Hindustan Aeronautics", "Defence", False),
    ("BAJFINANCE", "Bajaj Finance", "NBFC", True),
    ("DMART", "Avenue Supermarts", "Retail", False),
]

ALL = PORTFOLIO + ADHOC
