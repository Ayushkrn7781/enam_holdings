"""Research Q&A: a deterministic router, grounded answers with citations, and a numeric verifier."""
from __future__ import annotations

import re
import time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, Document, ResearchLog
from ..services import llm
from ..services import numbers as N
from ..services.results import periods as fin_periods, results_card
from . import guidance, health, retrieval
from .periods import fy_label, quarter_label

NOT_VERIFIED = "I could not verify this claim from the available primary documents."

ROUTES = [
    ("guidance", re.compile(r"guid|promis|\bdeliver(s|ed|ing)?\b|target|outlook|forecast|commit|kept (their|its) word|credib|indicated|"
                            r"said (earlier|last)|\b(meet|met|hit|miss|missed|achieve|achieved|beat)\b.{0,40}"
                            r"(\d+\s*%|expectation|plan)", re.I)),
    ("quarters", re.compile(r"last (four|4|few) quarters|quarter-on-quarter|compare.*quarters|quarterly trend|each quarter",
                            re.I)),
    ("metric", re.compile(r"^(what|how much|how many).{0,40}(revenue|sales|ebitda|pat|net profit|profit|margin|pbt)\b"
                          r"(?!.*\bwhy\b)(?!\s+mix)(?!.*\bsegments?\b)|\b(qoq|yoy)\b|growth (in|of) (revenue|sales|ebitda|pat|profit|pbt)|"
                          r"(revenue|pat|profit|ebitda|pbt) growth", re.I)),
    ("health", re.compile(r"\bdebt\b|leverage|borrow|cash flow|cash conversion|working capital|balance sheet|receivable|"
                          r"inventory|financial health|red flag", re.I)),
]
ROUTE_LABELS = {
    "metric": "Structured financials · deterministic maths",
    "quarters": "Structured financials · multi-quarter",
    "guidance": "Transcripts → guidance vs. reported actuals",
    "health": "Financial statements · health rules + filings",
    "narrative": "Hybrid retrieval over annual reports & transcripts",
}
BUSINESS_Q = re.compile(r"what does .* do|business model|segments?|products?|revenue mix|customers", re.I)


def route(question: str) -> str:
    q = question.strip()
    for name, rx in ROUTES:
        if rx.search(q):
            return name
    return "narrative"


# ---------------------------------------------------------------- verification
_NUM_TOK = re.compile(r"\d[\d,]*(?:\.\d+)?")


def verify(text: str, cites: list[dict]) -> dict:
    """Per sentence: [n] must resolve, and every number (>1 digit) must appear in the cited excerpts."""
    sentences = retrieval.split_sentences(text)
    out_sents, unverified = [], []
    for s in sentences:
        refs = [int(x) for x in re.findall(r"\[(\d+)\]", s)]
        ok = True
        if any(r < 1 or r > len(cites) for r in refs):
            ok = False
        clean = re.sub(r"\[\d+\]", "", s)
        nums = [n.replace(",", "") for n in _NUM_TOK.findall(clean) if len(n.replace(",", "").replace(".", "")) > 1]
        if nums and ok:
            pool = " ".join(cites[r - 1]["text"] for r in refs if 1 <= r <= len(cites)) if refs else ""
            pool = pool.replace(",", "")
            if not refs or any(n not in pool for n in nums):
                ok = False
        if not ok and s.strip() != NOT_VERIFIED:
            unverified.append(s)
            s = s + " ⚠︎ *unverified*"
        out_sents.append(s)
    return {"text": " ".join(out_sents), "sentences": len(sentences), "unverified": len(unverified),
            "unverified_sentences": unverified}


def confidence(retrieval_rel: float, coverage: float, numeric: float, demo: bool) -> dict:
    sq = 0.6 if demo else 1.0
    v = 0.3 * retrieval_rel + 0.3 * coverage + 0.25 * numeric + 0.15 * sq
    label = "high" if v >= 0.8 else "medium" if v >= 0.55 else "low"
    return {"label": label, "value": round(v, 2),
            "factors": {"retrieval_relevance": round(retrieval_rel, 2), "evidence_coverage": round(coverage, 2),
                        "numeric_verification": round(numeric, 2), "source_quality": sq},
            "note": "Evidence strength from four factors; not a calibrated probability."}


