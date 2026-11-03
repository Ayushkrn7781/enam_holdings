import { Activity, Check, ChevronDown, ChevronRight, Layers, List, Pin, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAsk } from "../components/Ask";
import { post, useApi } from "../lib/api";
import { pct, tone, when } from "../lib/format";
import { go } from "../lib/router";
import { Empty, ErrorState, ListSkeleton, MaterialityStrip, PriorityTag, Segmented, SourceBadge } from "../components/ui";

type Win = "24" | "72" | "168" | "custom";

export default function Brief() {
  const [win, setWin] = useState<Win>("24");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [view, setView] = useState<"deck" | "list">(() => (window.innerWidth >= 900 ? "list" : "deck"));
  const [filters, setFilters] = useState<{ sector?: string; category?: string; min_priority?: string }>({});
  const [showFilters, setShowFilters] = useState(false);

  const qs = new URLSearchParams();
  if (win === "custom" && from) { qs.set("start", from + "T00:00:00"); if (to) qs.set("end", to + "T23:59:59"); qs.set("hours", "24"); }
  else qs.set("hours", win === "custom" ? "24" : win);
  if (filters.sector) qs.set("sector", filters.sector);
  if (filters.category) qs.set("category", filters.category);
  if (filters.min_priority) qs.set("min_priority", filters.min_priority);
  const { data, error, loading, reload, setData } = useApi(`/api/digest?${qs}`);
  const cats = useApi("/api/meta/categories");
  const pf = useApi("/api/portfolio");

  const setTriage = (id: number, action: "pin" | "dismiss" | "clear") => {
    setData((d: any) => d && { ...d, material: d.material.map((m: any) => (m.id === id ? { ...m, triage: action === "clear" ? null : action } : m)) });
    post(`/api/signals/${id}/triage`, { action }).catch(() => reload());
  };

  const anchor = data?.window?.end;
  const { ticker, setTicker } = useAsk();
  useEffect(() => { if (!ticker && data?.material?.[0]) setTicker(data.material[0].ticker); }, [data]);
  const nFilters = Object.values(filters).filter(Boolean).length;

  return (
    <div>
      <div className="text-[13px] text-dim">
        {anchor ? new Date(anchor).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" }) : " "}
        {data?.anchored_to_dataset && <span className="text-faint">, dataset close</span>}
      </div>
      {loading && !data ? <div className="mt-3 space-y-2"><div className="skeleton h-7 w-11/12" /><div className="skeleton h-4 w-3/4" /></div> : (
        <>
          <h1 className="w-wide mt-1 text-[25px] font-bold leading-[1.12] tracking-[-0.015em] md:text-[32px]">{data?.headline ?? "Your brief"}</h1>
          {data?.summary_lines?.length > 0 && (
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13.5px]">
              {data.summary_lines.map((l: any) => (
                <div key={l.label} className="contents">
                  <dt className="text-dim">{l.label}</dt>
                  <dd className="flex flex-wrap gap-x-2">{l.tickers.map((t: string) => <button key={t} onClick={() => go("research", t)} className="font-semibold hover:text-info">{t}</button>)}</dd>
                </div>
              ))}
            </dl>
          )}
        </>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Segmented value={win} onChange={setWin} options={[{ value: "24", label: "24h" }, { value: "72", label: "3d" }, { value: "168", label: "7d" }, { value: "custom", label: "Custom" }]} />
        <button onClick={() => setShowFilters((s) => !s)} aria-label="Filter" className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[13px] ${nFilters ? "border-info text-info" : "border-line text-dim hover:text-fg"}`}>
          <SlidersHorizontal className="h-3.5 w-3.5" />{nFilters ? nFilters : <span className="hidden sm:inline">Filter</span>}
        </button>
        <div className="ml-auto inline-flex rounded border border-line bg-surface p-0.5">
          <button onClick={() => setView("deck")} aria-label="Triage view" aria-pressed={view === "deck"} className={`rounded-sm p-1 ${view === "deck" ? "bg-raised text-fg" : "text-dim"}`}><Layers className="h-4 w-4" /></button>
          <button onClick={() => setView("list")} aria-label="List view" aria-pressed={view === "list"} className={`rounded-sm p-1 ${view === "list" ? "bg-raised text-fg" : "text-dim"}`}><List className="h-4 w-4" /></button>
        </div>
      </div>
      {win === "custom" && (
        <div className="mt-2 flex items-center gap-2 text-[13px]">
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="rounded border border-line bg-surface px-2 py-1" aria-label="From date" />
          <span className="text-dim">to</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="rounded border border-line bg-surface px-2 py-1" aria-label="To date" />
        </div>
      )}
      {showFilters && (
        <div className="mt-2 grid grid-cols-1 gap-2 rounded border border-line bg-surface p-3 text-[13px] sm:grid-cols-3">
          <Select label="Sector" value={filters.sector} onChange={(v) => setFilters({ ...filters, sector: v })} options={(pf.data?.sectors ?? []).map((s: string) => [s, s])} />
          <Select label="Category" value={filters.category} onChange={(v) => setFilters({ ...filters, category: v })} options={(cats.data ?? []).map((c: any) => [c.key, c.label])} />
          <Select label="Priority at least" value={filters.min_priority} onChange={(v) => setFilters({ ...filters, min_priority: v })} options={[["critical", "Critical"], ["high", "High"], ["medium", "Medium"]]} />
        </div>
      )}

      {data && (
        <div className="num mt-3 text-[12.5px] text-dim">
          {data.counts.total} filings from {data.counts.companies} companies: <span className="text-down">{data.counts.critical} critical</span>, <span className="text-warn">{data.counts.high} high</span>, <span className="text-info">{data.counts.medium} medium</span>, {data.counts.routine} routine collapsed
        </div>
      )}

      <div className="mt-5">
        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && !data && <ListSkeleton rows={3} />}
        {data && (data.material.length === 0 ? (
          <Empty title="Nothing material in this window">Widen the window to 3 or 7 days, or clear filters.</Empty>
        ) : view === "deck" ? (
          <Deck items={data.material} anchor={anchor} onTriage={setTriage} />
        ) : (
          <SignalList items={data.material} anchor={anchor} onTriage={setTriage} />
        ))}
      </div>

      {data?.moves?.length > 0 && <Moves moves={data.moves} />}
      {data?.routine?.length > 0 && <Routine items={data.routine} anchor={anchor} />}
    </div>
  );
}

function Select({ label, value, onChange, options }: { label: string; value?: string; onChange: (v?: string) => void; options: [string, string][] }) {
  return (
    <label className="flex flex-col gap-1 text-dim">
      {label}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)} className="rounded border border-line bg-ink px-2 py-1.5 text-fg">
        <option value="">All</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

/* ------------------------------------------------------------------ triage deck */

function Deck({ items, anchor, onTriage }: { items: any[]; anchor?: string; onTriage: (id: number, a: "pin" | "dismiss" | "clear") => void }) {
  const queue = items.filter((i) => !i.triage);
  const pinned = items.filter((i) => i.triage === "pin");
  const [dx, setDx] = useState(0);
  const start = useRef<number | null>(null);
  const top = queue[0];
  const done = items.length - queue.length;
  const { setTicker } = useAsk();
  useEffect(() => { if (top) setTicker(top.ticker); }, [top?.ticker]);

  const commit = (action: "pin" | "dismiss") => { if (!top) return; setDx(action === "pin" ? 420 : -420); setTimeout(() => { onTriage(top.id, action); setDx(0); }, 160); };
  const onDown = (e: React.PointerEvent) => { start.current = e.clientX; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); };
  const onMove = (e: React.PointerEvent) => { if (start.current != null) setDx(e.clientX - start.current); };
  const onUp = () => {
    if (start.current == null) return;
    const d = dx;
    start.current = null;
    if (d > 90) commit("pin");
    else if (d < -90) commit("dismiss");
    else { setDx(0); if (Math.abs(d) < 6 && top) go("signal", top.id); }
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-[12.5px] text-dim">
        <span className="num">{top ? `${done + 1} of ${items.length}` : `${items.length} of ${items.length}`} reviewed</span>
        <span className="hidden sm:inline">Swipe right to pin, left when seen, tap to open</span>
      </div>
      {top ? (
        <div className="relative h-[322px] select-none">
          {queue.slice(1, 3).reverse().map((it, i, arr) => {
            const depth = arr.length - i;
            return <div key={it.id} className="absolute inset-x-0 top-0 rounded-deck border border-line bg-surface" style={{ transform: `translateY(${depth * 10}px) scale(${1 - depth * 0.035})`, height: 300, opacity: 1 - depth * 0.28 }} aria-hidden />;
          })}
          <div onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={() => { start.current = null; setDx(0); }}
            onKeyDown={(e) => { if (e.key === "ArrowRight") commit("pin"); if (e.key === "ArrowLeft") commit("dismiss"); if (e.key === "Enter") go("signal", top.id); }}
            tabIndex={0} role="button" aria-label={`${top.ticker}: ${top.summary}. Enter to open, right arrow to pin, left arrow to mark seen.`}
            className="absolute inset-x-0 top-0 h-[300px] cursor-grab touch-pan-y rounded-deck border border-line bg-raised p-4 shadow-[0_16px_40px_rgba(0,0,0,.35)] active:cursor-grabbing"
            style={{ transform: `translateX(${dx}px) rotate(${dx / 28}deg)`, transition: start.current == null ? "transform .18s ease-out" : "none" }}>
            {dx > 30 && <div className="absolute right-4 top-4 rounded-sm border border-up px-2 py-0.5 text-[12px] font-bold text-up" style={{ opacity: Math.min(1, dx / 90) }}>Pin</div>}
            {dx < -30 && <div className="absolute left-4 top-4 rounded-sm border border-dim px-2 py-0.5 text-[12px] font-bold text-dim" style={{ opacity: Math.min(1, -dx / 90) }}>Seen</div>}
            <SignalCardBody it={top} anchor={anchor} />
          </div>
        </div>
      ) : (
        <div className="rounded-deck border border-line bg-surface p-5">
          <div className="flex items-center gap-2 font-semibold"><Check className="h-4 w-4 text-up" />Brief cleared</div>
          <div className="mt-1 text-sm text-dim">{pinned.length ? `${pinned.length} pinned for follow-up.` : "Nothing pinned."}</div>
          <button onClick={() => items.forEach((i) => onTriage(i.id, "clear"))} className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-info hover:underline"><RotateCcw className="h-3.5 w-3.5" />Review again</button>
        </div>
      )}
      {top && (
        <div className="mt-3 grid grid-cols-3 gap-2">
          <button onClick={() => commit("dismiss")} className="flex items-center justify-center gap-1.5 rounded border border-line py-2.5 text-[13.5px] text-dim hover:text-fg"><X className="h-4 w-4" />Seen</button>
          <button onClick={() => go("signal", top.id)} className="flex items-center justify-center gap-1.5 rounded bg-fg py-2.5 text-[13.5px] font-semibold text-ink">Why it matters</button>
          <button onClick={() => commit("pin")} className="flex items-center justify-center gap-1.5 rounded border border-up/50 py-2.5 text-[13.5px] text-up hover:bg-up/10"><Pin className="h-4 w-4" />Pin</button>
        </div>
      )}
      {pinned.length > 0 && (
        <div className="mt-6">
          <div className="mb-1 text-[13px] font-semibold">Pinned</div>
          <SignalList items={pinned} anchor={anchor} onTriage={onTriage} compact />
        </div>
      )}
    </div>
  );
}

function topReason(it: any) {
  return it.why_rank as string | undefined;
}

function SignalCardBody({ it, anchor }: { it: any; anchor?: string }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 pr-12">
        <div className="min-w-0">
          <span className="text-[15px] font-bold">{it.ticker}</span>
          <span className="ml-2 truncate text-[12.5px] text-dim">{it.company}</span>
        </div>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-dim">
        <PriorityTag p={it.priority} score={it.score} />
        <span>{it.category_label}</span>
        <span>{when(it.published_at, anchor)}</span>
        <SourceBadge source={it.source} />
      </div>
      <div className="mt-3 text-[17px] font-semibold leading-snug">{it.summary}</div>
      {it.results_preview && (
        <div className="num mt-3 grid grid-cols-4 gap-2 border-t border-line pt-3">
          {it.results_preview.map((r: any) => (
            <div key={r.label}>
              <div className="text-[11.5px] text-dim">{r.label} YoY</div>
              <div className={`w-cond text-[18px] font-semibold ${tone(r.yoy_pct)}`}>{pct(r.yoy_pct)}</div>
            </div>
          ))}
        </div>
      )}
      {it.bio_preview && (
        <div className="mt-3 border-t border-line pt-3 text-[13px]">
          <div><span className="font-semibold">{it.bio_preview.name}</span> <span className="text-dim">{it.bio_preview.change === "appointment" ? "joins as" : "leaves as"} {it.bio_preview.role}</span></div>
          {it.bio_preview.profile && <div className="mt-1 line-clamp-3 text-dim">{it.bio_preview.profile}</div>}
        </div>
      )}
      <div className="mt-auto pt-3">
        <MaterialityStrip breakdown={it.breakdown} score={it.score} />
        {topReason(it) && <div className="mt-1.5 line-clamp-1 text-[12px] text-dim">{topReason(it)}</div>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ list view */

function SignalList({ items, anchor, onTriage, compact }: { items: any[]; anchor?: string; onTriage: (id: number, a: "pin" | "dismiss" | "clear") => void; compact?: boolean }) {
  return (
    <ul className="divide-y divide-line border-y border-line">
      {items.map((it) => (
        <li key={it.id} className={`group flex gap-3 py-3 ${it.triage === "dismiss" ? "opacity-55" : ""}`}>
          <button onClick={() => go("signal", it.id)} className="min-w-0 flex-1 text-left">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-dim">
              <span className="text-[14px] font-bold text-fg">{it.ticker}</span>
              <PriorityTag p={it.priority} score={it.score} />
              <span>{it.category_label}</span>
              <span>{when(it.published_at, anchor)}</span>
              <SourceBadge source={it.source} />
            </div>
            <div className="mt-1 text-[14.5px] leading-snug">{it.summary}</div>
            {!compact && it.results_preview && (
              <div className="num mt-1 flex flex-wrap gap-x-4 text-[12.5px] text-dim">
                {it.results_preview.map((r: any) => <span key={r.label}>{r.label} <span className={tone(r.yoy_pct)}>{pct(r.yoy_pct)}</span> YoY</span>)}
              </div>
            )}
            {!compact && <div className="mt-2 max-w-md"><MaterialityStrip breakdown={it.breakdown} score={it.score} height={4} /></div>}
          </button>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <button onClick={() => onTriage(it.id, it.triage === "pin" ? "clear" : "pin")} aria-label={it.triage === "pin" ? "Unpin" : "Pin"}
              className={`rounded p-1.5 ${it.triage === "pin" ? "text-up" : "text-faint hover:text-fg"}`}><Pin className="h-4 w-4" /></button>
            <ChevronRight className="mt-auto h-4 w-4 text-faint" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Moves({ moves }: { moves: any[] }) {
  return (
    <div className="mt-8">
      <div className="mb-2 flex items-center gap-2 text-[15px] font-semibold"><Activity className="h-4 w-4 text-warn" />Unusual end-of-day moves</div>
      <ul className="divide-y divide-line border-y border-line">
        {moves.map((m) => (
          <li key={m.id}>
            <button onClick={() => go("research", m.ticker)} className="flex w-full items-center gap-3 py-2.5 text-left">
              <span className="w-24 shrink-0 text-[14px] font-bold">{m.ticker}</span>
              <span className="min-w-0 flex-1 text-[13px] text-dim">{m.kind === "volume" ? `volume vs 20-day average; ${m.message.match(/\((.*)\)/)?.[1] ?? ""}` : m.message.replace(`${m.ticker} `, "")}</span>
              <span className={`num w-cond shrink-0 text-[16px] font-semibold ${m.kind === "volume" ? "text-warn" : tone(m.value)}`}>{m.kind === "volume" ? `${m.value.toFixed(1)}×` : pct(m.value)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Routine({ items, anchor }: { items: any[]; anchor?: string }) {
  const [open, setOpen] = useState(false);
  const byCat = useMemo(() => items.reduce((a: Record<string, number>, i) => ({ ...a, [i.category_label]: (a[i.category_label] ?? 0) + 1 }), {}), [items]);
  return (
    <div className="mt-8">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 text-left" aria-expanded={open}>
        <Layers className="h-4 w-4 text-faint" />
        <span className="shrink-0 whitespace-nowrap text-[15px] font-semibold">{items.length} routine filings</span>
        <span className="truncate text-[12.5px] text-dim">{Object.entries(byCat).map(([k, v]) => `${k} ${v}`).join(", ")}</span>
        <ChevronDown className={`ml-auto h-4 w-4 shrink-0 text-dim transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul className="mt-2 divide-y divide-line border-y border-line">
          {items.map((it) => (
            <li key={it.id}>
              <button onClick={() => go("signal", it.id)} className="flex w-full items-baseline gap-3 py-2 text-left text-[13px]">
                <span className="w-24 shrink-0 font-semibold">{it.ticker}</span>
                <span className="min-w-0 flex-1 text-dim">{it.subject}{it.is_duplicate && <span className="ml-1 text-faint">(duplicate)</span>}</span>
                <span className="shrink-0 text-[12px] text-faint">{when(it.published_at, anchor)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
