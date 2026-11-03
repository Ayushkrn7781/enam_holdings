"""Evaluation harness: route accuracy, Recall@5, citation validity, numeric accuracy, guidance grading,
insufficient-evidence handling, unverified-sentence rate and latency. Writes eval/results.json.

Run from backend/: python -m eval.run_eval
"""
from __future__ import annotations

import json
import re
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from finn.db import get_meta, init_db, session_scope
from finn.models import Chunk, Company
from finn.research import answer as A, guidance, retrieval
from finn.services import llm, numbers as N
from finn.services.results import periods

HERE = Path(__file__).resolve().parent


def _independent(s, ticker: str, metric: str, basis: str):
    """Recompute from raw rows, without going through results_card."""
    qs = periods(s, ticker, "Q")
    cur = qs[-1]
    target = cur.period_end - timedelta(days=91 if basis == "qoq" else 365)
    base = min(qs[:-1], key=lambda q: abs((q.period_end - target).days))
    return N.growth_pct(cur.metrics.get(metric), base.metrics.get(metric))


def main() -> None:
    init_db()
    qs = json.loads((HERE / "questions.json").read_text())
    rows, lat = [], []
    with session_scope() as s:
        all_chunks = {c.text for c in s.scalars(select(Chunk)).all()}
        mode = get_meta(s, "data_mode", "demo")
        for q in qs:
            t0 = time.perf_counter()
            res = A.answer(s, q["ticker"], q["question"])
            lat.append((time.perf_counter() - t0) * 1000)
            r = {"id": q["id"], "type": q["type"], "ticker": q["ticker"], "question": q["question"],
                 "route": res["route"], "route_ok": res["route"] == q["route"], "engine": res["engine"]}
            cites = [c for c in res["citations"] if c.get("doc_type") not in ("financials",)]
            r["citations_valid"] = all(any(c["text"] in ch for ch in all_chunks) for c in cites) if cites else None
            if "gold" in q:
                top = retrieval.search(s, q["ticker"], q["question"], k=5)
                r["recall_at_5"] = any(q["gold"].lower() in h["text"].lower() for h in top)
            if q["type"] == "numeric":
                want = _independent(s, q["ticker"], q["metric"], q["basis"])
                label = {"revenue": "Revenue", "ebitda": "EBITDA", "pbt": "PBT", "pat": "PAT"}[q["metric"]]
                m = re.search(rf"\*\*{label}\*\*.*?{'QoQ' if q['basis'] == 'qoq' else 'YoY'} ([+-]\d+\.\d)%",
                              res["answer"])
                got = float(m.group(1)) if m else None
                r.update(expected=want, got=got, numeric_ok=got is not None and want is not None and abs(got - want) < 0.05)
            if q["type"] in ("guidance", "contradiction"):
                summ = guidance.scorecard(s, q["ticker"])["summary"]
                counts = {"missed": summ["missed"], "achieved": summ["met"], "exceeded": summ["beaten"]}
                r["guidance_ok"] = all(counts[k] == v for k, v in q["expected"].items())
                r["guidance_counts"] = counts
            if q["type"] == "insufficient":
                r["insufficient_ok"] = A.NOT_VERIFIED in res["answer"] and not res["citations"]
            v = res.get("verification")
            r["sentences"] = v["sentences"] if v else 0
            r["unverified"] = v["unverified"] if v else 0
            rows.append(r)

    def rate(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return {"value": round(sum(bool(v) for v in vals) / len(vals), 3) if vals else None, "n": len(vals)}

    sent = sum(r["sentences"] for r in rows)
    metrics = {
        "route_accuracy": rate("route_ok"), "recall_at_5": rate("recall_at_5"),
        "citation_validity": rate("citations_valid"), "numeric_accuracy": rate("numeric_ok"),
        "guidance_grading": rate("guidance_ok"), "insufficient_evidence_handling": rate("insufficient_ok"),
        "unverified_sentence_rate": {"value": round(sum(r["unverified"] for r in rows) / sent, 3) if sent else 0.0,
                                     "n": sent},
        "latency_ms": {"p50": round(statistics.median(lat), 1),
                       "p95": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 1)},
    }
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "questions": len(rows),
           "corpus_mode": mode, "llm": llm.available(), "metrics": metrics, "rows": rows,
           "caveat": ("Run on the illustrative demo corpus: this validates the pipeline (routing, retrieval, citation, "
                      "maths and grading) end to end, not real-world accuracy on live filings."
                      + ("" if llm.available() else " LLM not configured: narrative answers are extractive."))}
    (HERE / "results.json").write_text(json.dumps(out, indent=2, default=str))
    for k, v in metrics.items():
        print(f"{k:32} {v}")
    fails = [r["id"] for r in rows if any(r.get(k) is False for k in
                                          ("route_ok", "recall_at_5", "citations_valid", "numeric_ok", "guidance_ok",
                                           "insufficient_ok"))]
    print("failures:", fails or "none")


if __name__ == "__main__":
    main()
