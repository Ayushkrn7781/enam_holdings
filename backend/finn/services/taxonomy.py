"""Announcement taxonomy: ordered regex rules, sub-type importance overrides, LLM fallback."""
from __future__ import annotations

import re
from typing import Optional

from . import llm

IMPORTANCE = {
    "results": 90, "M&A": 85, "management_change": 75, "fund_raise": 70, "litigation": 70,
    "pledging": 70, "capex": 65, "credit_rating": 55, "bonus_split": 55, "insider_trading": 50,
    "press_release": 40, "dividend": 40, "earnings_call": 35, "agm_egm": 25, "postal_ballot": 20,
    "investor_meetings": 15, "unclassified": 5,
}

LABELS = {
    "results": "Results", "M&A": "M&A", "management_change": "Management change",
    "fund_raise": "Fund raise", "litigation": "Litigation & regulatory", "pledging": "Promoter pledging",
    "capex": "Capex", "credit_rating": "Credit rating", "bonus_split": "Bonus / split",
    "insider_trading": "Insider trading", "press_release": "Press release", "dividend": "Dividend",
    "earnings_call": "Earnings call", "agm_egm": "AGM / EGM", "postal_ballot": "Postal ballot",
    "investor_meetings": "Investor meetings", "unclassified": "Routine",
}

SCHEDULED_SUBTYPES = {"board_notice", "routine", "meeting", "ballot", "meet", "recording", "notice"}

ROUTINE = re.compile(
    r"trading window|esop|esos|esps|allotment of shares under|regulation 74\s*\(5\)|compliance certificate|"
    r"loss of share certificate|duplicate share|newspaper (publication|advertisement)|copy of newspaper|spurious|"
    r"investor complaints|reconciliation of share capital|certificate under|brsr|business responsibility|"
    r"sustainability report|\besg\b|secretarial compliance|appointment of (statutory|secretarial|cost|internal) auditor|"
    r"record date for interest|change in registrar|iepf", re.I)

_R = lambda p: re.compile(p, re.I)  # noqa: E731

RULES: list[tuple[re.Pattern, str, str]] = [
    (_R(r"pledg|encumbrance"), "pledging", "pledge"),
    (_R(r"regulation 7\s*\(2\)|insider trading|\bsast\b|substantial acquisition of shares"), "insider_trading", "disclosure"),
    (_R(r"transcript"), "earnings_call", "transcript"),
    (_R(r"audio\s*/?\s*video recording|audio recording|video recording"), "earnings_call", "recording"),
    (_R(r"earnings call|conference call|con\.\s*call|concall"), "earnings_call", "notice"),
    (_R(r"analyst|institutional investor|investor meet|investor conference|non-deal roadshow|one-on-one"),
     "investor_meetings", "meet"),
    (_R(r"board meeting.{0,80}(consider|approve).{0,60}results|intimation of board meeting.{0,40}result"),
     "results", "board_notice"),
    (_R(r"financial results?|quarterly results?|unaudited.{0,40}results|audited.{0,40}results|"
        r"results for the (quarter|year)|outcome of board meeting.{0,60}result|investor presentation|"
        r"earnings (release|update)|shareholders'? letter"), "results", "results"),
    (_R(r"acqui(re|sition)|amalgamation|merger|demerger|scheme of arrangement|joint venture|"
        r"stake (sale|purchase)|divest|incorporation of.{0,40}subsidiary|investment in.{0,40}subsidiar"), "M&A", "deal"),
    (_R(r"\bceo\b|\bcfo\b|managing director|whole[- ]time director|\bcoo\b|change in (directors|key managerial|management)|"
        r"resignation of|appointment of|cessation|re-appointment|company secretary|compliance officer"),
     "management_change", "change"),
    (_R(r"\bqip\b|qualified institution|rights issue|preferential|buy-?back|\bncds?\b|non-convertible debenture|"
        r"commercial paper|fund rais|raising of funds|issue of (equity|securities)|basel iii|bonds?\b"), "fund_raise", "raise"),
    (_R(r"credit rating|\bcrisil\b|\bicra\b|care ratings|india ratings|rating agency"), "credit_rating", "rating"),
    (_R(r"usfda|form 483|warning letter|import alert|official action indicated"), "litigation", "regulatory"),
    (_R(r"litigation|penalty|show cause|sebi order|tribunal|\bnclt\b|insolvency|\bcourt\b|arbitration|tax demand|"
        r"gst.{0,40}(demand|order)|regulatory action|search and seizure"), "litigation", "legal"),
    (_R(r"\bbonus\b|stock split|sub-division"), "bonus_split", "corporate_action"),
    (_R(r"dividend"), "dividend", "dividend"),
    (_R(r"\bcapex\b|capital expenditure|capacity expansion|new (plant|facility|factory|unit)|greenfield|brownfield|"
        r"commissioning|commercial (production|operation)"), "capex", "capex"),
    (_R(r"postal ballot|e-voting result|scrutini[sz]er"), "postal_ballot", "ballot"),
    (_R(r"\bagm\b|\begm\b|annual general meeting|book closure"), "agm_egm", "meeting"),
    (_R(r"order (win|received|inflow)|bags.{0,40}order|letter of award|contract (award|win)|secures"),
     "press_release", "order"),
    (_R(r"press release|launch|partnership|collaborat|clarification|media release|update on"), "press_release", "news"),
]