def _fin_cite(card_or_rows, ticker: str, label: str) -> dict:
    src = card_or_rows.get("source", "demo") if isinstance(card_or_rows, dict) else "demo"
    return {"n": 1, "document": f"{ticker} reported financials ({label})", "doc_type": "financials", "period": label,
            "page": None, "speaker": None, "text": "Structured quarterly financials table", "url": None, "source": src}


# ---------------------------------------------------------------- routes
def _metric(s: Session, ticker: str, q: str) -> dict:
    card = results_card(s, ticker)
    if not card:
        return {"answer": NOT_VERIFIED + " No structured financials are loaded for this company.", "citations": [],
                "engine": "deterministic"}
    want = [k for k in ("revenue", "ebitda", "pbt", "pat") if re.search(
        {"revenue": r"revenue|sales|topline", "ebitda": r"ebitda|operating|margin", "pbt": r"pbt|before tax",
         "pat": r"\bpat\b|net profit|profit after|\bprofit\b(?!.*before)"}[k], q, re.I)]
    if not want:
        want = ["revenue", "ebitda", "pbt", "pat"]
    lines = []
    for r in card["rows"]:
        if r["key"] not in want:
            continue
        if r["current"] is None:
            lines.append(f"- **{r['label']}** {card['period_label']}: N/A. {r.get('note') or ''} [1]")
            continue
        lines.append(f"- **{r['label']}** {card['period_label']}: {N.fmt_cr(r['current'])} — QoQ {N.fmt_pct(r['qoq'])} "
                     f"(vs {N.fmt_cr(r['previous'])} in {card['previous_label']}), YoY {N.fmt_pct(r['yoy'])} "
                     f"(vs {N.fmt_cr(r['year_ago'])} in {card['year_ago_label']}) [1]")
    mg = card["margins"]
    if re.search(r"margin|ebitda", q, re.I) and mg.get("ebitda_margin") is not None:
        lines.append(f"- **EBITDA margin** {mg['ebitda_margin']:.1f}% vs {mg['ebitda_margin_year_ago']:.1f}% a year ago "
                     f"({mg['ebitda_margin_yoy_bps']:+d} bps) [1]")
    return {"answer": "\n".join(lines), "citations": [_fin_cite(card, ticker, card["period_label"])],
            "engine": "deterministic", "data": card}


def _quarters(s: Session, ticker: str) -> dict:
    qs = fin_periods(s, ticker, "Q")[-6:]
    if len(qs) < 2:
        return {"answer": NOT_VERIFIED + " Not enough quarterly history is loaded.", "citations": [],
                "engine": "deterministic"}
    lines = []
    for prev, cur in list(zip(qs, qs[1:]))[-5:]:
        m, p = cur.metrics or {}, prev.metrics or {}
        em = N.margin_pct(m.get("ebitda"), m.get("revenue"))
        lines.append(f"- **{quarter_label(cur.period_end)}**: revenue {N.fmt_cr(m.get('revenue'))} "
                     f"(QoQ {N.fmt_pct(N.growth_pct(m.get('revenue'), p.get('revenue')))}), EBITDA margin "
                     f"{'N/A' if em is None else f'{em:.1f}%'}, PAT {N.fmt_cr(m.get('pat'))} "
                     f"(QoQ {N.fmt_pct(N.growth_pct(m.get('pat'), p.get('pat')))}) [1]")
    label = f"{quarter_label(qs[1].period_end)}–{quarter_label(qs[-1].period_end)}"
    return {"answer": "\n".join(lines), "citations": [_fin_cite({"source": qs[-1].source}, ticker, label)],
            "engine": "deterministic"}


