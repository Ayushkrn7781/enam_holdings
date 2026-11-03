import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Layers, List, Pin, PinOff, SlidersHorizontal, Check } from "lucide-react";
import { api, type Digest, type Signal } from "../lib/api";
import { clock, longDate, pct, relTime, shortDate, tone } from "../lib/format";
import { go, href } from "../lib/router";
import { Button, DemoBadge, Empty, ErrorBox, LoadingRows, PriorityLabel, Segmented, Skeleton, Strip, useAsk, useAsync } from "../components/ui";

type Win = "24" | "72" | "168" | "custom";

function ResultsPreview({ s, compact }: { s: Signal; compact?: boolean }) {
  const rp = s.results_preview;
  if (!rp) return null;
  if (compact) {
    return (
      <div className="w-cond mt-1 flex flex-wrap gap-x-3 text-[13px] text-dim">
        {rp.rows.map((r) => <span key={r.key}>{r.label} <span className={tone(r.yoy)}>{r.current === null ? "N/A" : pct(r.yoy)}</span></span>)}
        <span>YoY</span>
      </div>
    );
  }
  return (
    <div className="mt-3 grid grid-cols-4 gap-2 border-y border-line py-2.5">
      {rp.rows.map((r) => (
        <div key={r.key} className="min-w-0">
          <div className="text-[12px] text-dim">{r.label}</div>
          <div className={`w-cond text-[18px] font-semibold leading-tight ${r.current === null ? "text-faint" : tone(r.yoy)}`}>
            {r.current === null ? "N/A" : pct(r.yoy)}
          </div>
        </div>
      ))}
      <div className="col-span-4 -mt-1 text-[11px] text-faint">YoY, {rp.period_label}{rp.verification === "verified" ? ", verified against the filing" : ""}</div>
    </div>
  );
}

function BioPreview({ s }: { s: Signal }) {
  const b = s.bio_preview;
  if (!b) return null;
  return (
    <div className="mt-3 border-y border-line py-2.5">
      <div className="flex items-baseline gap-2">
        <span className="font-semibold">{b.name}</span>
        <span className={`text-[13px] ${b.change === "joins" ? "text-up" : "text-warn"}`}>
          {b.change === "joins" ? "joins as" : b.change === "leaves" ? "leaves as" : "retires as"} {b.role}
        </span>
      </div>
      {b.profile && <p className="clamp-3 mt-1 text-[13px] leading-snug text-dim">{b.profile}</p>}
    </div>
  );
}

function Card({ s, anchor }: { s: Signal; anchor: string }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-baseline gap-2">
        <span className="w-cond text-[18px] font-bold">{s.ticker}</span>
        <span className="truncate text-[13px] text-dim">{s.company}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-dim">
        <PriorityLabel p={s.priority} score={s.score} />
        <span>{s.category_label}</span>
        <span>{relTime(s.published_at, anchor)}</span>
        <DemoBadge show={s.source === "demo"} />
      </div>
      <p className="mt-2.5 text-[17px] font-semibold leading-snug">{s.summary}</p>
      <ResultsPreview s={s} />
      <BioPreview s={s} />
      <div className="mt-auto pt-4">
        <Strip breakdown={s.breakdown} height={7} />
        <p className="mt-1.5 text-[12px] leading-snug text-dim">{s.why_rank}</p>
      </div>
    </div>
  );
}

