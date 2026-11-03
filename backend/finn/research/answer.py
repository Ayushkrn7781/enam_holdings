"""Ask FINN: query router + grounded answers + citation verification.

Router (deterministic, zero-cost) picks an engine per question:
  metric      -> structured financials + Decimal maths (no LLM arithmetic)
  quarters    -> structured multi-quarter table
  guidance    -> promise-vs-delivered scorecard
  health      -> financial-health checks
  narrative   -> hybrid retrieval over primary documents + LLM synthesis with [n] citations
Every numeric sentence in an LLM answer is checked against the cited excerpts; unverifiable sentences are flagged.
"""
from __future__ import annotations

import re
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Company, ResearchLog
from ..services import llm
from ..services.numbers import fmt_pct, growth_pct, margin_pct
from ..services.results import periods, results_card
from . import guidance, health, retrieval

NOT_VERIFIED = "I could not verify this claim from the available primary documents."

ROUTES = [
    ("guidance", r"guid|promis|deliver|target|outlook|forecast|commit|kept (their|its) word|credib|indicated|said (earlier|last)|"
                 r"\b(meet|met|hit|miss|missed|achieve|achieved|beat)\b.{0,40}(\d+\s*%|expectation|plan)"),
    ("quarters", r"last (four|4|few) quarters|quarter[- ]on[- ]quarter|compare.*quarters|quarterly trend|each quarter"),
    ("metric", r"^(what|how much|how many).{0,40}(revenue|sales|ebitda|pat|net profit|profit|margin|pbt)\b(?!.*\bwhy\b)|\b(qoq|yoy)\b|growth (in|of) (revenue|pat|profit|ebitda)|(revenue|pat|profit|ebitda) growth"),
    ("health", r"\bdebt\b|leverage|borrow|cash flow|cash conversion|working capital|balance sheet|receivable|inventory|financial health|red flag"),
]
ROUTE_LABEL = {
    "metric": "Structured financials · deterministic maths",
    "quarters": "Structured financials · multi-quarter",
    "guidance": "Transcripts → guidance vs. reported actuals",
    "health": "Financial statements · health rules + filings",
    "narrative": "Hybrid retrieval over annual reports & transcripts",
}


def route(question: str) -> str:
    q = question.lower()
    for name, pat in ROUTES:
        if re.search(pat, q):
            return name
    return "narrative"


def _cite(chunk, hit=None) -> dict:
    d = chunk.document
    return {
        "document": d.title, "doc_type": d.doc_type, "period": d.period_label, "page": chunk.page, "section": chunk.section,
        "speaker": chunk.speaker, "excerpt": chunk.text[:500], "url": d.url, "source": d.source,
        "score": hit.score if hit else None,
    }


def _table_cite(ticker: str, s: Session, ptype="Q") -> dict:
    ps = periods(s, ticker, ptype)
    p = ps[-1] if ps else None
    return {"document": f"Reported {'quarterly' if ptype == 'Q' else 'annual'} financials ({p.basis if p else ''})", "doc_type": "financials",
            "period": p.label if p else None, "page": None, "excerpt": None, "url": p.source_url if p else None, "source": p.source if p else None}


def answer(s: Session, ticker: str, question: str) -> dict:
    t0 = time.time()
    r = route(question)
    if r == "metric":
        out = _metric_answer(s, ticker, question)
    elif r == "quarters":
        out = _quarters_answer(s, ticker)
    elif r == "guidance":
        out = _guidance_answer(s, ticker)
    elif r == "health":
        out = _health_answer(s, ticker, question)
    else:
        out = _narrative_answer(s, ticker, question)
    out.update({"route": r, "route_label": ROUTE_LABEL[r], "ticker": ticker, "question": question,
                "latency_ms": int((time.time() - t0) * 1000), "retrieval_mode": retrieval.mode()})
    s.add(ResearchLog(ticker=ticker, question=question, route=r, answer={k: out[k] for k in ("answer", "engine", "confidence")}, latency_ms=out["latency_ms"]))
    s.commit()
    return out


