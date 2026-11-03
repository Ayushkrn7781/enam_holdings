"""Signal engine: turns raw filings into ranked, explained signals.

classify -> dedupe -> enrich (results card / appointee bio / amounts) -> score -> explain
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AlertRule, Announcement, Company, Holding, Meta
from . import enrich, market, materiality, results, taxonomy
from .numbers import fmt_pct, growth_pct

log = logging.getLogger("finn.signals")

QUESTIONS = {
    "results": [
        "Was the YoY change driven by volume, price or mix? (check the concall)",
        "Did margins move because of input costs or one-offs/exceptional items?",
        "How does this quarter compare with what management guided last quarter?",
    ],
    "management_change": [
        "Is the departure planned succession or abrupt (check stated reason & effective date)?",
        "Does the incoming person come from inside the company or a peer?",
        "Any other KMP changes in the last 12 months?",
    ],
    "M&A": ["What valuation multiple is being paid?", "How is it funded — cash, debt or equity?", "Does it change the segment mix materially?"],
    "fund_raise": ["How dilutive is it at the issue price?", "What is the stated use of proceeds?", "Is the balance sheet stretched (check D/E)?"],
    "litigation": ["What is the maximum financial exposure vs. net worth?", "Is it provided for or a contingent liability?", "Is this a recurring dispute?"],
    "credit_rating": ["What drove the rating action?", "Does it change borrowing costs on existing debt?"],
    "pledging": ["What % of promoter holding is now pledged?", "Why does the promoter need the borrowing?"],
    "capex": ["What is the capex vs. current gross block?", "Expected payback / commissioning timeline?", "Funded by internal accruals or debt?"],
    "insider_trading": ["Size of the trade vs. the insider's total holding?", "Open-market or off-market?"],
    "press_release": ["Is the order/contract size disclosed and material vs. revenue?", "Execution timeline?"],
    "dividend": ["Payout ratio vs. history?", "Record date?"],
    "bonus_split": ["No cash value change — check the record date for share-count adjustment."],
    "earnings_call": ["Read the guidance section of the transcript (FINN extracts it in Research → Promise vs delivered)."],
}

IMPLICATIONS = {
    "management_change": "Leadership transitions at CEO/CFO level can change capital-allocation and reporting priorities; markets often re-rate on the successor's track record.",
    "M&A": "Could change the growth profile, segment mix and leverage depending on size and funding.",
    "fund_raise": "Equity raises dilute existing holders; buybacks return cash; debt raises add leverage.",
    "litigation": "Potential cash outflow or provision if the matter goes against the company.",
    "credit_rating": "Rating changes affect the cost of borrowing and can signal lender views on balance-sheet strength.",
    "pledging": "Rising promoter pledges raise the risk of forced selling if the share price falls.",
    "capex": "Adds capacity and future revenue potential, at the cost of near-term free cash flow.",
    "insider_trading": "Insider buying/selling can reflect views on valuation, though trades have many motives.",
    "press_release": "Order wins add to revenue visibility if material relative to annual sales.",
    "dividend": "Cash returned to shareholders; signals confidence in cash generation.",
    "bonus_split": "No change to the company's value; may improve liquidity.",
    "earnings_call": "Primary source for management guidance and tone.",
}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in {"the", "and", "for", "with", "under", "regulation", "sebi", "limited", "ltd"}}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _weights(s: Session) -> dict:
    m = s.get(Meta, "materiality_weights")
    return m.value if m else materiality.DEFAULT_WEIGHTS


def process(s: Session, force: bool = False) -> int:
    """Score every unprocessed announcement. Idempotent."""
    q = select(Announcement).order_by(Announcement.published_at)
    if not force:
        q = q.where(Announcement.score.is_(None))
    anns = s.scalars(q).all()
    holdings = set(s.scalars(select(Holding.ticker)).all())
    watched = {r.category for r in s.scalars(select(AlertRule).where(AlertRule.kind == "category", AlertRule.enabled)).all()}
    weights = _weights(s)
    price_cache: dict[str, list] = {}
    n = 0
    for a in anns:
        try:
            _process_one(s, a, holdings, watched, weights, price_cache)
            n += 1
        except Exception:  # one bad filing must never break the feed
            log.exception("failed to process announcement %s", a.id)
            a.category = a.category or "unclassified"
            a.score, a.priority = 0, "low"
    s.commit()
    return n


def _process_one(s: Session, a: Announcement, holdings, watched, weights, price_cache) -> None:
    text = a.attachment_text or a.body or ""
    c = taxonomy.classify(a.subject, a.exchange_category, text)
    a.category, a.category_method = c.category, c.method
    imp, imp_reason = taxonomy.subtype_importance(c.category, c.subtype, f"{a.subject} {text[:1500]}")

    # --- dedupe & novelty against this company's earlier filings (90d) ---
    prior = s.scalars(
        select(Announcement).where(
            Announcement.ticker == a.ticker,
            Announcement.id != a.id,
            Announcement.published_at < a.published_at,
            Announcement.published_at >= a.published_at - timedelta(days=90),
        )
    ).all()
    toks = _tokens(a.subject)
    # novelty compares like with like: a results filing is not "old news" because its board-meeting notice came first
    comparable = [p for p in prior if (p.enrichment or {}).get("subtype") in (None, c.subtype)]
    sims = [(_jaccard(toks, _tokens(p.subject)), p) for p in comparable]
    max_sim, twin = max(sims, key=lambda x: x[0], default=(0.0, None))
    if twin and max_sim > 0.85 and (a.published_at - twin.published_at) < timedelta(days=2):
        a.is_duplicate_of = twin.id
    same_cat = [p for p in prior if p.category == c.category]
    days_since = (a.published_at - max(p.published_at for p in same_cat)).days if same_cat else None

    # --- enrichment ---
    enrichment: dict = {"subtype": c.subtype}
    card = None
    if c.category == "results" and c.subtype != "board_notice":
        card = _results_for(s, a)
        if card:
            enrichment["results"] = card
    if c.category == "management_change":
        enrichment["management"] = enrich.management_change(a.subject, text)
    amount = enrich.extract_amount_cr(f"{a.subject} {text[:4000]}") if c.category not in ("results", "dividend") else None
    if amount:
        enrichment["amount_cr"] = amount

    # --- components ---
    annual = results.periods(s, a.ticker, "Y")
    annual_rev = annual[-1].metrics.get("revenue") if annual else None
    qs = results.periods(s, a.ticker, "Q")
    yoy_hist = []
    for i, q in enumerate(qs):
        base = next((b for b in qs[:i] if b.period_end.year == q.period_end.year - 1 and b.period_end.month == q.period_end.month), None)
        if base:
            yoy_hist.append(growth_pct(q.metrics.get("pat"), base.metrics.get("pat")))
    if card:
        yoy_hist = yoy_hist[:-1]  # exclude the quarter being scored
    if a.ticker not in price_cache:
        price_cache[a.ticker] = market.series(s, a.ticker)
    react = market.reaction(price_cache[a.ticker], a.published_at.date() + (timedelta(days=1) if a.published_at.hour >= 16 else timedelta(0)))
    if react:
        enrichment["reaction"] = react

    comps = {
        "category": materiality.Component(imp, imp_reason),
        "financial": materiality.financial_impact(c.category, card, amount, annual_rev),
        "deviation": materiality.deviation(card, yoy_hist[-8:], react),
        "relevance": materiality.relevance(a.ticker in holdings, c.category in watched and c.subtype != "board_notice"),
        "novelty": materiality.novelty(max_sim, days_since),
    }
    if c.subtype in taxonomy.SCHEDULED_SUBTYPES:
        comps["novelty"] = materiality.Component(min(comps["novelty"].value, 30), "scheduled / recurring filing — expected, not news")
    if imp < 40 and comps["deviation"].value > 25:
        comps["deviation"] = materiality.Component(25, comps["deviation"].reason + " — capped: a low-importance filing is unlikely to explain the move")
    if c.category == "unclassified":
        comps["financial"] = materiality.Component(0, "routine filing")
        comps["deviation"] = materiality.Component(min(comps["deviation"].value, 20), comps["deviation"].reason)
        comps["novelty"] = materiality.Component(min(comps["novelty"].value, 10), "routine compliance paperwork")
    total, breakdown = materiality.score(comps, weights)
    if a.is_duplicate_of:
        total = min(total, 10)
        breakdown["duplicate_of"] = a.is_duplicate_of
    a.score, a.priority, a.score_breakdown = total, materiality.priority_for(total), breakdown

    a.summary, method = enrich.one_line_summary(a.subject, text, c.category)
    if card:
        a.summary = _results_sentence(card) or a.summary
    enrichment["summary_method"] = method
    enrichment["why"] = _explain(s, a, c.category, card, comps, same_cat, react, enrichment)
    enrichment["questions"] = QUESTIONS.get(c.category, [])
    a.enrichment = enrichment


def _results_for(s: Session, a: Announcement) -> dict | None:
    pages = (a.attachment_text or "").split("\f") if a.attachment_text else []
    filing = results.parse_results_pages(pages) if pages else None
    if pages and not filing:
        filing = results.llm_parse_results(pages)
    qs = results.periods(s, a.ticker, "Q")
    cand = [q for q in qs if q.period_end <= a.published_at.date() and (a.published_at.date() - q.period_end).days <= 80]
    if cand:
        card = results.results_card(s, a.ticker, cand[-1].period_end)
        return results.reconcile(card, filing) if card else None
    if filing:
        card = results.card_from_filing(filing, "Latest quarter", a.attachment_url)
        card["verification"] = {"status": "single_source", "detail": f"Parsed from the filing (p.{filing['page']}, {filing['method']}); structured table not yet updated."}
        return card
    return None


def _results_sentence(card: dict) -> str | None:
    r = {x["metric"]: x for x in card["rows"]}

    def p(k):
        v = r[k]["yoy_pct"]
        return "N/A" if v is None else f"{v:+.1f}%"

    if r["revenue"]["current"] is None:
        return None
    return f"{card['period']}: revenue {p('revenue')} YoY, PAT {p('pat')} YoY" + (
        f"; EBITDA margin {card['margins']['ebitda_margin']:.1f}%" if card.get("margins", {}).get("ebitda_margin") is not None else ""
    ) + "."


def _explain(s: Session, a: Announcement, cat: str, card, comps, same_cat, react, enrichment) -> dict:
    facts = [a.summary or a.subject]
    if card:
        for r in card["rows"]:
            if r["current"] is not None:
                facts.append(f"{r['label']} ₹{r['current']:,.0f} Cr — QoQ {fmt_pct(r['qoq_pct'])}, YoY {fmt_pct(r['yoy_pct'])}")
    if "management" in enrichment:
        for p in enrichment["management"]["people"]:
            if p.get("name"):
                facts.append(f"{p['name']} — {p.get('role') or 'role n/a'} ({p.get('change')})" + (f", effective {p['effective']}" if p.get("effective") else ""))
    if enrichment.get("amount_cr"):
        facts.append(f"Amount disclosed: ₹{enrichment['amount_cr']:,.0f} Cr")

    implication = IMPLICATIONS.get(cat)
    if card:
        m = card.get("margins", {})
        bps = m.get("ebitda_margin_change_bps_yoy")
        implication = (
            "Headline growth and margin direction set the tone for earnings estimates."
            + (f" EBITDA margin {'expanded' if bps > 0 else 'contracted'} {abs(bps)} bps YoY." if bps else "")
        )
    fin = comps["financial"]
    unusual = [comps["deviation"].reason, comps["novelty"].reason]
    history = []
    if same_cat:
        history.append(f"{len(same_cat)} earlier '{cat}' filing(s) from this company in the last 90 days; most recent {max(p.published_at for p in same_cat):%d %b %Y}.")
    else:
        history.append("No similar filing from this company in the last 90 days.")
    if card and card.get("trend"):
        pats = [t["pat"] for t in card["trend"] if t.get("pat") is not None]
        if len(pats) >= 4:
            history.append(f"PAT over the last {len(pats)} quarters: " + ", ".join(f"{x:,.0f}" for x in pats) + " (₹ Cr).")
    uncertain = []
    if not a.attachment_text:
        uncertain.append("Filing attachment text not available — summary is from the subject line only.")
    if card and card.get("verification", {}).get("status") != "verified":
        uncertain.append(card.get("verification", {}).get("detail", "Numbers from a single source."))
    if card and card.get("flags"):
        uncertain.extend(card["flags"])
    if cat == "management_change":
        uncertain.append("Bio is as disclosed in the filing; verify via the LinkedIn search link.")
    if not react:
        uncertain.append("No end-of-day market reaction available yet for this date.")
    if a.source == "demo":
        uncertain.insert(0, "ILLUSTRATIVE DEMO DATA — not a real filing.")
    return {
        "what_happened": facts,
        "implication": implication,
        "implication_is_inference": True,
        "is_it_unusual": unusual,
        "financial_size": fin.reason,
        "history": history,
        "uncertain": uncertain,
    }


def company_name(s: Session, ticker: str) -> str:
    c = s.get(Company, ticker)
    return c.name if c else ticker