function Deck({ items, anchor, onTriage }: { items: Signal[]; anchor: string; onTriage: (s: Signal, a: "pin" | "dismiss") => void }) {
  const ask = useAsk();
  const [idx, setIdx] = useState(0);
  const [dx, setDx] = useState(0);
  const [pinned, setPinned] = useState<Signal[]>([]);
  const start = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const top = items[idx];
  useEffect(() => { if (top) ask.setTicker(top.ticker); /* eslint-disable-next-line */ }, [top?.id]);

  const act = (a: "pin" | "dismiss") => {
    if (!top) return;
    onTriage(top, a);
    if (a === "pin") setPinned((p) => [...p, top]);
    setDx(0);
    setIdx((i) => i + 1);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") { e.preventDefault(); act("pin"); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); act("dismiss"); }
    else if (e.key === "Enter" && top) go(`signal/${top.id}`);
  };

  if (!top) {
    return (
      <div className="rounded-sheet border border-line bg-surface p-5">
        <div className="w-wide text-[18px] font-bold">Brief cleared</div>
        <p className="mt-1 text-[14px] text-dim">You reviewed all {items.length} material filings.</p>
        {pinned.length > 0 && (
          <div className="mt-4">
            <div className="text-[13px] text-dim">Pinned</div>
            <ul className="hairline mt-1">
              {pinned.map((p) => (
                <li key={p.id}><a href={href(`signal/${p.id}`)} className="flex gap-2 py-2 text-[14px] hover:text-info">
                  <span className="w-cond font-semibold">{p.ticker}</span><span className="truncate text-dim">{p.summary}</span></a></li>
              ))}
            </ul>
          </div>
        )}
        <Button className="mt-4" onClick={() => { setIdx(0); setPinned([]); }}>Review again</Button>
      </div>
    );
  }

  const rot = dx / 28;
  return (
    <div>
      <div className="relative grid select-none pb-[18px]" tabIndex={0} onKeyDown={onKey} aria-label="Triage deck. Right arrow pins, left arrow marks seen, Enter opens.">
        {items.slice(idx + 1, idx + 3).reverse().map((s, i, arr) => {
          const depth = arr.length - i;
          return (
            <div key={s.id} className="rounded-sheet border border-line bg-surface [grid-area:1/1]"
              style={{ transform: `translateY(${depth * 10}px) scale(${1 - depth * 0.04})`, opacity: 1 - depth * 0.25 }} aria-hidden />
          );
        })}
        <div
          className="relative cursor-grab touch-pan-y rounded-sheet [grid-area:1/1] border border-line bg-raised p-4 shadow-[0_10px_30px_rgba(0,0,0,.35)] active:cursor-grabbing"
          style={{ transform: `translateX(${dx}px) rotate(${rot}deg)`, transition: start.current ? "none" : "transform 180ms ease-out" }}
          onPointerDown={(e) => { start.current = { x: e.clientX, y: e.clientY, moved: false }; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); }}
          onPointerMove={(e) => {
            if (!start.current) return;
            const d = e.clientX - start.current.x;
            if (Math.abs(d) > 6) start.current.moved = true;
            setDx(d);
          }}
          onPointerUp={() => {
            const st = start.current;
            start.current = null;
            if (!st) return;
            if (dx > 90) act("pin");
            else if (dx < -90) act("dismiss");
            else { setDx(0); if (!st.moved) go(`signal/${top.id}`); }
          }}
          onPointerCancel={() => { start.current = null; setDx(0); }}
        >
          {dx > 30 && <div className="absolute right-4 top-4 rotate-6 rounded border-2 border-up px-2 py-0.5 text-[14px] font-bold text-up" style={{ opacity: Math.min(1, dx / 90) }}>Pin</div>}
          {dx < -30 && <div className="absolute left-4 top-4 -rotate-6 rounded border-2 border-dim px-2 py-0.5 text-[14px] font-bold text-dim" style={{ opacity: Math.min(1, -dx / 90) }}>Seen</div>}
          <Card s={top} anchor={anchor} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-[1fr_1.5fr_1fr] gap-2">
        <Button onClick={() => act("dismiss")}><Check size={16} /> Seen</Button>
        <Button primary onClick={() => go(`signal/${top.id}`)}>Why it matters</Button>
        <Button onClick={() => act("pin")}><Pin size={16} /> Pin</Button>
      </div>
      <div className="mt-2 text-center text-[12px] text-dim"><span className="w-cond">{idx}</span> of <span className="w-cond">{items.length}</span> reviewed. Swipe right to pin, left when seen.</div>
    </div>
  );
}

