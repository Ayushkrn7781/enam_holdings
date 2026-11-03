"""Promise vs delivered: extract management guidance from transcripts, grade it against reported numbers.

Extraction may use the fast LLM, but every statement must be verbatim from the transcript. Grading is
pure Python over structured financials.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Chunk, Document, FinancialPeriod, Guidance
from ..services import llm
from ..services import numbers as N
from ..services.results import periods as fin_periods
from . import periods as P
from .retrieval import split_sentences

KEYWORDS = re.compile(r"guid|expect|target|aim\b|aspire|outlook|confident|we see|we should|should be|will be in the|"
                      r"range of|band of|trajectory|plan to|planning|capex|invest", re.I)
HAS_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent\b|bps\b)|\d[\d,]*(?:\.\d+)?\s*(?:crores?|cr\b)", re.I)
BACKWARD = re.compile(r"last year|\bwas\b|\bwere\b|\bgrew\b|delivered|reported|achieved", re.I)
FORWARD = re.compile(r"expect|guid|target|aim|\bwill\b|should", re.I)

METRIC_LABELS = {"revenue_growth": "Revenue growth", "ebitda_margin": "EBITDA margin", "pat_growth": "PAT growth",
                 "capex": "Capex", "volume": "Volume", "qualitative": "Qualitative"}
TOL = 0.05  # percentage points: rounding only


# ---------------------------------------------------------------- parsing helpers
def parse_target(sentence: str, metric: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    s = sentence
    if metric == "capex":
        m = re.search(r"(?:Rs\.?|₹|INR)\s*([\d,]+(?:\.\d+)?)\s*(?:crores?|cr\b)", s, re.I)
        if m:
            v = float(m.group(1).replace(",", ""))
            return v, v, "INR cr"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*(?:to|–|—|-)\s*(\d+(?:\.\d+)?)\s*(?:%|percent)", s, re.I)
    if m:
        return float(m.group(1)), float(m.group(2)), "%"
    if re.search(r"double[- ]digit", s, re.I):
        return 10.0, None, "%"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", s, re.I)
    if m:
        x = float(m.group(1))
        pre = s[: m.start()].lower()[-40:]
        if re.search(r"at least|minimum|upwards of|more than|\bover\b|above|exceed", pre):
            return x, None, "%"
        if re.search(r"around|about|approximately|~|close to", pre):
            return x - 0.5, x + 0.5, "%"
        return x, x, "%"
    return None, None, None


def detect_metric(sentence: str) -> str:
    s = sentence.lower()
    if re.search(r"ebitda margin|operating margin|ebit margin|\bmargins?\b", s):
        return "ebitda_margin"
    if re.search(r"\bcapex\b|capital expenditure", s):
        return "capex"
    if re.search(r"\bpat\b|net profit|profit after tax|earnings growth", s):
        return "pat_growth"
    if re.search(r"revenue|topline|top line|sales|growth|\bgrow", s):
        return "revenue_growth"
    if re.search(r"volume", s):
        return "volume"
    return "qualitative"


def parse_horizon(sentence: str, said_in: str) -> str:
    m = re.search(r"Q([1-4])\s*FY\s*'?(\d{2})", sentence, re.I)
    if m:
        return f"Q{m.group(1)} FY{m.group(2)}"
    m = re.search(r"FY\s*'?(\d{2})\b", sentence, re.I)
    if m:
        return f"FY{m.group(1)}"
    low = sentence.lower()
    call_fy = P.fy_of_label(said_in)
    if re.search(r"(next|coming|following) quarter", low):
        return P.next_quarter(said_in) or said_in
    if re.search(r"medium[- ]term|long[- ]term|next (2|3|two|three)(\s*(-|to)\s*(3|three))? years", low):
        return "medium term"
    if re.search(r"next year", low) and call_fy:
        return f"FY{call_fy + 1:02d}"
    if call_fy:
        return f"FY{call_fy:02d}"
    return said_in


def commitment_of(sentence: str, lo, hi) -> str:
    if lo is None:
        return "qualitative"
    if re.search(r"guid|target|commit", sentence, re.I):
        return "range" if hi is not None and lo != hi else "explicit_target"
    return "outlook"


def _norm(t: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", (t or "").lower()).split())


def is_verbatim(statement: str, chunk_text: str) -> bool:
    a, b = _norm(statement), _norm(chunk_text)
    if not a:
        return False
    if a in b:
        return True
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    m = sm.find_longest_match(0, len(a), 0, len(b))
    return m.size >= 0.85 * len(a)


# ---------------------------------------------------------------- extraction
def rules_extract(chunk_text: str, said_in: str) -> list[dict]:
    out = []
    for sent in split_sentences(chunk_text):
        if not KEYWORDS.search(sent) or not HAS_NUMBER.search(sent):
            continue
        if BACKWARD.search(sent) and not FORWARD.search(sent):
            continue
        metric = detect_metric(sent)
        lo, hi, unit = parse_target(sent, metric)
        out.append({"statement": sent, "metric": metric if lo is not None else "qualitative",
                    "target_low": lo, "target_high": hi, "unit": unit,
                    "horizon": parse_horizon(sent, said_in), "commitment": commitment_of(sent, lo, hi)})
    return out


def _transcripts(s: Session, ticker: str, limit: int = 4) -> list[Document]:
    docs = s.scalars(select(Document).where(Document.ticker == ticker, Document.doc_type == "transcript",
                                            Document.status == "indexed")).all()
    docs.sort(key=lambda d: (d.period_end or P.quarter_end(1, 0)), reverse=True)
    return docs[:limit]


def _llm_extract(chunks: list[Chunk], said_in: str) -> list[dict]:
    numbered = "\n\n".join(f"[{i}] (page {c.page}, {c.speaker or 'unknown'}) {c.text}" for i, c in enumerate(chunks))
    res = llm.complete_json([
        {"role": "system", "content": "You extract forward-looking management guidance from an earnings-call transcript. "
                                      "Copy each statement VERBATIM (exact words from the chunk). Never turn vague language "
                                      "into numbers. Ignore backward-looking statements. JSON only."},
        {"role": "user", "content": f"Call: {said_in}\nChunks:\n{numbered}\n\nReturn {{\"items\":[{{\"chunk\":<index>,"
                                    "\"statement\":\"verbatim sentence\",\"metric\":\"revenue_growth|ebitda_margin|"
                                    "pat_growth|capex|volume|qualitative\",\"target_low\":number|null,\"target_high\":"
                                    "number|null,\"unit\":\"%|INR cr\"|null,\"horizon\":\"FYxx|Qn FYxx|medium term\","
                                    "\"commitment\":\"explicit_target|range|outlook|qualitative\"}]}"},
    ], tier="fast", max_tokens=2000)
    items = res.get("items") if isinstance(res, dict) else res if isinstance(res, list) else None
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            c = chunks[int(it.get("chunk"))]
        except (TypeError, ValueError, IndexError):
            continue
        stmt = str(it.get("statement") or "")
        if not is_verbatim(stmt, c.text):
            continue  # invented or paraphrased quote: drop it
        metric = it.get("metric") if it.get("metric") in METRIC_LABELS else detect_metric(stmt)
        out.append({"chunk": c, "statement": stmt, "metric": metric, "target_low": _f(it.get("target_low")),
                    "target_high": _f(it.get("target_high")), "unit": it.get("unit"),
                    "horizon": it.get("horizon") or parse_horizon(stmt, said_in),
                    "commitment": it.get("commitment") or "outlook", "method": "llm"})
    return out


def _f(x) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def extract(s: Session, ticker: str) -> int:
    s.execute(delete(Guidance).where(Guidance.ticker == ticker))
    n = 0
    for doc in _transcripts(s, ticker):
        said_in = doc.period_label or "unknown"
        chunks = [c for c in s.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.id)).all()
                  if KEYWORDS.search(c.text) and (c.speaker or "").lower() != "moderator"]
        items: list[dict] = []
        if llm.available() and chunks:
            items = _llm_extract(chunks, said_in)
        if not items:
            for c in chunks:
                for it in rules_extract(c.text, said_in):
                    it.update(chunk=c, method="rules")
                    items.append(it)
        for it in items:
            c: Chunk = it["chunk"]
            s.add(Guidance(ticker=ticker, document_id=doc.id, chunk_id=c.id, page=c.page, said_in=said_in,
                           statement=it["statement"], speaker=c.speaker, metric=it["metric"],
                           target_low=it["target_low"], target_high=it["target_high"], unit=it["unit"],
                           horizon=it["horizon"], commitment=it["commitment"], method=it["method"],
                           source=doc.source))
            n += 1
    s.flush()
    return n


# ---------------------------------------------------------------- grading
def _grade(lo, hi, actual) -> str:
    if hi is None:
        return "achieved" if actual >= lo - TOL else "missed"
    if actual > hi + TOL:
        return "exceeded"
    if actual < lo - TOL:
        return "missed"
    return "achieved"


def _fy_totals(s: Session, ticker: str, fy2: int) -> tuple[Optional[dict], int, str]:
    """Annual metrics for an FY: the annual row, or the sum of its 4 quarters. Returns (metrics, quarters, how)."""
    end = P.fy_end(fy2)
    ys = {p.period_end: p for p in fin_periods(s, ticker, "Y")}
    if end in ys:
        return ys[end].metrics, 4, f"annual {P.fy_label(end)} financials"
    qs = {p.period_end: p for p in fin_periods(s, ticker, "Q")}
    have = [qs[e] for e in P.fy_quarter_ends(fy2) if e in qs]
    if len(have) < 4:
        return None, len(have), ""
    tot: dict[str, float] = {}
    for k in ("revenue", "ebitda", "pat", "pbt"):
        vals = [(q.metrics or {}).get(k) for q in have]
        if all(v is not None for v in vals):
            tot[k] = sum(vals)
    return tot, 4, f"sum of 4 quarters of FY{fy2:02d}"


def _quarter(s: Session, ticker: str, q: int, fy2: int) -> Optional[FinancialPeriod]:
    end = P.quarter_end(q, fy2)
    return next((p for p in fin_periods(s, ticker, "Q") if p.period_end == end), None)


def actual_for(s: Session, ticker: str, metric: str, horizon: str) -> dict:
    """Returns {status_hint, actual, actual_period, how}. status_hint in pending|long_dated|not_comparable|qualitative|ok."""
    if metric == "qualitative" or metric == "volume":
        return {"hint": "qualitative" if metric == "qualitative" else "not_comparable", "how": "Not a reported P&L number"}
    if horizon == "medium term" or not horizon:
        return {"hint": "long_dated", "how": "Medium-term aspiration; not yet testable"}
    pq = P.parse_quarter(horizon)
    if pq:
        q, fy2 = pq
        cur = _quarter(s, ticker, q, fy2)
        if cur is None:
            return {"hint": "pending", "how": f"{horizon} not reported yet"}
        if metric == "capex":
            return {"hint": "not_comparable", "how": "Capex is not in the reported P&L"}
        if metric == "ebitda_margin":
            v = N.margin_pct(cur.metrics.get("ebitda"), cur.metrics.get("revenue"))
            return {"hint": "ok", "actual": v, "actual_period": horizon, "how": f"{horizon} EBITDA ÷ revenue"}
        prev = _quarter(s, ticker, q, fy2 - 1)
        key = "pat" if metric == "pat_growth" else "revenue"
        v = N.growth_pct(cur.metrics.get(key), prev.metrics.get(key) if prev else None)
        if v is None:
            return {"hint": "pending", "how": "Year-ago quarter missing"}
        return {"hint": "ok", "actual": v, "actual_period": horizon,
                "how": f"{horizon} {key.upper() if key == 'pat' else 'revenue'} YoY vs Q{q} FY{fy2 - 1:02d}"}
    fy2 = P.parse_fy(horizon)
    if fy2 is None:
        return {"hint": "long_dated", "how": "Horizon not recognised"}
    cur, k, how = _fy_totals(s, ticker, fy2)
    if cur is None:
        return {"hint": "pending", "how": f"pending — {k}/4 quarters of FY{fy2:02d} reported"}
    if metric == "capex":
        return {"hint": "not_comparable", "how": "Capex is not comparable from reported P&L financials"}
    if metric == "ebitda_margin":
        v = N.margin_pct(cur.get("ebitda"), cur.get("revenue"))
        return {"hint": "ok", "actual": v, "actual_period": f"FY{fy2:02d}", "how": f"EBITDA ÷ revenue, {how}"}
    prev, _, _ = _fy_totals(s, ticker, fy2 - 1)
    key = "pat" if metric == "pat_growth" else "revenue"
    v = N.growth_pct(cur.get(key), (prev or {}).get(key))
    if v is None:
        return {"hint": "pending", "how": "Prior-year base missing"}
    return {"hint": "ok", "actual": v, "actual_period": f"FY{fy2:02d}", "how": f"{key} YoY, {how}"}


def _fmt_target(lo, hi, unit) -> str:
    if lo is None:
        return "—"
    if unit == "INR cr":
        return N.fmt_cr(lo)
    if hi is None:
        return f"≥ {lo:g}%"
    if lo == hi:
        return f"{lo:g}%"
    return f"{lo:g}–{hi:g}%"


def _call_key(label: str) -> tuple:
    pq = P.parse_quarter(label or "")
    return (pq[1], pq[0]) if pq else (0, 0)


def scorecard(s: Session, ticker: str) -> dict[str, Any]:
    gs = s.scalars(select(Guidance).where(Guidance.ticker == ticker)).all()
    docs = {d.id: d for d in s.scalars(select(Document).where(Document.ticker == ticker))}
    if not gs:
        has_tx = any(d.doc_type == "transcript" and d.status == "indexed" for d in docs.values())
        return {"ticker": ticker, "status": "no_guidance" if has_tx else "no_transcripts", "rows": [],
                "summary": None, "chart": [], "revisions": [], "uncertainties": [],
                "interpretation": ("Transcripts are indexed but no quantified guidance was found in them."
                                   if has_tx else "No earnings-call transcripts are indexed for this company yet.")}
    gs.sort(key=lambda g: (_call_key(g.said_in), g.id), reverse=False)
    rows = []
    for g in gs:
        a = actual_for(s, ticker, g.metric, g.horizon or "")
        status = a["hint"]
        variance = None
        actual = a.get("actual")
        if status == "ok":
            if actual is None or g.target_low is None:
                status = "pending"
            else:
                status = _grade(g.target_low, g.target_high, actual)
                if status == "missed":
                    variance = N.rnd(actual - g.target_low)
                elif status == "exceeded":
                    variance = N.rnd(actual - g.target_high)
                else:
                    variance = 0.0
        if g.metric == "qualitative":
            status = "qualitative"
        d = docs.get(g.document_id)
        rows.append({
            "id": g.id, "said_in": g.said_in, "speaker": g.speaker, "statement": g.statement, "metric": g.metric,
            "metric_label": METRIC_LABELS.get(g.metric, g.metric), "target_low": g.target_low,
            "target_high": g.target_high, "unit": g.unit, "target": _fmt_target(g.target_low, g.target_high, g.unit),
            "horizon": g.horizon, "commitment": g.commitment, "actual": actual, "actual_period": a.get("actual_period"),
            "how_computed": a.get("how"), "variance_pp": variance, "status": status, "method": g.method,
            "revised": None,
            "citation": {"document": d.title if d else None, "document_id": g.document_id, "page": g.page,
                         "url": d.url if d else None, "period": g.said_in, "source": d.source if d else g.source},
        })
    # revisions: same (metric, horizon), different target on a later call
    revisions = []
    last: dict[tuple, dict] = {}
    for r in rows:
        if r["target_low"] is None or r["metric"] in ("qualitative",):
            continue
        k = (r["metric"], r["horizon"])
        prev = last.get(k)
        if prev and prev["said_in"] != r["said_in"] and (prev["target_low"], prev["target_high"]) != (r["target_low"], r["target_high"]):
            mid = lambda x: (x["target_low"] + (x["target_high"] if x["target_high"] is not None else x["target_low"])) / 2  # noqa: E731
            direction = "up" if mid(r) > mid(prev) else "down"
            rev = {"metric": r["metric"], "metric_label": r["metric_label"], "horizon": r["horizon"],
                   "direction": direction, "from": prev["target"], "to": r["target"],
                   "from_call": prev["said_in"], "to_call": r["said_in"]}
            revisions.append(rev)
            r["revised"] = direction
        last[k] = r
    graded = [r for r in rows if r["status"] in ("achieved", "exceeded", "missed")]
    met = sum(r["status"] == "achieved" for r in graded)
    beaten = sum(r["status"] == "exceeded" for r in graded)
    missed = sum(r["status"] == "missed" for r in graded)
    counts = {st: sum(r["status"] == st for r in rows) for st in
              ("exceeded", "achieved", "missed", "pending", "long_dated", "not_comparable", "qualitative")}
    miss_by_metric: dict[str, int] = {}
    for r in graded:
        if r["status"] == "missed":
            miss_by_metric[r["metric_label"]] = miss_by_metric.get(r["metric_label"], 0) + 1
    repeated = [m for m, c in miss_by_metric.items() if c >= 2]
    calls = sorted({r["said_in"] for r in rows}, key=_call_key)
    hit_rate = N.rnd((met + beaten) / len(graded) * 100, 0) if graded else None
    summary = {"counts": counts, "graded": len(graded), "met": met, "beaten": beaten, "missed": missed,
               "hit_rate": hit_rate, "revisions": len(revisions), "repeated_misses": repeated,
               "calls_covered": calls}
    chart = [{"label": f"{r['metric_label']} {r['horizon']}", "metric": r["metric"], "low": r["target_low"],
              "high": r["target_high"], "actual": r["actual"], "status": r["status"], "said_in": r["said_in"]}
             for r in rows if r["unit"] == "%" and r["actual"] is not None and r["status"] in ("achieved", "exceeded", "missed")]
    interp = [f"Of {len(graded)} gradeable statements: {met} met, {beaten} beaten, {missed} missed."]
    for rv in revisions:
        interp.append(f"{rv['metric_label']} guidance for {rv['horizon']} was revised {rv['direction']} on the "
                      f"{rv['to_call']} call (from {rv['from']}).")
    if repeated:
        interp.append("Repeated misses on: " + ", ".join(repeated) + ".")
    deterministic = " ".join(interp)
    interpretation, interp_method = deterministic, "deterministic"
    if llm.available() and graded:
        table = "\n".join(f"- {r['said_in']}: {r['metric_label']} {r['horizon']} target {r['target']}, actual "
                          f"{r['actual'] if r['actual'] is not None else 'n/a'}, status {r['status']}" for r in rows)
        out = llm.complete([
            {"role": "system", "content": "You write a neutral 3-4 sentence interpretation of a guidance-versus-actuals "
                                          "table for an investor. Use ONLY the table. Do no arithmetic beyond what is "
                                          "given. Never accuse management of dishonesty."},
            {"role": "user", "content": f"Company {ticker}. Hit rate {hit_rate}%. Revisions: {revisions}.\n{table}"},
        ], tier="strong", max_tokens=260)
        if out:
            interpretation, interp_method = " ".join(out.split()), "llm"
    unc = []
    if counts["pending"]:
        unc.append(f"{counts['pending']} statement(s) refer to periods not yet fully reported.")
    if counts["not_comparable"]:
        unc.append("Capex guidance cannot be checked against reported P&L figures.")
    if counts["long_dated"]:
        unc.append("Medium-term aspirations are listed but not graded.")
    if any(r["method"] == "rules" for r in rows):
        unc.append("Extracted by rules: vague language is never turned into numbers, so softer guidance may be missed.")
    if any(r["citation"]["source"] == "demo" for r in rows):
        unc.append("ILLUSTRATIVE DEMO DATA: transcripts and figures are synthetic.")
    unc.append("Growth is computed on the consolidated basis where available; management may guide on a different basis.")
    return {"ticker": ticker, "status": "ok", "rows": list(reversed(rows)), "summary": summary, "chart": chart,
            "revisions": revisions, "uncertainties": unc, "interpretation": interpretation,
            "interpretation_method": interp_method, "deterministic_interpretation": deterministic}
