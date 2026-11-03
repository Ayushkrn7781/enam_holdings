"""Announcement taxonomy + rule-based classifier.

Rules run first (free, instant, explainable). Only filings the rules leave as `unclassified`
*and* whose exchange label is not obviously routine are sent to the cheap LLM tier.
New categories are added by appending to CATEGORIES and RULES — nothing else changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import llm

CATEGORIES: dict[str, dict] = {
    "results": {"label": "Results", "importance": 90},
    "M&A": {"label": "M&A", "importance": 85},
    "management_change": {"label": "Management change", "importance": 75},
    "fund_raise": {"label": "Fund raise", "importance": 70},
    "litigation": {"label": "Litigation / regulatory", "importance": 70},
    "pledging": {"label": "Promoter pledge", "importance": 70},
    "credit_rating": {"label": "Credit rating", "importance": 55},
    "capex": {"label": "Capex", "importance": 65},
    "bonus_split": {"label": "Bonus / split", "importance": 55},
    "insider_trading": {"label": "Insider trade", "importance": 50},
    "press_release": {"label": "Press release", "importance": 40},
    "dividend": {"label": "Dividend", "importance": 40},
    "earnings_call": {"label": "Earnings call", "importance": 35},
    "agm_egm": {"label": "AGM / EGM", "importance": 25},
    "postal_ballot": {"label": "Postal ballot", "importance": 20},
    "investor_meetings": {"label": "Investor meeting", "importance": 15},
    "unclassified": {"label": "Routine", "importance": 5},
}

# (category, subtype, pattern). Order matters: first match wins.
RULES: list[tuple[str, str, str]] = [
    ("pledging", "pledge", r"\bpledg|encumbrance"),
    ("insider_trading", "insider", r"insider trading|regulation 7\(2\)|sast|disclosure under sebi \(prohibition of insider|acquisition of shares by promoter|sale of shares by promoter"),
    ("earnings_call", "transcript", r"transcript"),
    ("earnings_call", "recording", r"audio recording|video recording|recording of (the )?(earnings|conference|analyst)"),
    ("earnings_call", "notice", r"earnings call|conference call|con\. call|concall"),
    ("investor_meetings", "meet", r"analyst|institutional investor|investor meet|investor conference|non-deal roadshow|one-on-one"),
    ("results", "board_notice", r"board meeting.{0,80}(consider|approve).{0,60}(financial )?results|intimation of board meeting.{0,40}result"),
    ("results", "results", r"financial results?|quarterly results?|unaudited.{0,30}results|audited.{0,30}results|results for the (quarter|year)|outcome of board meeting.{0,60}result|investor presentation|earnings (release|update)|shareholders'? letter"),
    ("M&A", "deal", r"acqui(re|sition)|amalgamation|merger|demerger|scheme of arrangement|joint venture|\bjv\b|stake (sale|purchase)|divest|incorporation of (a )?(wholly owned )?subsidiary|investment in (wholly owned )?subsidiar"),
    ("management_change", "kmp", r"chief executive|\bceo\b|chief financial|\bcfo\b|managing director|\bmd\b|whole[- ]time director|chief operating|\bcoo\b|change in (directors|key managerial|management)|resignation of|appointment of|cessation|re-?appointment|company secretary|compliance officer"),
    ("fund_raise", "raise", r"\bqip\b|qualified institution|rights issue|preferential (issue|allotment)|buy-?back|non-convertible debenture|\bncds?\b|commercial paper|fund rais|raising of funds|issue of (equity|securities)"),
    ("credit_rating", "rating", r"credit rating|\brating\b.{0,40}(crisil|icra|care|india ratings|brickwork|fitch|moody|s&p)|(crisil|icra|care ratings|india ratings)"),
    ("litigation", "regulatory", r"usfda|form 483|warning letter|import alert|official action indicated|\boai\b"),
    ("litigation", "legal", r"litigation|penalty|show cause|\bsebi order|tribunal|\bnclt\b|insolvency|court|arbitration|tax demand|\bgst\b.{0,30}(demand|order)|regulatory action|fine imposed|search and seizure|\braid\b"),
    ("bonus_split", "corp_action", r"bonus|stock split|sub-?division|split of (equity )?shares"),
    ("dividend", "dividend", r"dividend"),
    ("capex", "capex", r"capex|capital expenditure|capacity expansion|new (plant|facility|factory|unit)|greenfield|brownfield|commissioning|commercial (production|operation)"),
    ("postal_ballot", "ballot", r"postal ballot|e-?voting result|scrutini[sz]er"),
    ("agm_egm", "meeting", r"annual general meeting|\bagm\b|extra-?ordinary general meeting|\begm\b|book closure"),
    ("press_release", "order", r"order (win|received|inflow)|bags? (an )?order|letter of award|contract (award|win)|secures"),
    ("press_release", "news", r"press release|launch|partnership|collaborat|clarification|media release|update on"),
]

ROUTINE = re.compile(
    r"trading window|esop|esos|esps|allotment of (equity )?shares under|regulation 74\(5\)|compliance certificate|"
    r"loss of share certificate|duplicate share|newspaper (publication|advertisement)|copy of newspaper|"
    r"spurious|investor complaints|reconciliation of share capital|certificate under|brsr|business responsibility|"
    r"sustainability report|esg|secretarial compliance|appointment of (statutory |secretarial |cost |internal )auditor|"
    r"record date for interest|change in registrar|transfer of shares to iepf",
    re.I,
)


@dataclass
class Classification:
    category: str
    subtype: str
    method: str  # rules | llm | routine


def classify(subject: str, exchange_category: str | None = None, body: str | None = None) -> Classification:
    text = " ".join(filter(None, [exchange_category, subject, (body or "")[:600]])).lower()
    head = " ".join(filter(None, [exchange_category, subject])).lower()
    if ROUTINE.search(head):
        return Classification("unclassified", "routine", "routine")
    # Subject first (most precise), then the exchange's own label, then the body text.
    for blob in (subject.lower(), (exchange_category or "").lower(), text):
        for cat, sub, pat in RULES:
            if blob and re.search(pat, blob, re.I):
                return Classification(cat, sub, "rules")
    return _llm_classify(subject, body) or Classification("unclassified", "other", "rules")


def _llm_classify(subject: str, body: str | None) -> Classification | None:
    if not llm.available():
        return None
    cats = ", ".join(CATEGORIES)
    out = llm.complete_json(
        [
            {
                "role": "system",
                "content": "You classify Indian stock-exchange corporate announcements. "
                f"Allowed categories: {cats}. Reply JSON: {{\"category\": ...}}. Use 'unclassified' for routine compliance paperwork.",
            },
            {"role": "user", "content": f"Subject: {subject}\n\nText: {(body or '')[:1200]}"},
        ],
        tier="fast",
        max_tokens=40,
    )
    if out and out.get("category") in CATEGORIES:
        return Classification(out["category"], "llm", "llm")
    return None


def subtype_importance(category: str, subtype: str, text: str) -> tuple[int, str]:
    """Category importance with explainable sub-type adjustments. Returns (score, reason)."""
    base = CATEGORIES.get(category, CATEGORIES["unclassified"])["importance"]
    t = text.lower()
    if category == "results" and subtype == "board_notice":
        return 30, "board-meeting notice for results (date only, no numbers)"
    if category == "management_change":
        if re.search(r"chief executive|\bceo\b|managing director|\bmd\b|chief financial|\bcfo\b", t):
            return 92, "CEO/MD/CFO-level change"
        if re.search(r"company secretary|compliance officer", t):
            return 30, "company secretary / compliance officer change"
        if re.search(r"independent director", t):
            return 45, "independent director change"
    if category == "credit_rating":
        if "downgrad" in t or "negative" in t:
            return 85, "rating downgrade / negative outlook"
        if "upgrad" in t or "positive" in t:
            return 65, "rating upgrade / positive outlook"
        if "reaffirm" in t:
            return 20, "rating reaffirmed (no change)"
    if category == "fund_raise":
        if "commercial paper" in t:
            return 30, "routine commercial-paper issuance"
        if "buyback" in t or "buy-back" in t or "buy back" in t:
            return 78, "buyback (capital return)"
    if category == "pledging" and re.search(r"release|revocation", t):
        return 40, "pledge released"
    if category == "litigation" and subtype == "regulatory":
        if re.search(r"warning letter|import alert|official action indicated", t):
            return 85, "USFDA warning letter / import alert"
        return 60, "regulatory inspection observations"
    if category == "earnings_call" and subtype == "transcript":
        return 45, "transcript available (primary source for guidance)"
    if category == "press_release" and subtype == "order":
        return 60, "order win"
    return base, f"{CATEGORIES.get(category, {}).get('label', category)} base weight"


# Scheduled or recurring paperwork: by definition not "news", so novelty is capped.
SCHEDULED_SUBTYPES = {"board_notice", "routine", "meeting", "ballot", "meet", "recording", "notice"}
