import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorState, H2, ListSkeleton, PriorityTag } from "../components/ui";
import { del, patch, post, useApi } from "../lib/api";
import { when } from "../lib/format";
import { go } from "../lib/router";

export default function Alerts() {
  const { data, error, loading, reload } = useApi("/api/alerts?limit=80");
  const cats = useApi("/api/meta/categories");
  useEffect(() => { if (data?.unseen) post("/api/alerts/seen").catch(() => {}); }, [data?.unseen]);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading && !data) return <ListSkeleton rows={6} />;
  const kindLabel: Record<string, string> = { volume: "Volume spike", price_up: "Price up", price_down: "Price down", category: "Filing" };

  return (
    <div>
      <h1 className="w-semi text-[24px] font-semibold">Alerts</h1>
      <p className="mt-1 text-[13px] text-dim">You decide what counts as unusual. {data?.monitoring}</p>

      <H2>Watching for</H2>
      <ul className="divide-y divide-line border-y border-line">
        {data?.rules.map((r: any) => <RuleRow key={r.id} r={r} onChange={reload} />)}
      </ul>
      <NewRule cats={cats.data ?? []} onCreated={reload} />

      <H2 right={<span className="text-[12px] text-dim">{data?.events.length} recent</span>}>History</H2>
      <ul className="divide-y divide-line border-y border-line">
        {data?.events.map((e: any) => (
          <li key={e.id}>
            <button onClick={() => (e.announcement_id ? go("signal", e.announcement_id) : go("research", e.ticker))} className="flex w-full items-start gap-3 py-2.5 text-left">
              <div className="w-[76px] shrink-0 pt-0.5"><PriorityTag p={e.priority} /></div>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px]">{e.message}</div>
                <div className="text-[11.5px] text-faint">{kindLabel[e.kind]}, {when(e.at)}</div>
              </div>
              {!e.seen && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-info" aria-label="new" />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RuleRow({ r, onChange }: { r: any; onChange: () => void }) {
  const [th, setTh] = useState<string>(r.threshold ?? "");
  const save = (body: any) => patch(`/api/alerts/${r.id}`, body).then(onChange);
  return (
    <li className={`flex items-center gap-3 py-2.5 ${r.enabled ? "" : "opacity-50"}`}>
      <label className="relative inline-flex shrink-0 cursor-pointer items-center" aria-label={r.enabled ? "Disable alert" : "Enable alert"}>
        <input type="checkbox" checked={r.enabled} onChange={(e) => save({ enabled: e.target.checked })} className="peer sr-only" />
        <span className="h-5 w-9 rounded-full bg-line transition-colors peer-checked:bg-up" />
        <span className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-fg transition-transform peer-checked:translate-x-4" />
      </label>
      <div className="min-w-0 flex-1 text-[13.5px]">{r.description}<div><PriorityTag p={r.priority} /></div></div>
      {r.kind !== "category" && (
        <input value={th} onChange={(e) => setTh(e.target.value)} onBlur={() => th && +th !== r.threshold && save({ threshold: +th })} inputMode="decimal" aria-label="Threshold"
          className="num w-16 rounded border border-line bg-ink px-2 py-1 text-right text-[13px] focus:border-info focus:outline-none" />
      )}
      <button onClick={() => del(`/api/alerts/${r.id}`).then(onChange)} aria-label="Delete alert" className="rounded p-1.5 text-faint hover:text-down"><Trash2 className="h-4 w-4" /></button>
    </li>
  );
}

function NewRule({ cats, onCreated }: { cats: any[]; onCreated: () => void }) {
  const [kind, setKind] = useState("volume");
  const [threshold, setThreshold] = useState("2");
  const [category, setCategory] = useState("results");
  const [ticker, setTicker] = useState("");
  const [priority, setPriority] = useState("high");
  const [err, setErr] = useState<string | null>(null);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    post("/api/alerts", { kind, threshold: kind === "category" ? null : +threshold, category: kind === "category" ? category : null, ticker: ticker.trim() || null, priority })
      .then(onCreated).catch((x) => setErr(x.message));
  };
  const field = "rounded border border-line bg-ink px-2 py-1.5 text-[13px] text-fg";
  return (
    <form onSubmit={submit} className="mt-3 grid grid-cols-2 gap-2 rounded border border-line bg-surface p-3 text-[12.5px] text-dim sm:grid-cols-5">
      <label className="flex flex-col gap-1">When<select value={kind} onChange={(e) => setKind(e.target.value)} className={field}>
        <option value="volume">Volume ≥ × average</option><option value="price_up">Price up ≥ %</option><option value="price_down">Price down ≥ %</option><option value="category">A filing of type</option></select></label>
      {kind === "category" ? (
        <label className="flex flex-col gap-1">Type<select value={category} onChange={(e) => setCategory(e.target.value)} className={field}>{cats.filter((c) => c.key !== "unclassified").map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select></label>
      ) : (
        <label className="flex flex-col gap-1">Threshold<input value={threshold} onChange={(e) => setThreshold(e.target.value)} inputMode="decimal" className={`num ${field}`} /></label>
      )}
      <label className="flex flex-col gap-1">Company<input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="Any holding" className={field} /></label>
      <label className="flex flex-col gap-1">Priority<select value={priority} onChange={(e) => setPriority(e.target.value)} className={field}><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
      <button className="col-span-2 self-end rounded bg-fg py-1.5 text-[13px] font-semibold text-ink sm:col-span-1">Add alert</button>
      {err && <div className="col-span-full text-down">{err}</div>}
    </form>
  );
}
