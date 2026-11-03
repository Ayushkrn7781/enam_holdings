"""Management promise vs. delivery.

1. Extract guidance statements from the last four earnings-call transcripts
   (cheap LLM over keyword-filtered chunks, with a rules extractor as fallback).
   Every statement must be found verbatim in its source chunk, or it is dropped — no invented quotes.
2. Resolve each statement's horizon (FY27, next quarter, medium term...) to a reporting period.
3. Compute the actual outcome in Python from reported financials and grade it:
   exceeded | achieved | missed | pending | not_comparable.
4. Detect revisions: the same metric+horizon guided differently on later calls.
5. Optionally ask the strong model for a neutral interpretation of the *computed* table only.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Chunk, Document, Guidance
from ..services import llm
from ..services.numbers import growth_pct, margin_pct
from ..services.results import periods
from .periods import fy_end, fy_of_quarter, next_quarter, quarter_end, quarter_label

KEY = re.compile(r"guid|expect|target|aim\b|aspire|outlook|confident|we see|we should|should be|will be in the|range of|band of|trajectory|plan to|planning|capex|invest", re.I)
NUM = re.compile(r"\d+(\.\d+)?\s*(%|percent|per cent|bps|basis points|crore|cr\b)", re.I)

METRIC_RULES = [
    ("ebitda_margin", r"ebitda margin|operating margin|ebit margin|\bmargins?\b"),
    ("capex", r"capex|capital expenditure|invest(ment)? of"),
    ("pat_growth", r"\bpat\b|net profit|profit growth|earnings growth|bottom line"),
    ("revenue_growth", r"revenue|top ?line|sales|growth|grow"),
    ("volume", r"volume|tonnage|units|capacity utili[sz]ation"),
]
METRIC_LABEL = {"revenue_growth": "Revenue growth", "ebitda_margin": "EBITDA margin", "pat_growth": "PAT growth", "capex": "Capex", "volume": "Volume", "qualitative": "Qualitative"}


def _metric(sent: str) -> str:
    for m, pat in METRIC_RULES:
        if re.search(pat, sent, re.I):
            return m
    return "qualitative"


def _targets(sent: str) -> tuple[float | None, float | None, str | None]:
    s = sent.replace("per cent", "%").replace("percent", "%")
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*%", s)
    if m:
        return float(m.group(1)), float(m.group(2)), "%"
    m = re.search(r"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\b)", s, re.I)
    if m and re.search(r"capex|capital expenditure|invest", s, re.I):
        v = float(m.group(1).replace(",", ""))
        return v, v, "INR cr"
    m = re.search(r"(double[- ]digit)", s, re.I)
    if m:
        return 10.0, None, "%"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if m:
        v = float(m.group(1))
        if re.search(r"at least|minimum|upwards of|more than|over|above|exceed", s, re.I):
            return v, None, "%"
        if re.search(r"around|about|approximately|~|close to", s, re.I):
            return v - 0.5, v + 0.5, "%"
        return v, v, "%"
    return None, None, None


def _horizon(sent: str, said_in: str) -> str | None:
    m = re.search(r"Q([1-4])\s?(?:of\s)?FY\s?'?(\d{2,4})", sent, re.I)
    if m:
        return f"Q{m.group(1)} FY{int(m.group(2)) % 100:02d}"
    m = re.search(r"FY\s?'?(\d{2,4})", sent, re.I)
    if m:
        y = int(m.group(1)) % 100
        return f"FY{y:02d}"
    if re.search(r"next quarter|coming quarter|following quarter|q[1-4] onwards", sent, re.I):
        return next_quarter(said_in)
    if re.search(r"this (fiscal|financial year|year)|full[- ]year|for the year|current year|rest of the year", sent, re.I):
        return fy_of_quarter(said_in)
    if re.search(r"next (fiscal|financial year|year)", sent, re.I):
        fy = fy_of_quarter(said_in)
        return f"FY{(int(fy[2:]) + 1) % 100:02d}" if fy else None
    if re.search(r"medium[- ]term|long[- ]term|next (two|three|2|3|few) years|over time", sent, re.I):
        return "medium term"
    return fy_of_quarter(said_in)


def _commitment(sent: str, lo, hi) -> str:
    if lo is None:
        return "qualitative"
    if re.search(r"guid|target|commit", sent, re.I):
        return "range" if hi is not None and hi != lo else "explicit_target"
    return "outlook"


def _rules_extract(chunk: Chunk, said_in: str) -> list[dict]:
    out = []
    from .retrieval import split_sentences

    for sent in split_sentences(chunk.text):
        if len(sent) < 30 or not KEY.search(sent) or not NUM.search(sent):
            continue
        if re.search(r"last year|was|were|grew|delivered|reported|achieved", sent, re.I) and not re.search(r"expect|guid|target|aim|will|should", sent, re.I):
            continue  # backward-looking statement of fact, not guidance
        lo, hi, unit = _targets(sent)
        if lo is None:
            continue
        metric = _metric(sent)
        out.append({"statement": sent.strip(), "metric": metric, "target_low": lo, "target_high": hi, "unit": unit,
                    "horizon": _horizon(sent, said_in), "commitment": _commitment(sent, lo, hi), "method": "rules"})
    return out


def _llm_extract(chunks: list[Chunk], said_in: str) -> list[dict] | None:
    if not llm.available() or not chunks:
        return None
    blob = "\n\n".join(f"[{i}] (p.{c.page}, {c.speaker or 'unknown'}) {c.text}" for i, c in enumerate(chunks))
    out = llm.complete_json(
        [
            {
                "role": "system",
                "content": "You extract forward-looking management guidance from an Indian earnings-call transcript. "
                "Only include statements by company management about FUTURE revenue growth, margins, profit growth, capex, or volumes. "
                "Copy the statement VERBATIM (one or two sentences). Do not turn vague language into numbers: if no number is stated, set targets null and commitment 'qualitative'. "
                'Reply JSON {"items":[{"chunk":int,"statement":str,"metric":"revenue_growth|ebitda_margin|pat_growth|capex|volume|qualitative",'
                '"target_low":number|null,"target_high":number|null,"unit":"%|INR cr|null","horizon":"FYxx|Qn FYxx|next quarter|medium term|null",'
                '"commitment":"explicit_target|range|outlook|qualitative"}]}',
            },
            {"role": "user", "content": f"Call: {said_in}\n\n{blob[:12000]}"},
        ],
        tier="fast",
        max_tokens=1400,
    )
    if not out or "items" not in out:
        return None
    items = []
    for it in out["items"]:
        try:
            c = chunks[int(it["chunk"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        st = (it.get("statement") or "").strip()
        if not _verbatim(st, c.text):
            continue  # citation verification: drop anything not actually in the source
        h = it.get("horizon")
        if h == "next quarter":
            h = next_quarter(said_in)
        items.append({**it, "horizon": h, "method": "llm", "_chunk": c})
    return items


def _verbatim(statement: str, source: str) -> bool:
    if not statement:
        return False
    norm = lambda t: re.sub(r"\W+", " ", t.lower()).strip()  # noqa: E731
    st, src = norm(statement), norm(source)
    if st in src:
        return True
    return SequenceMatcher(None, st, src).find_longest_match(0, len(st), 0, len(src)).size >= 0.85 * len(st)


def extract(s: Session, ticker: str, n_calls: int = 4) -> int:
    docs = s.scalars(
        select(Document).where(Document.ticker == ticker, Document.doc_type == "transcript", Document.status == "indexed")
        .order_by(Document.period_end.desc())
    ).all()[:n_calls]
    s.execute(delete(Guidance).where(Guidance.ticker == ticker))
    n = 0
    for d in docs:
        said_in = d.period_label or (quarter_label(d.period_end) if d.period_end else "unknown")
        cands = [c for c in d.chunks if KEY.search(c.text) and (c.speaker or "").lower() not in ("moderator",)]
        llm_items = _llm_extract(cands, said_in)
        # if the LLM is unavailable, or every item it returned failed verbatim verification, use the rules extractor
        items = llm_items or [dict(it, _chunk=c) for c in cands for it in _rules_extract(c, said_in)]
        seen = set()
        for it in items:
            key = (it["metric"], it.get("horizon"), it.get("target_low"))
            if key in seen:
                continue
            seen.add(key)
            c = it.pop("_chunk")
            s.add(Guidance(ticker=ticker, document_id=d.id, chunk_id=c.id, page=c.page, said_in=said_in, statement=it["statement"],
                           speaker=c.speaker, metric=it.get("metric") or "qualitative", target_low=it.get("target_low"),
                           target_high=it.get("target_high"), unit=it.get("unit"), horizon=it.get("horizon"),
                           commitment=it.get("commitment") or "outlook", method=it["method"]))
            n += 1
    s.commit()
    return n


# ------------------------------------------------------------------ grading

def _actual(s: Session, ticker: str, metric: str, horizon: str | None) -> tuple[float | None, str | None, str]:
    """Return (actual value, period label, how computed)."""
    if not horizon or horizon == "medium term":
        return None, None, "long-dated — not yet assessable"
    qs = periods(s, ticker, "Q")
    ys = periods(s, ticker, "Y")
    fe = fy_end(horizon)
    if fe:  # full fiscal year
        cur = next((y for y in ys if y.period_end == fe), None)
        prev = next((y for y in ys if y.period_end.year == fe.year - 1 and y.period_end.month == 3), None)
        if not cur:  # sum four quarters if the annual row isn't there yet
            fq = [q for q in qs if fe.replace(year=fe.year - 1) < q.period_end <= fe]
            pq = [q for q in qs if fe.replace(year=fe.year - 2) < q.period_end <= fe.replace(year=fe.year - 1)]
            if len(fq) < 4:
                return None, horizon, f"pending — {len(fq)}/4 quarters of {horizon} reported"
            agg = lambda lst, k: sum((q.metrics.get(k) or 0) for q in lst)  # noqa: E731
            cm = {k: agg(fq, k) for k in ("revenue", "ebitda", "pat")}
            pm = {k: agg(pq, k) for k in ("revenue", "ebitda", "pat")} if len(pq) == 4 else None
        else:
            cm, pm = cur.metrics, prev.metrics if prev else None
        if metric == "ebitda_margin":
            return margin_pct(cm.get("ebitda"), cm.get("revenue")), horizon, "full-year EBITDA ÷ revenue"
        key = {"revenue_growth": "revenue", "pat_growth": "pat"}.get(metric)
        if key and pm:
            return growth_pct(cm.get(key), pm.get(key)), horizon, f"full-year {key} YoY"
        return None, horizon, "not comparable from reported financials"
    qe = quarter_end(horizon)
    if qe:
        cur = next((q for q in qs if q.period_end == qe), None)
        if not cur:
            return None, horizon, "pending — quarter not yet reported"
        base = next((q for q in qs if q.period_end.year == qe.year - 1 and q.period_end.month == qe.month), None)
        if metric == "ebitda_margin":
            return margin_pct(cur.metrics.get("ebitda"), cur.metrics.get("revenue")), horizon, "quarter EBITDA ÷ revenue"
        key = {"revenue_growth": "revenue", "pat_growth": "pat"}.get(metric)
        if key and base:
            return growth_pct(cur.metrics.get(key), base.metrics.get(key)), horizon, f"quarter {key} YoY"
    return None, horizon, "not comparable from reported financials"


def _grade(lo, hi, actual, unit) -> tuple[str, float | None]:
    if actual is None or lo is None:
        return "not_comparable", None
    tol = 0.05 if unit == "%" else 0  # rounding tolerance only; "around X%" already carries its own band
    if hi is None:  # "at least X"
        return ("achieved" if actual >= lo - tol else "missed"), round(actual - lo, 1)
    if actual > hi + tol:
        return "exceeded", round(actual - hi, 1)
    if actual < lo - tol:
        return "missed", round(actual - lo, 1)
    return "achieved", 0.0


def scorecard(s: Session, ticker: str, interpret: bool = True) -> dict:
    gs = s.scalars(select(Guidance).where(Guidance.ticker == ticker).order_by(Guidance.id)).all()
    docs = {d.id: d for d in s.scalars(select(Document).where(Document.ticker == ticker)).all()}
    if not gs:
        n_tx = sum(1 for d in docs.values() if d.doc_type == "transcript")
        return {"ticker": ticker, "rows": [], "summary": None,
                "status": "no_transcripts" if not n_tx else "no_guidance",
                "message": "No earnings-call transcripts indexed for this company." if not n_tx
                else "Transcripts are indexed, but no quantified forward guidance could be established from them."}
    rows = []
    for g in gs:
        actual, period, how = _actual(s, ticker, g.metric, g.horizon)
        status, variance = _grade(g.target_low, g.target_high, actual, g.unit)
        if status == "not_comparable" and how.startswith("pending"):
            status = "pending"
        if g.commitment == "qualitative":
            status = "qualitative"
        if g.horizon == "medium term":
            status = "long_dated"
        d = docs.get(g.document_id)
        rows.append({
            "id": g.id, "said_in": g.said_in, "speaker": g.speaker, "statement": g.statement, "metric": g.metric,
            "metric_label": METRIC_LABEL.get(g.metric, g.metric), "target_low": g.target_low, "target_high": g.target_high,
            "unit": g.unit, "horizon": g.horizon, "commitment": g.commitment, "actual": actual, "actual_period": period,
            "actual_method": how, "variance": variance, "status": status, "method": g.method,
            "citation": {"document": d.title if d else None, "page": g.page, "url": d.url if d else None, "period": g.said_in, "source": d.source if d else None},
        })
    # revisions: same metric+horizon guided again later with a different target
    by_key: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["target_low"] is not None and r["horizon"]:
            by_key.setdefault((r["metric"], r["horizon"]), []).append(r)
    revisions = []
    for (metric, hz), lst in by_key.items():
        lst.sort(key=lambda r: quarter_end(r["said_in"]) or fy_end(r["said_in"]) or quarter_end("Q1 FY00"))
        for a, b in zip(lst, lst[1:]):
            if (a["target_low"], a["target_high"]) != (b["target_low"], b["target_high"]):
                direction = "up" if (b["target_low"] or 0) > (a["target_low"] or 0) else "down"
                b["revision"] = {"direction": direction, "from": [a["target_low"], a["target_high"]], "said_in": a["said_in"]}
                revisions.append({"metric": METRIC_LABEL.get(metric, metric), "horizon": hz, "direction": direction,
                                  "from": [a["target_low"], a["target_high"]], "to": [b["target_low"], b["target_high"]],
                                  "from_call": a["said_in"], "to_call": b["said_in"]})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    graded = [r for r in rows if r["status"] in ("achieved", "exceeded", "missed")]
    hit_rate = round(sum(r["status"] != "missed" for r in graded) / len(graded) * 100) if graded else None
    repeated_misses = sorted({r["metric_label"] for r in graded if r["status"] == "missed" and sum(1 for x in graded if x["metric"] == r["metric"] and x["status"] == "missed") >= 2})

    # chart: per metric, target band vs actual by horizon
    chart = []
    for r in rows:
        if r["unit"] == "%" and r["target_low"] is not None and r["horizon"] and r["status"] not in ("long_dated", "qualitative"):
            chart.append({"label": f"{r['metric_label']} · {r['horizon']}", "said_in": r["said_in"], "metric": r["metric"],
                          "low": r["target_low"], "high": r["target_high"] if r["target_high"] is not None else r["target_low"],
                          "actual": r["actual"], "status": r["status"]})

    summary = {"counts": counts, "hit_rate_pct": hit_rate, "graded": len(graded), "revisions": revisions, "repeated_misses": repeated_misses,
               "calls_covered": sorted({r["said_in"] for r in rows})}
    out = {"ticker": ticker, "status": "ok", "rows": rows, "summary": summary, "chart": chart,
           "uncertainties": _uncertainties(rows), "interpretation": _deterministic_take(summary, rows)}
    if interpret and llm.available() and graded:
        out["interpretation"] = _llm_take(ticker, rows, summary) or out["interpretation"]
    return out


def _uncertainties(rows):
    u = ["Actuals are compared on the company's reported basis (consolidated where available); segment-level guidance is graded only where segment data exists."]
    if any(r["method"] == "rules" for r in rows):
        u.append("Some statements were extracted by keyword rules (LLM not configured) — review the verbatim quote before relying on the grade.")
    if any(r["status"] == "pending" for r in rows):
        u.append("Pending items refer to periods not yet reported.")
    if any(r["commitment"] == "outlook" for r in rows):
        u.append("'Outlook' statements are softer than explicit guidance; a miss against an outlook is weaker evidence than a miss against a stated target.")
    return u


def _deterministic_take(summary, rows) -> dict:
    parts = []
    if summary["graded"]:
        c = summary["counts"]
        parts.append(f"Of {summary['graded']} gradeable statement{'s' if summary['graded'] != 1 else ''}: {c.get('achieved', 0)} met, {c.get('exceeded', 0)} beaten, {c.get('missed', 0)} missed.")
    for rv in summary["revisions"]:
        parts.append(f"{rv['metric']} guidance for {rv['horizon']} was revised {rv['direction']} on the {rv['to_call']} call (from {rv['from'][0]:g}{'–' + format(rv['from'][1], 'g') if rv['from'][1] not in (None, rv['from'][0]) else ''}%).")
    if summary["repeated_misses"]:
        parts.append(f"Repeated misses on: {', '.join(summary['repeated_misses'])}.")
    if not parts:
        parts.append("Not enough reported periods yet to grade management's guidance.")
    return {"text": " ".join(parts), "method": "deterministic"}


def _llm_take(ticker, rows, summary) -> dict | None:
    table = "\n".join(
        f"- [{r['said_in']}] {r['metric_label']} target {r['target_low']}–{r['target_high']}{r['unit'] or ''} for {r['horizon']} → actual {r['actual']} ({r['status']}). Quote: \"{r['statement'][:220]}\""
        for r in rows if r["status"] not in ("qualitative",)
    )
    text = llm.complete(
        [
            {"role": "system", "content": "You are a neutral equity analyst. Using ONLY the computed table below, write 3-4 sentences on how management's guidance compared with delivery: "
             "credibility pattern, revisions, and what to watch next. Do not restate every row. Do not use outside knowledge. Do not accuse management of dishonesty. "
             "Do not compute new numbers; you may reference numbers in the table."},
            {"role": "user", "content": f"{ticker}\n{table}\n\nSummary: {summary}"},
        ],
        tier="strong",
        max_tokens=260,
    )
    return {"text": text.strip(), "method": "llm (strong tier, grounded in computed table)"} if text else None
