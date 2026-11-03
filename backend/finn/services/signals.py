"""Signal pipeline: classify -> dedupe/novelty -> enrich -> score -> summary -> why -> questions."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_meta
from ..models import AlertRule, Announcement, Company, FinancialPeriod, Holding, Price
from ..research.periods import quarter_label
from . import enrich, llm, materiality as M, market, results
from . import numbers as N
from .taxonomy import LABELS, classify, importance

log = logging.getLogger("finn.signals")

IMPLICATION = {
    "results": "Results reset the earnings base the market prices off; a large YoY move usually re-rates estimates.",
    "M&A": "A deal changes what the company owns; watch the price paid, how it is funded and how it shifts the mix.",
    "management_change": "Leadership changes can shift strategy and capital allocation; an abrupt exit is a governance question.",
    "fund_raise": "New capital means dilution or more debt; the use of proceeds decides whether it creates value.",
    "litigation": "A legal or regulatory action can carry a cash cost and, for pharma, can block a plant's exports.",
    "pledging": "Promoter pledging creates forced-selling risk if the share price falls.",
    "capex": "Capex adds capacity ahead of demand; returns depend on utilisation and funding.",
    "credit_rating": "Ratings move the cost of debt; a downgrade is a stress signal, a reaffirmation is not news.",
    "bonus_split": "A bonus or split changes share count, not value.",
    "insider_trading": "Insider sales or buys are weak signals alone but worth tracking in clusters.",
    "press_release": "Order wins and launches matter in proportion to their size against revenue.",
    "dividend": "A dividend returns cash; the size versus earnings says something about confidence.",
    "earnings_call": "The transcript is where management's guidance and tone live; compare it with the numbers.",
    "agm_egm": "Shareholder meetings are procedural unless the agenda carries a material resolution.",
    "postal_ballot": "Postal ballots are procedural unless the resolution itself is material.",
    "investor_meetings": "Investor meetings are scheduled; they rarely carry new information.",
    "unclassified": "Routine compliance paperwork.",
}

QUESTIONS = {
    "results": ["Was the YoY change driven by volume, price or mix?",
                "Did margins move because of input costs or one-offs/exceptional items?",
                "How does this quarter compare with what management guided last quarter?"],
    "management_change": ["Is the departure planned succession or abrupt?",
                          "Does the incoming person come from inside the company or a peer?",
                          "Any other KMP changes in the last 12 months?"],
    "M&A": ["Is the valuation reasonable against the target's revenue and margins?",
            "How is the deal funded (cash, debt or equity)?",
            "How does the target change the revenue mix?"],
    "fund_raise": ["How much dilution or extra leverage does this add?",
                   "What is the stated use of proceeds?",
                   "Where does debt-to-equity go after this?"],
    "litigation": ["What is the maximum cash exposure?", "Has the company provided for it?",
                   "Is this a repeat issue at the same unit or authority?"],
    "credit_rating": ["What drove the rating action?", "Does the outlook change the cost of borrowing?",
                      "How does leverage compare with the agency's trigger?"],
    "pledging": ["What share of promoter holding is now pledged?", "At what price could margin calls start?",
                 "Why does the promoter need the loan?"],
    "capex": ["How is the capex funded?", "What utilisation is needed to earn its cost of capital?",
              "When does the capacity start contributing revenue?"],
    "insider_trading": ["Is this one person or a cluster of insiders?", "How large is it versus their holding?",
                        "Was it inside a trading-window closure?"],
    "press_release": ["How large is this against annual revenue?", "Is it new business or a renewal?",
                      "What margin does this kind of work carry?"],
    "dividend": ["What payout ratio does this imply?", "Is it in line with the stated dividend policy?",
                 "Is the cash coming from operations?"],
    "bonus_split": ["Does this signal anything beyond liquidity?", "What is the record date?",
                    "Any change in the dividend per share after adjustment?"],
    "earnings_call": ["What guidance did management give on this call?", "What did analysts push back on?",
                      "Did any earlier guidance get revised?"],
}


def _price_rows(s: Session, ticker: str) -> list[Price]:
    return s.scalars(select(Price).where(Price.ticker == ticker).order_by(Price.date)).all()


def annual_revenue(s: Session, ticker: str, as_of: datetime) -> Optional[float]:
    ys = [p for p in results.periods(s, ticker, "Y") if p.period_end <= as_of.date()]
    if ys and (ys[-1].metrics or {}).get("revenue"):
        return ys[-1].metrics["revenue"]
    qs = [p for p in results.periods(s, ticker, "Q") if p.period_end <= as_of.date()][-4:]
    if len(qs) == 4 and all((q.metrics or {}).get("revenue") for q in qs):
        return sum(q.metrics["revenue"] for q in qs)
    return None


def reaction_date(published: datetime):
    d = published.date()
    if published.hour >= 16:
        d = d + timedelta(days=1)
    return d


def _pat_z(s: Session, ticker: str, period_end) -> Optional[float]:
    qs = results.periods(s, ticker, "Q")
    by_end = {q.period_end: q for q in qs}
    yoys: list[tuple[Any, float]] = []
    for q in qs:
        ya = next((x for e, x in by_end.items() if abs((q.period_end - timedelta(days=365) - e).days) <= 20), None)
        g = N.growth_pct((q.metrics or {}).get("pat"), (ya.metrics or {}).get("pat") if ya else None)
        if g is not None:
            yoys.append((q.period_end, g))
    cur = next((g for e, g in yoys if e == period_end), None)
    hist = [g for e, g in yoys if e < period_end][-8:]
    if cur is None or len(hist) < 3:
        return None
    return N.zscore(cur, hist)


def _pick_quarter(s: Session, ticker: str, published: datetime) -> Optional[FinancialPeriod]:
    qs = [q for q in results.periods(s, ticker, "Q")
          if q.period_end <= published.date() and (published.date() - q.period_end).days <= 80]
    return qs[-1] if qs else None


def _clean_subject(subj: str) -> str:
    t = re.sub(r"\s+", " ", subj or "").strip()
    return t[:1].upper() + t[1:] if t else t


def _llm_summary(a: Announcement, text: str) -> Optional[str]:
    if not llm.available():
        return None
    out = llm.complete([
        {"role": "system", "content": "Summarise an Indian exchange filing in ONE sentence of at most 28 words. "
                                      "Concrete facts only (who, what, how much, when). No adjectives, no opinion."},
        {"role": "user", "content": f"Company: {a.ticker}\nSubject: {a.subject}\n\n{text[:3000]}"},
    ], tier="fast", max_tokens=80)
    if not out:
        return None
    out = " ".join(out.split())
    return out if len(out.split()) <= 34 else " ".join(out.split()[:28]) + "…"


def _results_summary(card: dict) -> str:
    r = {row["key"]: row for row in card["rows"]}
    parts = [f"revenue {N.fmt_pct(r['revenue']['yoy'])} YoY", f"PAT {N.fmt_pct(r['pat']['yoy'])} YoY"]
    tail = ""
    if card["margins"].get("ebitda_margin") is not None:
        tail = f"; EBITDA margin {card['margins']['ebitda_margin']:.1f}%"
    return f"{card['period_label']}: " + ", ".join(parts) + tail + "."


def _alerted_categories(s: Session, ticker: str) -> set[str]:
    rules = s.scalars(select(AlertRule).where(AlertRule.kind == "category", AlertRule.enabled.is_(True))).all()
    return {r.category for r in rules if r.ticker in (None, ticker)}


def process_one(s: Session, a: Announcement, weights: dict, holdings: set[str]) -> None:
    text = "\n".join(x for x in (a.subject, a.body or "", (a.attachment_text or "")[:4000]) if x)
    cat, sub, method = classify(a.subject, a.exchange_category, a.body)
    a.category, a.subtype, a.category_method = cat, sub, method
    cat_score, cat_reason = importance(cat, sub, f"{a.subject} {a.body or ''}")
    comp = s.get(Company, a.ticker)

    # ---- dedupe + novelty (same company, previous 90 days)
    prior = s.scalars(select(Announcement).where(
        Announcement.ticker == a.ticker, Announcement.id != a.id,
        Announcement.published_at <= a.published_at,
        Announcement.published_at >= a.published_at - timedelta(days=90),
        Announcement.category.is_not(None))).all()
    toks = M.tokens(f"{a.subject} {(a.body or '')[:1000]}")
    max_sim, dup_of, same_cat_14 = 0.0, None, False
    for p in prior:
        sim = M.jaccard(toks, M.tokens(f"{p.subject} {(p.body or '')[:1000]}"))
        if sim > 0.85 and (a.published_at - p.published_at) <= timedelta(days=2) and dup_of is None:
            dup_of = p.id
        if p.subtype == sub:
            max_sim = max(max_sim, sim)
        if p.category == cat and (a.published_at - p.published_at) <= timedelta(days=14):
            same_cat_14 = True
    a.is_duplicate_of = dup_of

    # ---- enrichment
    enr: dict[str, Any] = {}
    rev_yoy = pat_yoy = pat_z = None
    card = None
    if cat == "results" and sub != "board_notice":
        pages = (a.attachment_text or "").split("\f") if a.attachment_text else []
        filing = results.parse_results_pages(pages) if pages else None
        if pages and filing is None:
            filing = results.llm_read_page(pages)
        q = _pick_quarter(s, a.ticker, a.published_at)
        if q is not None:
            card = results.results_card(s, a.ticker, q.period_end)
            card["verification"] = results.reconcile(card, filing)
            pat_z = _pat_z(s, a.ticker, q.period_end)
        elif filing:
            card = results.card_from_filing(filing, a.ticker, a.published_at.date(), bool(comp and comp.is_financial))
        if card:
            rows = {r["key"]: r for r in card["rows"]}
            rev_yoy, pat_yoy = rows["revenue"]["yoy"], rows["pat"]["yoy"]
            enr["results"] = card
    people = []
    if cat == "management_change":
        people = enrich.management_change(text, comp.name if comp else a.ticker)
        enr["people"] = people
    amount = enrich.amount_cr(f"{a.subject}\n{a.body or ''}\n{(a.attachment_text or '')[:3000]}")
    if amount:
        enr["amount_cr"] = amount
    rows = _price_rows(s, a.ticker)
    react = market.reaction(rows, reaction_date(a.published_at)) if rows else None
    enr["reaction"] = react
    ann_rev = annual_revenue(s, a.ticker, a.published_at)

    # ---- components and score
    in_pf = a.ticker in holdings
    comps = {
        "category": {"value": cat_score, "reason": cat_reason},
        "financial": M.financial(cat, sub, amount, ann_rev, rev_yoy, pat_yoy),
        "deviation": M.deviation(cat_score, cat, pat_z, react),
        "relevance": M.relevance(in_pf, cat in _alerted_categories(s, a.ticker), sub),
        "novelty": M.novelty(max_sim, same_cat_14, sub, cat),
    }
    sc, breakdown = M.score(comps, weights)
    if dup_of is not None:
        sc = min(sc, 10.0)
    a.score = sc
    a.priority = M.priority(sc)
    a.score_breakdown = breakdown

    # ---- summary
    if card:
        a.summary = _results_summary(card)
    elif cat != "unclassified" and dup_of is None and (s_llm := _llm_summary(a, text)):
        a.summary = s_llm
        enr["summary_method"] = "llm"
    else:
        a.summary = _clean_subject(a.subject)

    # ---- why should I care
    what: list[str] = []
    if card:
        for r in card["rows"]:
            if r["current"] is None:
                what.append(f"{r['label']}: N/A{' (' + r['note'].split(':')[0] + ')' if r.get('note') else ''}")
            else:
                what.append(f"{r['label']} {N.fmt_cr(r['current'])} — QoQ {N.fmt_pct(r['qoq'])}, YoY {N.fmt_pct(r['yoy'])}")
    for p in people:
        verb = {"joins": "joins as", "leaves": "leaves as", "retires": "retires as"}.get(p.get("change"), "")
        what.append(f"{p['name']} {verb} {p.get('role') or 'officer'}" +
                    (f", effective {p['effective']}" if p.get("effective") else ""))
    if amount:
        what.append(f"Amount disclosed: {N.fmt_cr(amount)}")
    if not what:
        what.append(_clean_subject(a.subject))
    hist_same = [p for p in prior if p.category == cat]
    trend = results.periods(s, a.ticker, "Q")[-8:]
    uncertain = []
    if a.source == "demo":
        uncertain.append("ILLUSTRATIVE DEMO DATA — not a real filing.")
    if not a.attachment_text and cat not in ("unclassified",):
        uncertain.append("No attachment text was read; the summary relies on the subject line.")
    if card and card.get("verification", {}).get("status") not in ("verified",):
        uncertain.append(f"Results not cross-verified: {card.get('verification', {}).get('detail')}")
    if card:
        uncertain += card.get("flags", [])
    if people:
        uncertain.append("Bio as disclosed by the company; not independently verified.")
    if react is None:
        uncertain.append("No end-of-day reaction yet (filed after the last session).")
    enr["why"] = {
        "what_happened": what,
        "implication": IMPLICATION.get(cat, ""),
        "is_it_unusual": [comps["deviation"]["reason"], comps["novelty"]["reason"]],
        "financial_size": comps["financial"]["reason"],
        "history": {"same_category_90d": len(hist_same),
                    "last_same_category": max((p.published_at for p in hist_same), default=None),
                    "pat_last_8q": [{"label": quarter_label(q.period_end), "pat": (q.metrics or {}).get("pat")}
                                    for q in trend]},
        "uncertain": uncertain,
    }
    enr["questions"] = QUESTIONS.get(cat, [])
    enr["category_label"] = LABELS.get(cat, cat)
    a.enrichment = _jsonable(enr)


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_jsonable(v) for v in x]
    if isinstance(x, datetime):
        return x.isoformat()
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return x


def process(s: Session, force: bool = False) -> int:
    weights = M.normalise_weights(get_meta(s, "materiality_weights"))
    holdings = {h.ticker for h in s.scalars(select(Holding)).all()}
    q = select(Announcement).order_by(Announcement.published_at, Announcement.id)
    if force:
        for a in s.scalars(select(Announcement)).all():
            a.category = a.subtype = a.score = a.priority = None
            a.is_duplicate_of = None
        s.flush()
    else:
        q = q.where(Announcement.score.is_(None))
    n = 0
    for a in s.scalars(q).all():
        try:
            process_one(s, a, weights, holdings)
            s.flush()
            n += 1
        except Exception as e:  # one bad filing never breaks the feed
            log.exception("signal processing failed for %s", a.id)
            a.category = a.category or "unclassified"
            a.score, a.priority = 0.0, "low"
            a.summary = _clean_subject(a.subject)
            a.enrichment = {"error": str(e)}
    return n