def _guidance(s: Session, ticker: str) -> dict:
    sc = guidance.scorecard(s, ticker)
    if sc["status"] != "ok":
        return {"answer": NOT_VERIFIED + " " + sc["interpretation"], "citations": [], "engine": "deterministic",
                "data": sc}
    graded = [r for r in sc["rows"] if r["status"] in ("missed", "exceeded", "achieved")][:5]
    cites, lines = [], [sc["interpretation"], ""]
    for i, r in enumerate(graded, 1):
        cites.append({"n": i, "document": r["citation"]["document"], "doc_type": "transcript",
                      "period": r["said_in"], "page": r["citation"]["page"], "speaker": r["speaker"],
                      "text": r["statement"], "url": r["citation"]["url"], "source": r["citation"]["source"],
                      "document_id": r["citation"]["document_id"]})
        act = f"{r['actual']:.1f}%" if r["actual"] is not None else "n/a"
        lines.append(f"- **{r['metric_label']} {r['horizon']}** ({r['said_in']} call): guided {r['target']}, "
                     f"reported {act}: **{r['status']}** [{i}]")
    return {"answer": "\n".join(lines).strip(), "citations": cites,
            "engine": sc.get("interpretation_method", "deterministic"), "data": {"summary": sc["summary"]}}


_PILLAR_Q = [(r"\bdebt\b|leverage|borrow|balance sheet", "Leverage"), (r"cash", "Cash quality"),
             (r"working capital|receivable|inventory", "Working capital"), (r"risk|red flag", "Disclosed risks")]


def _health(s: Session, ticker: str, q: str) -> dict:
    h = health.assess(s, ticker)
    if not h["checks"]:
        return {"answer": NOT_VERIFIED + " " + h["reason"], "citations": [], "engine": "deterministic"}
    pillars = [p for rx, p in _PILLAR_Q if re.search(rx, q, re.I)]
    chosen = [c for c in h["checks"] if c["pillar"] in pillars] if pillars else \
        [c for c in h["checks"] if c["label"] in ("elevated", "monitor")]
    chosen = chosen or h["checks"][:4]
    cites = [{"n": 1, "document": f"{ticker} reported annual financials", "doc_type": "financials",
              "period": h["years"][-1] if h.get("years") else None, "page": None, "speaker": None,
              "text": "Structured annual financials", "url": None, "source": h.get("source", "demo")}]
    lines = [f"Overall: **{h['overall']}**. {h['reason']}", ""]
    for c in chosen:
        ref = 1
        if c.get("evidence"):
            cites.append({"n": len(cites) + 1, "document": c["evidence"]["document"], "doc_type": "annual_report",
                          "period": None, "page": c["evidence"]["page"], "speaker": None,
                          "text": c["evidence"]["excerpt"], "url": c["evidence"]["url"], "source": c["source"],
                          "document_id": c["evidence"]["document_id"]})
            ref = len(cites)
        lines.append(f"- **{c['metric']}** ({c['label']}): {c['interpretation']} [{ref}]")
    if h.get("lender_note"):
        lines.append("")
        lines.append(h["lender_note"])
    return {"answer": "\n".join(lines).strip(), "citations": cites, "engine": "deterministic"}


def _extractive(q: str, hits: list[dict]) -> tuple[str, list[dict]]:
    """Best sentences from the top passages. Prose beats number-dense tables; a matching section heading
    means the whole passage is on topic, so its lead sentences are quoted."""
    qt = set(retrieval.tokenize(q))
    top = max(h["bm25"] for h in hits)
    strong = [h for h in hits if h["bm25"] >= 0.4 * top]  # drop filler that only matched a stray word
    prose = [h for h in strong if h.get("kind") != "table"]
    use = (prose or strong)[:4]
    lines = ["Most relevant passages from primary documents (extractive — LLM not configured):", ""]
    for i, h in enumerate(use, 1):
        sents = retrieval.split_sentences(h["text"])
        if set(retrieval.tokenize(retrieval.expand_query(q))) & set(retrieval.tokenize(h.get("section") or "")):
            best = sents[:3]
        else:
            scored = sorted(sents, key=lambda x: (-len(qt & set(retrieval.tokenize(x))), not re.search(r"\d", x)))
            best = [x for x in scored[:2] if qt & set(retrieval.tokenize(x))] or sents[:2]
            best.sort(key=sents.index)
        lines.append(f"- {' '.join(best)} [{i}]")
    return "\n".join(lines), use