def _match(text: str) -> Optional[tuple[str, str]]:
    for rx, cat, sub in RULES:
        if rx.search(text):
            return cat, sub
    return None


def classify_rules(subject: str, exchange_category: str | None = None, body: str | None = None
                   ) -> Optional[tuple[str, str]]:
    subj = subject or ""
    if ROUTINE.search(subj) or ROUTINE.search(exchange_category or ""):
        return "unclassified", "routine"
    for text in (subj, exchange_category or "", (body or "")[:600]):
        if text and (hit := _match(text)):
            return hit
    return None


def classify(subject: str, exchange_category: str | None = None, body: str | None = None
             ) -> tuple[str, str, str]:
    """Returns (category, subtype, method)."""
    hit = classify_rules(subject, exchange_category, body)
    if hit:
        return hit[0], hit[1], "rules"
    if llm.available():
        cats = ", ".join(k for k in IMPORTANCE)
        out = llm.complete_json([
            {"role": "system", "content": "You classify Indian stock-exchange filings. Reply JSON only."},
            {"role": "user", "content": f"Categories: {cats}.\nFiling subject: {subject}\nExchange label: "
                                        f"{exchange_category}\nBody: {(body or '')[:800]}\n"
                                        'Return {"category": "<one category>"}'},
        ], tier="fast", max_tokens=60)
        cat = (out or {}).get("category") if isinstance(out, dict) else None
        if cat in IMPORTANCE:
            return cat, "llm", "llm"
    return "unclassified", "unknown", "rules"


def importance(category: str, subtype: str, text: str) -> tuple[float, str]:
    """Base importance with sub-type overrides; returns (score, reason)."""
    t = (text or "").lower()
    base = IMPORTANCE.get(category, 5)
    label = LABELS.get(category, category)
    if category == "results" and subtype == "board_notice":
        return 30, "Board-meeting notice for results (scheduled, no numbers yet)"
    if category == "management_change":
        if re.search(r"\b(ceo|cfo|managing director|chief executive|chief financial)\b", t):
            return 92, "Change in CEO / MD / CFO, a top-level role"
        if re.search(r"company secretary|compliance officer", t):
            return 30, "Company secretary / compliance officer change"
        if "independent director" in t:
            return 45, "Independent director change"
    if category == "credit_rating":
        if re.search(r"downgrad|negative outlook|credit watch with negative", t):
            return 85, "Credit rating downgrade or negative outlook"
        if re.search(r"upgrad|positive outlook", t):
            return 65, "Credit rating upgrade or positive outlook"
        if "reaffirm" in t:
            return 20, "Credit rating reaffirmed, no change"
    if category == "fund_raise":
        if "commercial paper" in t:
            return 30, "Commercial paper, routine short-term borrowing"
        if re.search(r"buy-?back", t):
            return 78, "Share buyback"
    if category == "pledging" and re.search(r"releas|revoc", t):
        return 40, "Pledge released"
    if category == "litigation" and subtype == "regulatory":
        if re.search(r"warning letter|import alert|official action indicated|\boai\b", t):
            return 85, "USFDA warning letter / import alert / OAI"
        return 60, "USFDA inspection observations"
    if category == "earnings_call" and subtype == "transcript":
        return 45, "Earnings-call transcript published"
    if category == "press_release" and subtype == "order":
        return 60, "Order win"
    if category == "unclassified":
        return 5, "Routine compliance filing"
    return base, f"{label} filings carry base importance {base}"


def categories() -> list[dict]:
    return [{"key": k, "label": LABELS[k], "importance": v} for k, v in IMPORTANCE.items()]