# ------------------------------------------------------------------ structured routes

def _metric_answer(s, ticker, q) -> dict:
    card = results_card(s, ticker)
    if not card:
        return _empty("No reported quarterly financials available for this company.")
    want = [m for m in ("revenue", "ebitda", "pbt", "pat") if re.search({"revenue": r"revenue|sales|top", "ebitda": r"ebitda|operating", "pbt": r"pbt|before tax", "pat": r"pat|net profit|profit(?! before)"}[m], q.lower())] or ["revenue", "ebitda", "pbt", "pat"]
    lines = []
    for row in card["rows"]:
        if row["metric"] in want:
            if row["current"] is None:
                lines.append(f"**{row['label']}**: N/A{(' — ' + row['note']) if row['note'] else ''}")
            else:
                lines.append(f"**{row['label']}** {card['period']}: ₹{row['current']:,.0f} Cr — QoQ {fmt_pct(row['qoq_pct'])} (vs ₹{row['previous'] or 0:,.0f} Cr in {card['previous_period']}), YoY {fmt_pct(row['yoy_pct'])} (vs ₹{row['year_ago'] or 0:,.0f} Cr in {card['year_ago_period']}) [1]")
    m = card["margins"]
    if "margin" in q.lower() and m["ebitda_margin"] is not None and m["ebitda_margin_yoy"] is not None:
        lines.append(f"**EBITDA margin** {m['ebitda_margin']:.1f}% vs {m['ebitda_margin_yoy']:.1f}% a year ago ({m['ebitda_margin_change_bps_yoy']:+d} bps) [1]")
    return {"answer": "\n".join(lines), "engine": "deterministic", "citations": [_table_cite(ticker, s)],
            "data": card, "confidence": _conf(1.0, 1.0, 1.0, card["source"]), "verification": {"numeric": "computed in Python (Decimal) from reported figures"}}


def _quarters_answer(s, ticker) -> dict:
    qs = periods(s, ticker, "Q")[-5:]
    if len(qs) < 2:
        return _empty("Fewer than two reported quarters available.")
    rows = []
    for prev, cur in zip(qs, qs[1:]):
        rows.append(f"**{cur.label}**: revenue ₹{cur.metrics.get('revenue') or 0:,.0f} Cr ({fmt_pct(growth_pct(cur.metrics.get('revenue'), prev.metrics.get('revenue')))} QoQ), "
                    f"EBITDA margin {margin_pct(cur.metrics.get('ebitda'), cur.metrics.get('revenue')) or 'N/A'}%, PAT ₹{cur.metrics.get('pat') or 0:,.0f} Cr ({fmt_pct(growth_pct(cur.metrics.get('pat'), prev.metrics.get('pat')))} QoQ) [1]")
    return {"answer": "\n".join(rows), "engine": "deterministic", "citations": [_table_cite(ticker, s)],
            "confidence": _conf(1.0, 1.0, 1.0, qs[-1].source), "verification": {"numeric": "computed in Python from reported figures"}}


def _guidance_answer(s, ticker) -> dict:
    sc = guidance.scorecard(s, ticker, interpret=True)
    if sc["status"] != "ok":
        return _empty(sc["message"])
    cites, lines = [], []
    for r in [x for x in sc["rows"] if x["status"] in ("missed", "exceeded", "achieved")][:5]:
        cites.append({"document": r["citation"]["document"], "doc_type": "transcript", "period": r["said_in"], "page": r["citation"]["page"],
                      "excerpt": r["statement"], "url": r["citation"]["url"], "source": r["citation"]["source"], "speaker": r["speaker"]})
        tgt = f"{r['target_low']:g}" + (f"–{r['target_high']:g}" if r["target_high"] not in (None, r["target_low"]) else "") + (r["unit"] or "")
        lines.append(f"- {r['metric_label']} for {r['horizon']}: guided {tgt} on the {r['said_in']} call → actual {r['actual']:.1f}{r['unit'] or ''} — **{r['status']}** [{len(cites)}]")
    body = sc["interpretation"]["text"] + ("\n\n" + "\n".join(lines) if lines else "")
    return {"answer": body, "engine": "deterministic grading" + (" + LLM interpretation" if sc["interpretation"]["method"].startswith("llm") else ""),
            "citations": cites, "data": sc, "confidence": _conf(0.9, 1.0 if cites else 0.4, 1.0, cites[0]["source"] if cites else None),
            "verification": {"quotes": "verbatim-checked against transcript chunks", "numeric": "actuals computed in Python"}}


