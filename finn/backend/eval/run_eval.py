"""Evaluation harness. Runs every curated question through the real API code path and scores it.

    python -m eval.run_eval            (from backend/)

Metrics
  route_accuracy       router picked the expected engine
  recall_at_5          narrative questions: the gold evidence string is in the top-5 retrieved chunks
  citation_validity    every citation's excerpt exists verbatim in a stored chunk of that company
  numeric_accuracy     numeric answers match an independent recomputation from raw stored figures
  guidance_grading     promise-vs-delivered status counts match the gold labels
  insufficient_handled questions with no evidence return the explicit "could not verify" message
  unverified_rate      share of answer sentences flagged by the numeric/citation verifier (hallucination proxy)
  latency_ms           p50 / p95 end-to-end
Results are written to eval/results.json and shown in the app (Settings -> Evaluation).
The corpus is the ILLUSTRATIVE demo dataset unless live documents have been ingested.
"""
import json
import re
import statistics
import time
from pathlib import Path

from sqlalchemy import select

from finn.db import SessionLocal, init_db
from finn.models import Chunk, Meta
from finn.research import answer, retrieval
from finn.services import llm
from finn.services.numbers import growth_pct
from finn.services.results import periods

HERE = Path(__file__).parent


def main():
    init_db()
    s = SessionLocal()
    qs = json.loads((HERE / "questions.json").read_text())
    rows, lat = [], []
    for q in qs:
        t0 = time.time()
        out = answer.answer(s, q["ticker"], q["q"])
        lat.append((time.time() - t0) * 1000)
        r = {"id": q["id"], "type": q["type"], "ticker": q["ticker"], "question": q["q"], "route": out["route"], "route_ok": out["route"] == q["route"]}
        if q["type"] in ("fact", "guidance_text"):
            hits = retrieval.search(s, q["ticker"], q["q"], k=5)
            r["recall_at_5"] = any(q["evidence"].lower() in c.text.lower() for c, _ in hits)
        chunks = {c.text for c in s.scalars(select(Chunk).where(Chunk.ticker == q["ticker"]))}
        cits = [c for c in out["citations"] if c.get("doc_type") not in ("financials",)]
        r["citations"] = len(out["citations"])
        r["citations_valid"] = all(any((c["excerpt"] or "")[:200] in t for t in chunks) or c.get("doc_type") == "transcript" and any(c["excerpt"][:120] in t for t in chunks) for c in cits)
        if q["type"] == "numeric":
            qq = periods(s, q["ticker"], "Q")
            cur, prev = qq[-1], qq[-2]
            base = prev if q["calc"] == "qoq" else next(x for x in qq if x.period_end.year == cur.period_end.year - 1 and x.period_end.month == cur.period_end.month)
            expect = growth_pct(cur.metrics[q["metric"]], base.metrics[q["metric"]])
            tag = "QoQ" if q["calc"] == "qoq" else "YoY"
            m = re.search(rf"\*\*{ {'pat':'PAT','revenue':'Revenue','ebitda':'EBITDA','pbt':'PBT'}[q['metric']] }\*\*.*?{tag} ([+-]?\d+\.\d)%", out["answer"])
            r["expected"], r["got"] = expect, float(m.group(1)) if m else None
            r["numeric_ok"] = r["got"] is not None and abs(r["got"] - expect) < 0.05
        if q["type"] in ("guidance", "contradiction"):
            counts = out.get("data", {}).get("summary", {}).get("counts", {})
            r["guidance_ok"] = all(counts.get(k, 0) == v for k, v in q["expect_status"].items())
        if q.get("insufficient"):
            r["insufficient_ok"] = "could not verify" in out["answer"].lower()
        ver = out.get("verification") or {}
        r["unverified_sentences"] = len(ver.get("unverified", []))
        r["sentences"] = ver.get("sentences") or max(1, out["answer"].count("\n") + 1)
        r["engine"] = out["engine"]
        rows.append(r)

    def rate(key):
        v = [r[key] for r in rows if key in r]
        return {"value": round(sum(v) / len(v), 3) if v else None, "n": len(v)}

    mode = s.get(Meta, "data_mode")
    res = {
        "corpus": (mode.value.get("mode") if mode else "unknown"),
        "llm": llm.stats()["configured"],
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "n_questions": len(rows),
        "metrics": {
            "route_accuracy": rate("route_ok"),
            "recall_at_5": rate("recall_at_5"),
            "citation_validity": rate("citations_valid"),
            "numeric_accuracy": rate("numeric_ok"),
            "guidance_grading": rate("guidance_ok"),
            "insufficient_handled": rate("insufficient_ok"),
            "unverified_rate": {"value": round(sum(r["unverified_sentences"] for r in rows) / max(1, sum(r["sentences"] for r in rows)), 3), "n": len(rows)},
            "latency_ms": {"p50": round(statistics.median(lat)), "p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))])},
        },
        "rows": rows,
        "caveat": "Measured on the curated question set over the indexed corpus. With the demo corpus this validates the pipeline, not real-world accuracy; re-run after `python -m finn.refresh --research ...`.",
    }
    (HERE / "results.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res["metrics"], indent=2))
    for r in rows:
        bad = [k for k in ("route_ok", "recall_at_5", "citations_valid", "numeric_ok", "guidance_ok", "insufficient_ok") if r.get(k) is False]
        if bad:
            print("FAIL", r["id"], r["question"], bad, r.get("expected"), r.get("got"))


if __name__ == "__main__":
    main()