def _narrative(s: Session, ticker: str, q: str) -> dict:
    docs = s.scalars(select(Document).where(Document.ticker == ticker, Document.status == "indexed")).all()
    if not docs:
        return {"answer": f"{NOT_VERIFIED} No primary documents are indexed for this company yet — run document "
                          "ingestion first.", "citations": [], "engine": "deterministic", "status": "NOT_VERIFIED"}
    hits = []
    if BUSINESS_Q.search(q):
        hits = retrieval.search(s, ticker, q, k=6, doc_types=["annual_report"])
    if not hits:
        hits = retrieval.search(s, ticker, q, k=6)
    hits = [h for h in hits if h["bm25"] > 1.0]
    if not hits:
        return {"answer": f"{NOT_VERIFIED} Nothing relevant was found in the indexed annual reports and transcripts.",
                "citations": [], "engine": "deterministic", "status": "NOT_VERIFIED"}
    cites = [{"n": i, **{k: h[k] for k in ("document", "doc_type", "period", "page", "speaker", "text", "url", "source",
                                          "document_id", "chunk_id", "section", "relevance")}} for i, h in enumerate(hits, 1)]
    if llm.available():
        excerpts = "\n\n".join(f"[{c['n']}] {c['document']} p.{c['page']}"
                               f"{' (' + c['speaker'] + ')' if c['speaker'] else ''}: {c['text']}" for c in cites)
        out = llm.complete([
            {"role": "system", "content": "You answer investor questions using ONLY the numbered excerpts from a "
                                          "company's primary documents. Put [n] after every factual sentence. Do not use "
                                          "outside knowledge. Do not calculate anything; quote numbers exactly as written. "
                                          f"If the excerpts do not answer the question, reply exactly: {NOT_VERIFIED} "
                                          "Maximum 120 words."},
            {"role": "user", "content": f"Company: {ticker}\nQuestion: {q}\n\nExcerpts:\n{excerpts}"},
        ], tier="fast" if BUSINESS_Q.search(q) else "strong", max_tokens=400)
        if out:
            v = verify(out.strip(), cites)
            return {"answer": v["text"], "citations": cites, "engine": "llm", "verification": v}
    text, used = _extractive(q, hits)
    ids = [h["chunk_id"] for h in used]
    ordered = [next(c for c in cites if c["chunk_id"] == cid) for cid in ids]
    for n, c in enumerate(ordered, 1):
        c["n"] = n
    return {"answer": text, "citations": ordered, "engine": "extractive"}