def _health_answer(s, ticker, q) -> dict:
    h = health.analyse(s, ticker)
    if not h["checks"]:
        return _empty(h.get("note", "Not enough annual data."))
    want = []
    ql = q.lower()
    for c in h["checks"]:
        p = c["pillar"].lower()
        if (("debt" in ql or "lever" in ql or "borrow" in ql) and p == "leverage") or ("cash" in ql and p == "cash quality") or \
           (("working capital" in ql or "receivable" in ql or "inventory" in ql) and p == "working capital") or ("risk" in ql and p == "disclosed risks"):
            want.append(c)
    want = want or [c for c in h["checks"] if c["label"] in ("elevated", "monitor")] or h["checks"][:4]
    lines = [f"Overall: **{h['overall'].upper()}** — {h['overall_reason']}"]
    cites = [_table_cite(ticker, s, "Y")]
    for c in want[:6]:
        val = "" if c["current"] is None else f" {c['current']:,.1f}{c['unit'] if c['unit'] in ('%', '×') else ' ' + c['unit']}"
        ev = ""
        if c.get("evidence"):
            cites.append({"document": c["evidence"]["document"], "doc_type": "annual_report", "page": c["evidence"]["page"], "excerpt": c["evidence"]["excerpt"], "url": c["evidence"]["url"], "source": "pdf"})
            ev = f" [{len(cites)}]"
        else:
            ev = " [1]"
        lines.append(f"- **{c['metric']}**{val} · {c['label']} ({c['direction']}) — {c['interpretation']}{ev}")
    return {"answer": "\n".join(lines), "engine": "deterministic rules", "citations": cites, "data": h,
            "confidence": _conf(0.9, 1.0, h["data_completeness"], cites[0]["source"]), "verification": {"numeric": "ratios computed in Python"}}


# ------------------------------------------------------------------ narrative RAG

BUSINESS_Q = re.compile(r"what does .* do|business model|segments?|products?|revenue mix|customers|what .* sell", re.I)


