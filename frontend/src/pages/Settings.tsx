import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { COMPONENT_COLOR } from "../lib/format";
import { Button, ErrorBox, LoadingRows, Section, useAsync } from "../components/ui";

const ORDER = ["category", "financial", "deviation", "relevance", "novelty"];
const HELP: Record<string, string> = {
  category: "How much the type of filing matters (results, M&A, CEO change…)",
  financial: "Size against revenue, or the size of the results move",
  deviation: "Results surprise, price and volume reaction",
  relevance: "A holding you alert on, a holding, or neither",
  novelty: "How different it is from this company's recent filings",
};

function Weights() {
  const { data, error, loading, reload } = useAsync<any>(() => api.weights(), []);
  const [w, setW] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (data) setW(data.weights); }, [data]);
  if (loading && !data) return <LoadingRows n={2} />;
  if (error) return <ErrorBox what="weights" error={error} retry={reload} />;
  if (!w) return null;
  const total = Object.values(w).reduce((a, b) => a + b, 0) || 1;
  const save = async (weights: Record<string, number>) => {
    setBusy(true); setMsg(null);
    try { const r = await api.putWeights(weights); setW(r.weights); setMsg(`Saved. Re-scored ${r.rescored} filings.`); }
    catch (e: any) { setMsg(`Could not save: ${e.message}`); }
    setBusy(false);
  };
  return (
    <div>
      <div className="space-y-3">
        {ORDER.map((k) => (
          <div key={k}>
            <div className="flex items-baseline justify-between text-[14px]">
              <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: COMPONENT_COLOR[k] }} />{data.labels[k]}</span>
              <span className="w-cond font-semibold">{Math.round((w[k] / total) * 100)}%</span>
            </div>
            <input type="range" min={0} max={0.6} step={0.01} value={w[k]} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })}
              className="mt-1 w-full" aria-label={`${data.labels[k]} weight`} />
            <div className="text-[12px] text-faint">{HELP[k]}</div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-2">
        <Button primary disabled={busy} onClick={() => save(w)}>{busy ? "Re-scoring…" : "Save and re-score"}</Button>
        <Button disabled={busy} onClick={() => save(data.defaults)}>Restore defaults</Button>
      </div>
      {msg && <p className="mt-2 text-[13px] text-dim" role="status">{msg}</p>}
    </div>
  );
}