function ListView({ items, anchor, onTriage }: { items: Signal[]; anchor: string; onTriage: (s: Signal, a: "pin" | "clear") => void }) {
  return (
    <ul className="hairline border-y border-line">
      {items.map((s) => (
        <li key={s.id} className="flex gap-3 py-3">
          <a href={href(`signal/${s.id}`)} className="min-w-0 flex-1 hover:[&_p]:text-info">
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[13px] text-dim">
              <span className="w-cond text-[15px] font-bold text-fg">{s.ticker}</span>
              <PriorityLabel p={s.priority} score={s.score} />
              <span>{s.category_label}</span>
              <span>{relTime(s.published_at, anchor)}</span>
              <DemoBadge show={s.source === "demo"} />
            </div>
            <p className="mt-1 text-[15px] font-medium leading-snug">{s.summary}</p>
            <ResultsPreview s={s} compact />
            <div className="mt-2 max-w-[360px]"><Strip breakdown={s.breakdown} height={4} /></div>
          </a>
          <button onClick={() => onTriage(s, s.triage === "pin" ? "clear" : "pin")} aria-pressed={s.triage === "pin"}
            aria-label={s.triage === "pin" ? `Unpin ${s.ticker}` : `Pin ${s.ticker}`}
            className={`self-start rounded p-1.5 ${s.triage === "pin" ? "text-info" : "text-faint hover:text-fg"}`}>
            {s.triage === "pin" ? <PinOff size={17} /> : <Pin size={17} />}
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function Brief() {
  const [win, setWin] = useState<Win>("24");
  const [cStart, setCStart] = useState("");
  const [cEnd, setCEnd] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [sector, setSector] = useState("");
  const [category, setCategory] = useState("");
  const [minP, setMinP] = useState("");
  const [view, setView] = useState<"deck" | "list">(() => (window.matchMedia("(min-width: 768px)").matches ? "list" : "deck"));
  const [showRoutine, setShowRoutine] = useState(false);
  const cats = useAsync(() => api.categories(), []);
  const pf = useAsync(() => api.portfolio(), []);

  const params = useMemo(() => {
    const p: Record<string, unknown> = { sector, category: category || undefined, min_priority: minP };
    if (win === "custom") { if (cStart) p.start = cStart; if (cEnd) p.end = cEnd; p.hours = 2160; }
    else p.hours = Number(win);
    return p;
  }, [win, cStart, cEnd, sector, category, minP]);
  const { data, error, loading, reload, setData } = useAsync<Digest>(() => api.digest(params), [JSON.stringify(params)]);

  const triage = (s: Signal, a: "pin" | "dismiss" | "clear") => {
    api.triage(s.id, a).catch(() => {});
    if (data) setData({ ...data, items: data.items.map((x) => (x.id === s.id ? { ...x, triage: a === "clear" ? null : a } : x)) });
  };

  return (
    <div>
      {loading && !data ? (
        <div className="space-y-3"><Skeleton className="h-3 w-40" /><Skeleton className="h-9 w-4/5" /><Skeleton className="h-4 w-2/3" /></div>
      ) : data ? (
        <>
          <div className="text-[13px] text-dim">{longDate(data.anchor)}{data.data_mode === "demo" ? ", dataset close" : `, ${clock(data.anchor)} IST`}</div>
          <h1 className="w-wide mt-1 text-[25px] font-bold leading-tight md:text-[32px]">{data.headline}</h1>
          {data.lines.length > 0 && (
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[14px]">
              {data.lines.map((l) => (
                <div key={l.label} className="contents">
                  <dt className="text-dim">{l.label}</dt>
                  <dd className="flex flex-wrap gap-x-2.5">
                    {l.tickers.map((t) => <a key={t} href={href(`research/${t}`)} className="w-cond font-semibold hover:text-info">{t}</a>)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Segmented<Win> label="Time window" value={win} onChange={setWin}
          options={[{ value: "24", label: "24h" }, { value: "72", label: "3d" }, { value: "168", label: "7d" }, { value: "custom", label: "Custom" }]} />
        <button onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}
          className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-[13px] ${showFilters || sector || category || minP ? "border-info/50 text-fg" : "border-line text-dim"}`}>
          <SlidersHorizontal size={14} /> Filter
        </button>
        <div className="ml-auto inline-flex rounded border border-line p-0.5" role="radiogroup" aria-label="View">
          <button role="radio" aria-checked={view === "deck"} aria-label="Triage deck" onClick={() => setView("deck")}
            className={`rounded-[4px] p-1.5 ${view === "deck" ? "bg-raised text-fg" : "text-dim"}`}><Layers size={16} /></button>
          <button role="radio" aria-checked={view === "list"} aria-label="List" onClick={() => setView("list")}
            className={`rounded-[4px] p-1.5 ${view === "list" ? "bg-raised text-fg" : "text-dim"}`}><List size={16} /></button>
        </div>
      </div>
      {win === "custom" && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
          <label className="flex items-center gap-1.5 text-dim">From <input type="date" value={cStart} onChange={(e) => setCStart(e.target.value)} className="rounded border border-line bg-surface px-2 py-1 text-fg" /></label>
          <label className="flex items-center gap-1.5 text-dim">To <input type="date" value={cEnd} onChange={(e) => setCEnd(e.target.value)} className="rounded border border-line bg-surface px-2 py-1 text-fg" /></label>
        </div>
      )}
      {showFilters && (
        <div className="mt-2 grid grid-cols-1 gap-2 rounded border border-line p-3 text-[13px] sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-dim">Sector
            <select value={sector} onChange={(e) => setSector(e.target.value)} className="rounded border border-line bg-surface px-2 py-1.5 text-fg">
              <option value="">All sectors</option>
              {(pf.data?.sectors || []).map((s: string) => <option key={s}>{s}</option>)}
            </select></label>
          <label className="flex flex-col gap-1 text-dim">Category
            <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded border border-line bg-surface px-2 py-1.5 text-fg">
              <option value="">All categories</option>
              {(cats.data?.categories || []).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select></label>
          <label className="flex flex-col gap-1 text-dim">Priority at least
            <select value={minP} onChange={(e) => setMinP(e.target.value)} className="rounded border border-line bg-surface px-2 py-1.5 text-fg">
              <option value="">Any</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option>
            </select></label>
        </div>
      )}

      {error && <div className="mt-4"><ErrorBox what="the brief" error={error} retry={reload} /></div>}
      {loading && !data && <div className="mt-5"><LoadingRows n={3} /></div>}
      {data && (
        <>
          <p className="mt-4 text-[13px] text-dim">
            <span className="w-cond text-fg">{data.counts.filings}</span> filings from <span className="w-cond text-fg">{data.counts.companies}</span> companies:{" "}
            <span className="w-cond">{data.counts.critical}</span> critical, <span className="w-cond">{data.counts.high}</span> high,{" "}
            <span className="w-cond">{data.counts.medium}</span> medium, <span className="w-cond">{data.counts.routine}</span> routine collapsed
          </p>
          <div className="mt-3">
            {data.items.length === 0 ? (
              <Empty title="Nothing material in this window">Widen the window to 7 days, or loosen the filters.</Empty>
            ) : view === "deck" ? (
              <Deck key={JSON.stringify(params)} items={data.items} anchor={data.anchor} onTriage={triage} />
            ) : (
              <ListView items={data.items} anchor={data.anchor} onTriage={triage} />
            )}
          </div>

          {data.moves.length > 0 && (
            <section className="mt-8">
              <h2 className="w-semi text-[17px] font-semibold">Unusual end-of-day moves</h2>
              <ul className="hairline mt-2 border-y border-line">
                {data.moves.map((m, i) => (
                  <li key={i}><a href={href(`research/${m.ticker}`)} className="flex items-center gap-3 py-2.5 text-[14px] hover:text-info">
                    <span className="w-cond w-24 shrink-0 font-semibold">{m.ticker}</span>
                    <span className="min-w-0 flex-1 truncate text-dim">{m.kind === "volume" ? "Volume vs 20-day avg" : "Day move"}, {shortDate(m.date)}</span>
                    <span className={`w-cond text-[16px] font-semibold ${m.kind === "volume" ? "text-warn" : tone(m.value)}`}>
                      {m.kind === "volume" ? `${m.value.toFixed(1)}×` : pct(m.value)}
                    </span>
                  </a></li>
                ))}
              </ul>
            </section>
          )}

          {data.routine.length > 0 && (
            <section className="mt-8">
              <button onClick={() => setShowRoutine(!showRoutine)} aria-expanded={showRoutine} className="flex w-full items-start gap-2 text-left">
                <div className="min-w-0 flex-1">
                  <h2 className="w-semi text-[17px] font-semibold">{data.routine.length} routine filings</h2>
                  <p className="mt-0.5 text-[13px] text-dim">{data.routine_summary.map((r) => `${r.label} ${r.count}`).join(", ")}</p>
                </div>
                <ChevronDown size={18} className={`mt-1 text-dim transition-transform ${showRoutine ? "rotate-180" : ""}`} />
              </button>
              {showRoutine && (
                <ul className="hairline mt-2 border-y border-line">
                  {data.routine.map((s) => (
                    <li key={s.id}><a href={href(`signal/${s.id}`)} className="flex items-baseline gap-3 py-2 text-[14px] hover:text-info">
                      <span className="w-cond w-24 shrink-0 font-semibold">{s.ticker}</span>
                      <span className="min-w-0 flex-1 truncate text-dim">{s.summary}</span>
                      {s.is_duplicate && <span className="shrink-0 text-[12px] text-faint">duplicate</span>}
                    </a></li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