def _narrative_answer(s, ticker, q) -> dict:
    from ..models import Document

    n_docs = s.scalar(select(func.count()).select_from(Document).where(Document.ticker == ticker, Document.status == "indexed"))
    if not n_docs:
        return _empty(NOT_VERIFIED + " No primary documents are indexed for this company yet — run document ingestion first.")
    # metadata filter: business-description questions are answered from the annual report first
    hits = retrieval.search(s, ticker, q, k=6, doc_types=["annual_report"]) if BUSINESS_Q.search(q) else []
    hits = hits or retrieval.search(s, ticker, q, k=6)
    if not hits:
        return _empty(NOT_VERIFIED + " Nothing relevant was found in the indexed annual reports and transcripts.")
    cites = [_cite(c, h) for c, h in hits]
    top_rel = min(1.0, (hits[0][1].bm25_rank is not None) * 0.6 + 0.4 * (len(hits) / 6))
    if llm.available():
        ctx = "\n\n".join(f"[{i+1}] {c['document']} ({c['period'] or ''}, p.{c['page']}{', ' + c['speaker'] if c['speaker'] else ''}):\n{c['excerpt']}" for i, c in enumerate(cites))
        tier = "fast" if re.search(r"what does .* do|business|segments?|products?", q, re.I) else "strong"
        text = llm.complete(
            [
                {"role": "system", "content": "You are FINN, an equity research assistant. Answer ONLY from the numbered excerpts of the company's own annual reports and earnings-call transcripts. "
                 "Cite every factual sentence with [n]. Do not use outside knowledge, news or broker views. Do not do arithmetic — quote numbers exactly as they appear. "
                 f"If the excerpts do not answer the question, say exactly: \"{NOT_VERIFIED}\" Be concise: <=120 words, plain sentences or short bullets."},
                {"role": "user", "content": f"Question: {q}\n\nExcerpts:\n{ctx}"},
            ],
            tier=tier,
            max_tokens=400,
        )
        if text:
            ver = verify(text, cites)
            cov = ver["cited_sentences"] / max(1, ver["sentences"])
            return {"answer": ver["text"], "engine": f"hybrid retrieval + LLM ({tier} tier)", "citations": cites,
                    "confidence": _conf(top_rel, cov, ver["numeric_ok"], cites[0]["source"]), "verification": ver}
    # no-LLM fallback: extractive answer — best sentences from the top passages, each cited
    qt = set(retrieval.tokenize(retrieval.expand(q))) - {"company", "does", "what", "do", "how", "has", "have", "management", "its", "much"}
    picks = []
    for i, c in enumerate(cites[:4]):
        sents = retrieval.split_sentences(c["excerpt"])
        ranked = sorted(sents, key=lambda x: (-len(qt & set(retrieval.tokenize(x))), not re.search(r"\d", x)))
        for best in ranked[:2]:
            if len(qt & set(retrieval.tokenize(best))) >= 1:
                picks.append(f"- {best.strip()} [{i+1}]")
        if len(picks) >= 4:
            break
    if not picks:
        for i, c in enumerate(cites[:2]):
            lead = " ".join(retrieval.split_sentences(c["excerpt"])[:2]).strip()
            if lead:
                picks.append(f"- {lead} [{i+1}]")
    body = "Most relevant passages from primary documents (extractive — LLM not configured):\n" + "\n".join(picks) if picks else NOT_VERIFIED
    return {"answer": body, "engine": "hybrid retrieval (extractive)", "citations": cites,
            "confidence": _conf(top_rel, 1.0 if picks else 0, 1.0, cites[0]["source"]), "verification": {"mode": "extractive — every line is a verbatim excerpt"}}


_NUMTOK = re.compile(r"(?<![\w.])(\d[\d,]*\.?\d*)\s*(%|cr|crore|bps)?", re.I)


def verify(text: str, cites: list[dict]) -> dict:
    """Check [n] markers point at real excerpts and that numbers in each sentence occur in its cited excerpts."""
    sents = [x for line in text.split("\n") for x in retrieval.split_sentences(line) if x.strip()]
    out_lines, n_cited, n_num, n_num_ok, bad = [], 0, 0, 0, []
    for sent in sents:
        refs = [int(x) for x in re.findall(r"\[(\d+)\]", sent)]
        valid = [r for r in refs if 1 <= r <= len(cites)]
        if valid:
            n_cited += 1
        nums = [m.group(1).replace(",", "") for m in _NUMTOK.finditer(re.sub(r"\[\d+\]", "", sent)) if len(m.group(1).replace(",", "").strip(".")) > 1]
        flag = False
        if nums:
            n_num += 1
            pool = " ".join((cites[r - 1]["excerpt"] or "") for r in valid).replace(",", "")
            if valid and all(n.rstrip(".") in pool for n in nums):
                n_num_ok += 1
            else:
                flag = True
                bad.append(sent.strip())
        if refs and not valid:
            flag = True
        out_lines.append(sent + (" ⚠︎ *unverified*" if flag else ""))
    return {"text": "\n".join(out_lines) if "\n" in text else " ".join(out_lines), "sentences": len(sents), "cited_sentences": n_cited,
            "numeric_sentences": n_num, "numeric_ok": (n_num_ok / n_num) if n_num else 1.0, "unverified": bad}