def answer(s: Session, ticker: str, question: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    comp = s.get(Company, ticker)
    r = route(question)
    if r == "metric":
        out = _metric(s, ticker, question)
    elif r == "quarters":
        out = _quarters(s, ticker)
    elif r == "guidance":
        out = _guidance(s, ticker)
    elif r == "health":
        out = _health(s, ticker, question)
    else:
        out = _narrative(s, ticker, question)
    cites = out.get("citations", [])
    ver = out.get("verification") or (verify(out["answer"], cites) if out.get("engine") == "llm" else None)
    demo = any(c.get("source") == "demo" for c in cites) or (comp is not None and comp.source == "demo")
    if not cites:
        conf = confidence(0.0, 0.0, 0.0, demo)
    else:
        rel = max((c.get("relevance", 1.0) if isinstance(c.get("relevance"), float) else 1.0) for c in cites)
        n_sent = max(1, len(retrieval.split_sentences(out["answer"])))
        cited = sum(1 for x in retrieval.split_sentences(out["answer"]) if re.search(r"\[\d+\]", x))
        coverage = min(1.0, cited / n_sent) if out.get("engine") != "deterministic" else 1.0
        numeric = 1.0 - (ver["unverified"] / max(1, ver["sentences"]) if ver else 0.0)
        conf = confidence(rel if out.get("engine") in ("llm", "extractive") else 1.0, coverage, numeric, demo)
    latency = round((time.perf_counter() - t0) * 1000, 1)
    res = {"ticker": ticker, "question": question, "route": r, "route_label": ROUTE_LABELS[r],
           "answer": out["answer"], "citations": cites, "engine": out.get("engine"), "confidence": conf,
           "verification": ver, "latency_ms": latency, "status": out.get("status", "OK"),
           "data_mode": "demo" if demo else "live"}
    try:
        with s.begin_nested():
            s.add(ResearchLog(ticker=ticker, question=question, route=r, answer=out["answer"][:4000], latency_ms=latency,
                              source=out.get("engine") or "rules"))
    except Exception:
        pass
    return res


# ---------------------------------------------------------------- overview + bull/bear
def overview(s: Session, ticker: str) -> dict[str, Any]:
    comp = s.get(Company, ticker)
    biz: dict[str, Any] = {"text": comp.about if comp else None, "citations": [], "method": "company profile"}
    hits = retrieval.search(s, ticker, "business overview segments products revenue mix what the company does", k=4,
                            doc_types=["annual_report"])
    if hits:
        cites = [{"n": i, **{k: h[k] for k in ("document", "doc_type", "period", "page", "text", "url", "source",
                                              "document_id", "section")}} for i, h in enumerate(hits, 1)]
        text = None
        if llm.available():
            out = llm.complete([
                {"role": "system", "content": "Summarise what the company does in at most 60 words using ONLY the "
                                              "excerpts. Put [n] after each sentence. No outside knowledge."},
                {"role": "user", "content": "\n\n".join(f"[{c['n']}] {c['text']}" for c in cites)},
            ], tier="fast", max_tokens=160)
            if out:
                text = verify(out.strip(), cites)["text"]
                biz["method"] = "llm"
        if not text:
            first = [retrieval.split_sentences(h["text"])[:2] for h in hits[:2]]
            text = " ".join(" ".join(f) + f" [{i}]" for i, f in enumerate(first, 1))
            biz["method"] = "extractive"
        biz["text"], biz["citations"] = text, cites[:2] if biz["method"] == "extractive" else cites
    ys = fin_periods(s, ticker, "Y")
    qs = fin_periods(s, ticker, "Q")
    lender = bool(comp and comp.is_financial)
    fin = None
    if ys:
        m = ys[-1].metrics or {}
        fin = {"period": fy_label(ys[-1].period_end), "revenue": m.get("revenue"),
               "ebitda_margin": None if lender else N.margin_pct(m.get("ebitda"), m.get("revenue")),
               "pat": m.get("pat"), "pat_margin": N.margin_pct(m.get("pat"), m.get("revenue")),
               "roe": m.get("roe"), "roce": None if lender else m.get("roce"),
               "de": None if lender else N.ratio(m.get("borrowings"), m.get("net_worth")),
               "source": ys[-1].source, "is_financial": lender}
    if len(qs) >= 4 and fin is not None:
        last4 = qs[-4:]
        fin["ttm_revenue"] = sum((q.metrics or {}).get("revenue") or 0 for q in last4)
        fin["ttm_pat"] = sum((q.metrics or {}).get("pat") or 0 for q in last4)
        fin["ttm_label"] = f"TTM to {quarter_label(last4[-1].period_end)}"
    traj = None
    if len(ys) >= 2:
        series = [{"label": fy_label(y.period_end), "revenue": (y.metrics or {}).get("revenue"),
                   "pat": (y.metrics or {}).get("pat"),
                   "ebitda_margin": None if lender else N.margin_pct((y.metrics or {}).get("ebitda"),
                                                                    (y.metrics or {}).get("revenue"))} for y in ys]
        n = len(ys) - 1
        rc = N.cagr_pct(series[-1]["revenue"], series[0]["revenue"], n)
        pc = N.cagr_pct(series[-1]["pat"], series[0]["pat"], n)
        take = f"Revenue compounded {rc:.1f}% a year over {n} years" if rc is not None else "Revenue history is short"
        if pc is not None:
            take += f"; PAT {pc:.1f}%"
        if series[0]["ebitda_margin"] is not None and series[-1]["ebitda_margin"] is not None:
            take += f"; EBITDA margin moved from {series[0]['ebitda_margin']:.1f}% to {series[-1]['ebitda_margin']:.1f}%"
        traj = {"series": series, "revenue_cagr": rc, "pat_cagr": pc, "takeaway": take + "."}
    return {"ticker": ticker, "business": biz, "financials": fin, "trajectory": traj,
            "latest_quarter": results_card(s, ticker)}


def bull_bear(s: Session, ticker: str) -> dict[str, Any]:
    h = health.assess(s, ticker)
    sc = guidance.scorecard(s, ticker)
    if llm.available():
        hits = retrieval.search(s, ticker, "outlook growth risks competition margin strategy", k=6)
        cites = [{"n": i, **{k: x[k] for k in ("document", "doc_type", "period", "page", "text", "url", "source",
                                              "document_id")}} for i, x in enumerate(hits, 1)]
        metrics = "; ".join(f"{c['metric']}: {c['current']}{c['unit'] or ''} ({c['label']})" for c in h["checks"]
                            if c["current"] is not None)
        res = llm.complete_json([
            {"role": "system", "content": "Write a tight bull and bear case for an investor from the computed metrics "
                                          "and numbered excerpts ONLY. Each bullet <=22 words, cite [n] for excerpts. "
                                          "No outside knowledge, no new arithmetic. JSON only."},
            {"role": "user", "content": f"Metrics: {metrics}\nGuidance hit rate: {(sc.get('summary') or {}).get('hit_rate')}\n"
                                        "Excerpts:\n" + "\n".join(f"[{c['n']}] {c['text']}" for c in cites) +
                                        '\nReturn {"bull":["..."x3],"bear":["..."x3]}'},
        ], tier="strong")
        if isinstance(res, dict) and res.get("bull") and res.get("bear"):
            pool = cites + [{"n": len(cites) + 1, "text": metrics}]
            fix = lambda b: verify(str(b), pool)["text"]  # noqa: E731
            return {"ticker": ticker, "bull": [fix(b) for b in res["bull"][:3]], "bear": [fix(b) for b in res["bear"][:3]],
                    "citations": cites, "method": "llm",
                    "note": "Written by the strong model from computed metrics and cited excerpts; numbers verified."}
    bull, bear = [], []
    for c in h["checks"]:
        if c.get("text_detected"):
            continue
        if c["label"] == "stable" and c["current"] is not None:
            bull.append(f"{c['metric']}: {c['interpretation']}")
        elif c["label"] in ("elevated", "monitor"):
            bear.append(f"{c['metric']} ({c['label']}): {c['interpretation']}")
    if sc.get("status") == "ok":
        summ = sc["summary"]
        if summ["repeated_misses"]:
            bear.insert(0, f"Guidance missed repeatedly on {', '.join(summ['repeated_misses'])}.")
        if summ["hit_rate"] is not None and summ["hit_rate"] >= 66:
            bull.insert(0, f"Management met or beat {summ['hit_rate']:.0f}% of gradeable guidance.")
        for rv in sc["revisions"]:
            (bull if rv["direction"] == "up" else bear).append(
                f"{rv['metric_label']} guidance for {rv['horizon']} revised {rv['direction']} ({rv['from']} → {rv['to']}).")
    return {"ticker": ticker, "bull": bull[:3], "bear": bear[:3], "citations": [], "method": "deterministic",
            "note": "Deterministic: bull points from stable checks, bear points from elevated/monitor checks and guidance."}
