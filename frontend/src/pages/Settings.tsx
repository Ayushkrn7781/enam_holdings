import { CheckCircle2, CircleAlert, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorState, H2, ListSkeleton } from "../components/ui";
import { api, post, useApi } from "../lib/api";
import { COMPONENTS } from "../lib/format";
import { go } from "../lib/router";

export default function Settings() {
  const st = useApi("/api/system/data-status");
  const ev = useApi("/api/system/eval");
  const [msg, setMsg] = useState<string | null>(null);
  if (st.error) return <ErrorState message={st.error} onRetry={st.reload} />;
  if (!st.data) return <ListSkeleton rows={6} />;
  const s = st.data;
  const demo = s.mode?.mode === "demo";
  return (
    <div>
      <h1 className="w-semi text-[24px] font-semibold">Settings</h1>

      <H2>Data</H2>
      <div className={`rounded border p-3 text-[13.5px] ${demo ? "border-warn/40 bg-warn/5" : "border-line"}`}>
        <div className="font-semibold">{demo ? "Illustrative demo dataset" : "Live end-of-day data"}, as of {s.mode?.as_of}</div>
        <div className="mt-1 text-dim">{s.mode?.note}</div>
        <div className="mt-1 text-dim">{s.monitoring}</div>
        <div className="num mt-2 flex flex-wrap gap-x-4 text-[12.5px] text-dim">{Object.entries(s.counts).map(([k, v]) => <span key={k}>{k.replace("_", " ")} {String(v)}</span>)}</div>
        {demo && <div className="mt-2 text-[12.5px] text-dim">To load real data, run <code className="rounded bg-ink px-1">python -m finn.refresh --research TRENT HAL</code> on a machine with normal internet access.</div>}
      </div>
      {Object.keys(s.sources).length > 0 && (
        <ul className="mt-2 divide-y divide-line border-y border-line text-[13px]">
          {Object.entries(s.sources).map(([k, v]: any) => (
            <li key={k} className="flex items-start gap-2 py-2">
              {v.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-up" /> : <CircleAlert className="mt-0.5 h-4 w-4 text-down" />}
              <div><span className="font-semibold capitalize">{k}</span> <span className="text-dim">{v.detail}</span><div className="text-[11.5px] text-faint">{v.at}</div></div>
            </li>
          ))}
        </ul>
      )}
      <button onClick={() => { setMsg("Rebuilding…"); post("/api/system/demo-reset").then(() => { setMsg("Demo dataset rebuilt."); st.reload(); }).catch((e) => setMsg(e.message)); }}
        className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-info hover:underline"><RotateCcw className="h-3.5 w-3.5" />Reset demo dataset</button>
      {msg && <span className="ml-3 text-[12.5px] text-dim">{msg}</span>}

      <H2>Language model</H2>
      <div className="text-[13.5px]">
        {s.llm.configured ? (
          <div>Connected to <span className="font-semibold">{s.llm.provider}</span>. Fast tier <code>{s.llm.fast_model}</code> handles classification fallbacks, summaries and extraction; strong tier <code>{s.llm.strong_model}</code> is used only for research synthesis and interpretation.</div>
        ) : (
          <div className="text-dim">No API key set, so FINN runs fully deterministic: rule-based classification, extractive answers with citations, and rule-based guidance extraction. Set <code className="rounded bg-ink px-1">GROQ_API_KEY</code> (free tier) on the backend to enable summaries and synthesis.</div>
        )}
        <div className="num mt-1 text-[12.5px] text-faint">This process: {s.llm.calls} calls, {s.llm.cache_hits} cache hits, {s.llm.prompt_tokens + s.llm.completion_tokens} tokens. Retrieval: {s.retrieval}.</div>
      </div>

      <Weights />

      <H2>Evaluation</H2>
      {ev.data?.available ? (
        <div className="text-[13.5px]">
          <div className="text-dim">{ev.data.n_questions} curated questions, run {ev.data.generated_at} on the {ev.data.corpus} corpus, LLM {ev.data.llm ? "on" : "off"}.</div>
          <dl className="num mt-2 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            {Object.entries(ev.data.metrics).map(([k, v]: any) => (
              <div key={k}><dt className="text-[11.5px] text-dim">{k.replace(/_/g, " ")}</dt><dd className="w-cond text-[18px] font-semibold">{"value" in v ? (v.value == null ? "N/A" : k.includes("rate") ? `${(v.value * 100).toFixed(1)}%` : `${Math.round(v.value * 100)}%`) : `${v.p50} / ${v.p95} ms`}</dd>{"n" in v && <dd className="text-[11px] text-faint">n={v.n}</dd>}</div>
            ))}
          </dl>
          <p className="mt-2 text-[12px] text-faint">{ev.data.caveat}</p>
        </div>
      ) : <div className="text-[13px] text-dim">No evaluation run yet. Run <code>python -m eval.run_eval</code> in the backend.</div>}

      <H2>About</H2>
      <p className="max-w-prose text-[13px] text-dim">FINN ranks filings by an explainable materiality score, computes every number in code, and answers research questions only from a company's own annual reports, concall transcripts and reported financials. It is a research aid, not investment advice. <button onClick={() => go("brief")} className="text-info hover:underline">Back to the brief</button></p>
    </div>
  );
}

function Weights() {
  const { data, reload } = useApi("/api/settings/materiality");
  const [w, setW] = useState<Record<string, number> | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (data) setW(data.weights); }, [data]);
  if (!w) return null;
  const total = Object.values(w).reduce((a, b) => a + b, 0) || 1;
  return (
    <>
      <H2>How signals are ranked</H2>
      <p className="mb-2 text-[13px] text-dim">Materiality is a weighted sum of five rule-based scores. Change the weights to change what rises to the top; every signal is re-scored.</p>
      <div className="space-y-2">
        {COMPONENTS.map((c) => (
          <label key={c.key} className="grid grid-cols-[130px_1fr_44px] items-center gap-3 text-[13px]">
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: c.color }} />{c.label}</span>
            <input type="range" min={0} max={0.6} step={0.05} value={w[c.key]} onChange={(e) => setW({ ...w, [c.key]: +e.target.value })} className="accent-[#3FB98A]" />
            <span className="num text-right text-dim">{Math.round((w[c.key] / total) * 100)}%</span>
          </label>
        ))}
      </div>
      <div className="mt-2 flex gap-3 text-[13px]">
        <button disabled={saving} onClick={() => { setSaving(true); api("/api/settings/materiality", { method: "PUT", body: JSON.stringify(w) }).then(reload).finally(() => setSaving(false)); }} className="rounded bg-fg px-3 py-1 font-semibold text-ink">{saving ? "Re-scoring…" : "Save and re-score"}</button>
        <button onClick={() => setW({ category: 0.25, financial: 0.25, deviation: 0.2, relevance: 0.15, novelty: 0.15 })} className="text-dim hover:text-fg">Restore defaults</button>
      </div>
    </>
  );
}