def _conf(relevance: float, coverage: float, numeric: float, source: str | None) -> dict:
    src_q = 0.6 if source == "demo" else 1.0
    score = round(0.3 * relevance + 0.3 * coverage + 0.25 * numeric + 0.15 * src_q, 2)
    label = "high" if score >= 0.8 else "medium" if score >= 0.55 else "low"
    return {"label": label, "score": score, "factors": {"retrieval_relevance": round(relevance, 2), "evidence_coverage": round(coverage, 2),
            "numeric_verification": round(numeric, 2), "source_quality": src_q},
            "note": "Heuristic evidence score, not a calibrated probability."}


def _empty(msg: str) -> dict:
    return {"answer": msg, "engine": "none", "citations": [], "confidence": {"label": "low", "score": 0, "factors": {}, "note": "No evidence."}, "verification": {}}


# ------------------------------------------------------------------ research view

def overview(s: Session, ticker: str) -> dict:
    co = s.get(Company, ticker)
    ys = periods(s, ticker, "Y")
    qs = periods(s, ticker, "Q")
    traj = None
    if len(ys) >= 2:
        n = len(ys) - 1
        from ..services.numbers import cagr_pct

        traj = {
            "years": [y.label for y in ys],
            "series": [{"label": y.label, "revenue": y.metrics.get("revenue"), "pat": y.metrics.get("pat"), "ebitda": y.metrics.get("ebitda"),
                        "ebitda_margin": margin_pct(y.metrics.get("ebitda"), y.metrics.get("revenue")), "pat_margin": margin_pct(y.metrics.get("pat"), y.metrics.get("revenue")),
                        "cfo": y.metrics.get("cfo"), "borrowings": y.metrics.get("borrowings")} for y in ys],
            "revenue_cagr": cagr_pct(ys[-1].metrics.get("revenue"), ys[0].metrics.get("revenue"), n),
            "pat_cagr": cagr_pct(ys[-1].metrics.get("pat"), ys[0].metrics.get("pat"), n),
            "n_years": n,
        }
        m0, m1 = margin_pct(ys[0].metrics.get("ebitda"), ys[0].metrics.get("revenue")), margin_pct(ys[-1].metrics.get("ebitda"), ys[-1].metrics.get("revenue"))
        bits = [f"Revenue compounded {traj['revenue_cagr']}% a year over {n} years" if traj["revenue_cagr"] is not None else None,
                f"PAT {traj['pat_cagr']}%" if traj["pat_cagr"] is not None else None,
                f"EBITDA margin moved from {m0}% to {m1}%" if m0 is not None and m1 is not None and not (co and co.is_financial) else None]
        traj["takeaway"] = "; ".join(b for b in bits if b) + "."
    business = _business(s, ticker, co)
    latest_y = ys[-1] if ys else None
    ttm = None
    if len(qs) >= 4:
        last4 = qs[-4:]
        ttm = {k: round(sum((q.metrics.get(k) or 0) for q in last4), 1) for k in ("revenue", "ebitda", "pat")}
        ttm["label"] = f"TTM to {last4[-1].label}"
        ttm["ebitda_margin"] = margin_pct(ttm["ebitda"], ttm["revenue"])
    fin_snap = None
    if latest_y:
        m = latest_y.metrics
        fin_snap = {"period": latest_y.label, "revenue": m.get("revenue"), "ebitda_margin": margin_pct(m.get("ebitda"), m.get("revenue")),
                    "pat": m.get("pat"), "pat_margin": margin_pct(m.get("pat"), m.get("revenue")), "roe": m.get("roe"), "roce": m.get("roce"),
                    "debt_to_equity": round(m["borrowings"] / m["net_worth"], 2) if m.get("borrowings") is not None and m.get("net_worth") else None,
                    "ttm": ttm, "source": latest_y.source, "source_url": latest_y.source_url}
    return {
        "ticker": ticker,
        "company": {"name": co.name if co else ticker, "sector": co.sector if co else None, "is_financial": bool(co and co.is_financial)},
        "business": business,
        "financial_snapshot": fin_snap,
        "trajectory": traj,
        "latest_quarter": results_card(s, ticker),
    }


