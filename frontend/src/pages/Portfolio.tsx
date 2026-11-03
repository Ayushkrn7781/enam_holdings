import { Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Empty, ErrorState, ListSkeleton, PriorityTag, Segmented, Sparkline } from "../components/ui";
import { api, del, post, useApi } from "../lib/api";
import { pct, rupee, tone } from "../lib/format";
import { go } from "../lib/router";

type Sort = "signals" | "move" | "volume" | "name";

export default function Portfolio() {
  const { data, error, loading, reload } = useApi("/api/portfolio");
  const [sector, setSector] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>("signals");
  const [edit, setEdit] = useState(false);

  const items = useMemo(() => {
    const xs = (data?.items ?? []).filter((i: any) => !sector || i.sector === sector);
    const key: Record<Sort, (i: any) => number | string> = {
      signals: (i) => -(i.top_score_7d ?? 0), move: (i) => -Math.abs(i.price?.return_pct ?? 0),
      volume: (i) => -(i.price?.volume_ratio ?? 0), name: (i) => i.ticker,
    };
    return [...xs].sort((a, b) => (key[sort](a) < key[sort](b) ? -1 : 1));
  }, [data, sector, sort]);

  const day = data?.items?.[0]?.price?.date;
  const avg = data?.items?.length ? data.items.reduce((s: number, i: any) => s + (i.price?.return_pct ?? 0), 0) / data.items.length : null;
  const adv = data?.items?.filter((i: any) => (i.price?.return_pct ?? 0) > 0).length ?? 0;

  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="w-semi text-[24px] font-semibold">Portfolio</h1>
          {data && <div className="num text-[13px] text-dim">{data.count} holdings, equal-weight day move <span className={tone(avg)}>{pct(avg, true, 2)}</span>, {adv} up and {data.count - adv} down{day ? ` on ${new Date(day).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} (EOD)` : ""}</div>}
        </div>
        <button onClick={() => setEdit(!edit)} className="text-[13px] text-info hover:underline">{edit ? "Done" : "Edit"}</button>
      </div>

      <AddTicker onAdded={reload} />

      <div className="no-scrollbar -mx-4 mt-3 flex gap-2 overflow-x-auto px-4">
        {[null, ...(data?.sectors ?? [])].map((s: string | null) => (
          <button key={s ?? "all"} onClick={() => setSector(s)} className={`shrink-0 rounded-full border px-3 py-1 text-[12.5px] ${sector === s ? "border-fg bg-fg text-ink" : "border-line text-dim hover:text-fg"}`}>{s ?? "All sectors"}</button>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between text-[12.5px] text-dim">
        <span>Sort by</span>
        <Segmented size="sm" value={sort} onChange={setSort} options={[{ value: "signals", label: "Signals" }, { value: "move", label: "Move" }, { value: "volume", label: "Volume" }, { value: "name", label: "A–Z" }]} />
      </div>

      <div className="mt-3">
        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && !data && <ListSkeleton rows={6} />}
        {data && items.length === 0 && <Empty title="No holdings yet">Add an NSE ticker above to start monitoring it.</Empty>}
        <ul className="divide-y divide-line border-y border-line">
          {items.map((i: any) => (
            <li key={i.ticker} className="flex items-center gap-3 py-2.5">
              <button onClick={() => go("research", i.ticker)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2"><span className="text-[14.5px] font-bold">{i.ticker}</span>{i.signals_7d > 0 && <PriorityTag p={i.top_score_7d >= 80 ? "critical" : i.top_score_7d >= 60 ? "high" : "medium"} />}</div>
                  <div className="truncate text-[12px] text-dim">{i.name}</div>
                </div>
                <Sparkline data={i.spark} />
                <div className="num w-[92px] shrink-0 text-right">
                  <div className="text-[13.5px]">{rupee(i.price?.close)}</div>
                  <div className={`text-[12.5px] ${tone(i.price?.return_pct)}`}>{pct(i.price?.return_pct, true, 2)}</div>
                </div>
                <div className="num hidden w-16 shrink-0 text-right text-[12.5px] sm:block">
                  <div className={(i.price?.volume_ratio ?? 0) >= 2 ? "font-semibold text-warn" : "text-dim"}>{i.price?.volume_ratio?.toFixed(1) ?? "N/A"}×</div>
                  <div className="text-[11px] text-faint">vol</div>
                </div>
              </button>
              {edit && (
                <button aria-label={`Remove ${i.ticker}`} onClick={() => { if (confirm(`Remove ${i.ticker} from the portfolio?`)) del(`/api/portfolio/${encodeURIComponent(i.ticker)}`).then(reload); }} className="rounded p-1.5 text-down hover:bg-down/10"><Trash2 className="h-4 w-4" /></button>
              )}
            </li>
          ))}
        </ul>
        {data && <div className="mt-2 text-[11.5px] text-faint">End-of-day prices. Volume is today's volume divided by the 20-session average.</div>}
      </div>
    </div>
  );
}

export function TickerSearch({ onPick, placeholder, cta }: { onPick: (t: string) => void; placeholder: string; cta: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[]>([]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const t = setTimeout(() => api(`/api/companies/search?q=${encodeURIComponent(q.trim())}`).then(setHits).catch(() => setHits([])), 150);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="relative">
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) { onPick((hits[0]?.ticker ?? q).toUpperCase()); setQ(""); } }}
        className="flex items-center gap-2 rounded border border-line bg-surface px-3 focus-within:border-info">
        <Search className="h-4 w-4 text-faint" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label={placeholder} className="min-w-0 flex-1 bg-transparent py-2 text-[14px] placeholder:text-faint focus:outline-none" />
        <button className="inline-flex items-center gap-1 text-[13px] font-semibold text-info"><Plus className="h-4 w-4" />{cta}</button>
      </form>
      {hits.length > 0 && (
        <ul className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded border border-line bg-raised shadow-xl">
          {hits.map((h) => (
            <li key={h.ticker}>
              <button onClick={() => { onPick(h.ticker); setQ(""); setHits([]); }} className="flex w-full items-baseline gap-2 px-3 py-2 text-left hover:bg-surface">
                <span className="text-[13.5px] font-bold">{h.ticker}</span><span className="truncate text-[12.5px] text-dim">{h.name}</span>
                {h.in_portfolio && <span className="ml-auto shrink-0 text-[11px] text-up">Held</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AddTicker({ onAdded }: { onAdded: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="mt-4">
      <TickerSearch placeholder="Add an NSE ticker, e.g. TRENT" cta="Add" onPick={(t) => {
        setMsg(null);
        post("/api/portfolio", { ticker: t }).then(() => { setMsg(`Added ${t}.`); onAdded(); }).catch((e) => setMsg(e.message));
      }} />
      {msg && <div className="mt-1 text-[12.5px] text-dim">{msg}</div>}
    </div>
  );
}