export default function Settings({ onReset }: { onReset: () => void }) {
  const st = useAsync<any>(() => api.status(), []);
  const ev = useAsync<any>(() => api.evalResults(), []);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const reset = async () => {
    if (!window.confirm("Reset the demo dataset? Pins, alert changes and weights are cleared.")) return;
    setBusy(true);
    try { const r = await api.demoReset(); setMsg(`Demo dataset restored (${r.method}).`); st.reload(); onReset(); }
    catch (e: any) { setMsg(`Reset failed: ${e.message}`); }
    setBusy(false);
  };
  const s = st.data;
  return (
    <div>
      <h1 className="w-semi text-[24px] font-bold">Settings</h1>
      {st.error && <div className="mt-4"><ErrorBox what="data status" error={st.error} retry={st.reload} /></div>}
      {st.loading && !s && <div className="mt-4"><LoadingRows n={3} /></div>}
      {s && (
        <>
          <Section title="Data">
            <div className={`rounded border p-3.5 text-[14px] ${s.mode === "demo" ? "border-warn/40 bg-warn/5" : "border-line"}`}>
              <div className={`font-semibold ${s.mode === "demo" ? "text-warn" : ""}`}>{s.mode === "demo" ? "Illustrative demo data" : "Live data"}</div>
              <p className="mt-1 text-dim">{s.demo_note || s.monitoring_note}</p>
              <p className="mt-2 text-dim">
                <span className="w-cond text-fg">{s.counts.holdings}</span> holdings, <span className="w-cond text-fg">{s.counts.announcements}</span> filings,{" "}
                <span className="w-cond text-fg">{s.counts.prices.toLocaleString("en-IN")}</span> price rows, <span className="w-cond text-fg">{s.counts.documents}</span> documents
                (<span className="w-cond text-fg">{s.counts.chunks}</span> passages), last session {s.last_eod_session}.
              </p>
              <p className="mt-2 text-[13px] text-dim">To pull live NSE filings, screener.in fundamentals and Yahoo prices, run <code className="rounded bg-raised px-1 py-0.5 text-fg">{s.refresh_command}</code></p>
            </div>
            <ul className="hairline mt-2 text-[13px]">
              {Object.entries(s.sources || {}).map(([k, v]: any) => (
                <li key={k} className="flex items-baseline gap-2 py-1.5">
                  <span className={`h-2 w-2 rounded-full ${v.ok ? "bg-up" : "bg-down"}`} />
                  <span className="w-20 font-medium">{k}</span><span className="min-w-0 flex-1 truncate text-dim">{v.detail}</span>
                </li>
              ))}
            </ul>
            <Button className="mt-3" disabled={busy} onClick={reset}>{busy ? "Resetting…" : "Reset demo dataset"}</Button>
            {msg && <p className="mt-2 text-[13px] text-dim" role="status">{msg}</p>}
          </Section>

          <Section title="Language model">
            {s.llm.configured ? (
              <div className="text-[14px]">
                <p>{s.llm.provider}. Rules run first; the model only fills gaps.</p>
                <ul className="mt-2 space-y-1 text-dim">
                  <li><span className="w-cond text-fg">{s.llm.models.fast}</span>, fast tier: {s.llm.routing.fast}</li>
                  <li><span className="w-cond text-fg">{s.llm.models.strong}</span>, strong tier: {s.llm.routing.strong}</li>
                </ul>
              </div>
            ) : (
              <p className="text-[14px] text-dim">No model key is set, so FINN runs fully deterministic: rules classify filings, guidance is extracted by rules, and research answers are extractive quotes from the documents. Set <code className="rounded bg-raised px-1 py-0.5 text-fg">GEMINI_API_KEY</code> (free tier) to enable summaries and synthesis.</p>
            )}
            <p className="mt-2 text-[13px] text-dim">
              <span className="w-cond text-fg">{s.llm.calls}</span> calls, <span className="w-cond text-fg">{s.llm.cache_hits}</span> cache hits, <span className="w-cond text-fg">{s.llm.tokens.toLocaleString("en-IN")}</span> tokens this process. Retrieval: {s.retrieval}.
            </p>
          </Section>
        </>
      )}

      <Section title="Materiality weights"><Weights /></Section>

      <Section title="Evaluation">
        {ev.data?.available ? (
          <div>
            <div className="grid grid-cols-2 border-y border-line sm:grid-cols-4">
              {Object.entries(ev.data.metrics).filter(([k]) => k !== "latency_ms").map(([k, v]: any) => (
                <div key={k} className="py-2.5">
                  <div className="text-[12px] capitalize text-dim">{k.replace(/_/g, " ")}</div>
                  <div className="w-cond text-[20px] font-semibold">{v.value === null ? "N/A" : `${Math.round(v.value * 100)}%`}</div>
                  <div className="text-[11px] text-faint">n = {v.n}</div>
                </div>
              ))}
              <div className="py-2.5"><div className="text-[12px] text-dim">Latency p50 / p95</div><div className="w-cond text-[20px] font-semibold">{ev.data.metrics.latency_ms.p50} / {ev.data.metrics.latency_ms.p95} ms</div></div>
            </div>
            <p className="mt-2 text-[12px] text-faint">{ev.data.questions} questions. {ev.data.caveat}</p>
          </div>
        ) : <p className="text-[14px] text-dim">No evaluation results yet. Run <code className="rounded bg-raised px-1 py-0.5 text-fg">./run.sh test</code>.</p>}
      </Section>

      <Section title="About">
        <p className="text-[14px] leading-relaxed text-dim">
          FINN filters an investor's day: the brief ranks every exchange filing across your portfolio with an explainable materiality
          score, and research grades what management promised against what they reported, using only primary documents. Numbers
          are always computed in code, never by the model.
        </p>
      </Section>
    </div>
  );
}