def _business(s, ticker, co) -> dict:
    hits = retrieval.search(s, ticker, "business overview what we do segments products customers revenue mix", k=3, doc_types=["annual_report"])
    cites = [_cite(c, h) for c, h in hits]
    if hits and llm.available():
        ctx = "\n\n".join(f"[{i+1}] {c['excerpt']}" for i, c in enumerate(cites))
        text = llm.complete([
            {"role": "system", "content": "From these annual-report excerpts only, describe in <=60 words what the company does, its segments and revenue mix. Cite [n]. No outside knowledge."},
            {"role": "user", "content": ctx}], tier="fast", max_tokens=160)
        if text:
            return {"text": verify(text, cites)["text"], "citations": cites, "method": "llm"}
    if hits:
        return {"text": cites[0]["excerpt"][:420] + " [1]", "citations": cites[:1], "method": "extractive"}
    return {"text": (co.about if co and co.about else "No annual report indexed yet — run ingestion for this ticker."), "citations": [], "method": "profile"}


def bull_bear(s: Session, ticker: str) -> dict:
    h = health.analyse(s, ticker)
    sc = guidance.scorecard(s, ticker, interpret=False)
    facts = [f"{c['metric']}: {c['current']} {c['unit']} ({c['label']}, {c['direction']})" for c in h.get("checks", []) if c["current"] is not None]
    if sc.get("summary"):
        facts.append(f"Guidance hit rate: {sc['summary']['hit_rate_pct']}% of {sc['summary']['graded']} graded; revisions: {len(sc['summary']['revisions'])}")
    hits = retrieval.search(s, ticker, "outlook opportunities growth drivers risks threats headwinds competition", k=6)
    cites = [_cite(c, hh) for c, hh in hits]
    if llm.available() and (facts or cites):
        ctx = "\n".join(f"- {f}" for f in facts) + "\n\n" + "\n\n".join(f"[{i+1}] {c['excerpt']}" for i, c in enumerate(cites))
        out = llm.complete_json([
            {"role": "system", "content": "Write a tight bull and bear case (3 bullets each, <=22 words per bullet) using ONLY the computed metrics and numbered primary-document excerpts. "
             "Cite excerpts as [n]; metrics need no citation. No outside knowledge, no price targets, no recommendation. "
             'Reply JSON {"bull":[str],"bear":[str]}'},
            {"role": "user", "content": ctx}], tier="strong", max_tokens=500)
        if out and out.get("bull"):
            chk = lambda xs: [verify(x, cites)["text"] for x in xs if isinstance(x, str)]  # noqa: E731
            return {"bull": chk(out["bull"]), "bear": chk(out.get("bear", [])), "citations": cites, "method": "llm (strong tier), numbers checked against excerpts"}
    fmt = lambda c: f"{c['current']:,.1f}{c['unit'] if c['unit'] in ('%', '×') else ' ' + c['unit']}"  # noqa: E731
    quant = [c for c in h.get("checks", []) if c["pillar"] != "Disclosed risks" and c["current"] is not None]
    bull = [f"{c['metric']} {fmt(c)} ({c['direction']}) — {c['interpretation']}" for c in quant if c["label"] == "stable"][:3]
    bear = [f"{c['metric']} {fmt(c)} ({c['direction']}, {c['label']}) — {c['interpretation']}" for c in sorted(quant, key=lambda c: c["label"] != "elevated") if c["label"] in ("elevated", "monitor")][:3]
    if sc.get("summary", {}).get("repeated_misses"):
        bear.append(f"Repeated guidance misses on {', '.join(sc['summary']['repeated_misses'])}")
    return {"bull": bull or ["Not enough evidence for a bull case."], "bear": bear or ["No health checks flagged."], "citations": [], "method": "deterministic from health checks"}
