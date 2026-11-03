import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { shortDate } from "../lib/format";
import { href } from "../lib/router";
import { Button, Empty, ErrorBox, LoadingRows, PriorityDot, Section, Toggle, useAsync } from "../components/ui";

function ThresholdInput({ rule, onSave }: { rule: any; onSave: (v: number) => void }) {
  const [v, setV] = useState(String(rule.threshold ?? ""));
  useEffect(() => setV(String(rule.threshold ?? "")), [rule.threshold]);
  return (
    <label className="inline-flex items-center gap-1 text-[13px] text-dim">
      <input value={v} onChange={(e) => setV(e.target.value)} inputMode="decimal" aria-label="Threshold"
        onBlur={() => { const n = Number(v); if (n > 0 && n !== rule.threshold) onSave(n); else setV(String(rule.threshold)); }}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
        className="w-cond w-14 rounded border border-line bg-surface px-1.5 py-1 text-right text-fg" />
      {rule.kind === "volume" ? "×" : "%"}
    </label>
  );
}

export default function Alerts({ onSeen }: { onSeen: () => void }) {
  const { data, error, loading, reload } = useAsync<any>(() => api.alerts(), []);
  const [kind, setKind] = useState("volume");
  const [threshold, setThreshold] = useState("2");
  const [category, setCategory] = useState("results");
  const [ticker, setTicker] = useState("");
  const [priority, setPriority] = useState("high");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => { api.alertsSeen().then(onSeen).catch(() => {}); /* eslint-disable-next-line */ }, []);

  const patch = (id: number, body: any) => api.patchAlert(id, body).then(reload).catch((e) => setMsg(e.message));
  const del = (id: number) => { if (window.confirm("Delete this alert rule and its history?")) api.deleteAlert(id).then(reload).catch((e) => setMsg(e.message)); };
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);
    try {
      await api.addAlert({ kind, priority, ticker: ticker.trim() || null,
        ...(kind === "category" ? { category } : { threshold: Number(threshold) }) });
      setTicker("");
      setMsg("Alert added. FINN checked it against the last 10 sessions and 14 days of filings.");
      reload();
    } catch (err: any) { setMsg(`Could not add the alert: ${err.message}`); }
  };

  return (
    <div>
      <h1 className="w-semi text-[24px] font-bold">You decide what counts as unusual.</h1>
      <p className="mt-1 text-[14px] text-dim">{data?.monitoring_note || "End-of-day monitoring. Not real-time."}</p>
      {error && <div className="mt-4"><ErrorBox what="alerts" error={error} retry={reload} /></div>}
      {loading && !data && <div className="mt-4"><LoadingRows n={4} /></div>}
      {data && (
        <>
          <Section title="Rules">
            <ul className="hairline border-y border-line">
              {data.rules.map((r: any) => (
                <li key={r.id} className="flex items-center gap-3 py-2.5">
                  <Toggle on={r.enabled} onChange={(v) => patch(r.id, { enabled: v })} label={`Enable ${r.description}`} />
                  <div className="min-w-0 flex-1">
                    <div className={`text-[14px] ${r.enabled ? "" : "text-faint"}`}>{r.description}</div>
                    <div className="mt-0.5 inline-flex items-center gap-1.5 text-[12px] capitalize text-dim"><PriorityDot p={r.priority} size={7} /> {r.priority}</div>
                  </div>
                  {r.kind !== "category" && <ThresholdInput rule={r} onSave={(v) => patch(r.id, { threshold: v })} />}
                  <button onClick={() => del(r.id)} aria-label={`Delete ${r.description}`} className="rounded p-1.5 text-faint hover:text-down"><Trash2 size={16} /></button>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="New rule">
            <form onSubmit={add} className="grid grid-cols-2 gap-2 text-[13px] sm:grid-cols-5">
              <label className="flex flex-col gap-1 text-dim">When
                <select value={kind} onChange={(e) => { setKind(e.target.value); setThreshold(e.target.value === "volume" ? "2" : "4"); }} className="rounded border border-line bg-surface px-2 py-1.5 text-fg">
                  <option value="volume">Volume spike</option><option value="price_up">Price up</option>
                  <option value="price_down">Price down</option><option value="category">Filing type</option>
                </select></label>
              {kind === "category" ? (
                <label className="flex flex-col gap-1 text-dim">Type
                  <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded border border-line bg-surface px-2 py-1.5 text-fg">
                    {data.categories.map((c: any) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select></label>
              ) : (
                <label className="flex flex-col gap-1 text-dim">Threshold {kind === "volume" ? "(× avg)" : "(%)"}
                  <input value={threshold} onChange={(e) => setThreshold(e.target.value)} inputMode="decimal" className="w-cond rounded border border-line bg-surface px-2 py-1.5 text-fg" /></label>
              )}
              <label className="flex flex-col gap-1 text-dim">Company
                <input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="Any holding" className="w-cond rounded border border-line bg-surface px-2 py-1.5 text-fg placeholder:text-faint" /></label>
              <label className="flex flex-col gap-1 text-dim">Priority
                <select value={priority} onChange={(e) => setPriority(e.target.value)} className="rounded border border-line bg-surface px-2 py-1.5 text-fg">
                  <option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
                </select></label>
              <div className="col-span-2 flex items-end sm:col-span-1"><Button primary type="submit" className="w-full">Add alert</Button></div>
            </form>
            {msg && <p className="mt-2 text-[13px] text-dim" role="status">{msg}</p>}
          </Section>

          <Section title="History">
            {data.events.length === 0 ? <Empty title="No alerts fired yet">Lower a threshold above, or widen the filing types you watch.</Empty> : (
              <ul className="hairline border-y border-line">
                {data.events.map((e: any) => (
                  <li key={e.id}>
                    <a href={href(e.announcement_id ? `signal/${e.announcement_id}` : `research/${e.ticker}`)} className="flex items-start gap-3 py-2.5 hover:[&_.msg]:text-info">
                      <span className="mt-1.5"><PriorityDot p={e.priority || "low"} size={7} /></span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2"><span className="w-cond font-semibold">{e.ticker}</span><span className="text-[12px] text-dim">{shortDate(e.triggered_at)}</span>{!e.seen && <span className="text-[11px] text-info">new</span>}</div>
                        <div className="msg truncate text-[14px] text-fg/85">{e.message}</div>
                        <div className="text-[12px] text-faint">{e.rule}</div>
                      </div>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}
    </div>
  );
}
