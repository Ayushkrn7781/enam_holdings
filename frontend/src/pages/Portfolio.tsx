import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, X } from "lucide-react";
import { api } from "../lib/api";
import { pct, price, shortDate, tone } from "../lib/format";
import { go, href } from "../lib/router";
import { Button, Chip, Empty, ErrorBox, LoadingRows, PriorityDot, Spark, useAsync } from "../components/ui";

type Sort = "signals" | "move" | "volume" | "az";

export function TickerSearch({ onPick, placeholder = "Add a company: ticker or name", autoFocus }:
  { onPick: (t: string) => void; placeholder?: string; autoFocus?: boolean }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const t = useRef<number>();
  useEffect(() => {
    window.clearTimeout(t.current);
    if (!q.trim()) { setRes([]); return; }
    t.current = window.setTimeout(() => api.search(q).then((r) => { setRes(r.results); setHi(0); }).catch(() => setRes([])), 140);
  }, [q]);
  const pick = (x: any) => { onPick(x.ticker); setQ(""); setOpen(false); };
  return (
    <div className="relative">
      <input value={q} autoFocus={autoFocus} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)} placeholder={placeholder} aria-label={placeholder}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, res.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
          else if (e.key === "Enter" && res[hi]) { e.preventDefault(); pick(res[hi]); }
        }}
        className="w-full rounded border border-line bg-surface px-3 py-2.5 text-[15px] outline-none placeholder:text-faint focus:border-info/60" />
      {open && res.length > 0 && (
        <ul role="listbox" className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded border border-line bg-raised py-1 shadow-xl">
          {res.map((x, i) => (
            <li key={x.ticker} role="option" aria-selected={i === hi}>
              <button onMouseDown={(e) => e.preventDefault()} onClick={() => pick(x)}
                className={`flex w-full items-baseline gap-2 px-3 py-2 text-left text-[14px] ${i === hi ? "bg-line/60" : ""}`}>
                <span className="w-cond w-24 shrink-0 font-semibold">{x.ticker}</span>
                <span className="min-w-0 flex-1 truncate text-dim">{x.name}</span>
                {x.in_portfolio && <span className="text-[12px] text-faint">held</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Portfolio() {
  const { data, error, loading, reload } = useAsync<any>(() => api.portfolio(), []);
  const [sector, setSector] = useState("");
  const [sort, setSort] = useState<Sort>("signals");
  const [edit, setEdit] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const items = useMemo(() => {
    let xs = (data?.items || []) as any[];
    if (sector) xs = xs.filter((x) => x.sector === sector);
    const by: Record<Sort, (a: any, b: any) => number> = {
      signals: (a, b) => (b.top_score_7d || 0) - (a.top_score_7d || 0) || a.ticker.localeCompare(b.ticker),
      move: (a, b) => Math.abs(b.price?.return_pct || 0) - Math.abs(a.price?.return_pct || 0),
      volume: (a, b) => (b.price?.volume_ratio || 0) - (a.price?.volume_ratio || 0),
      az: (a, b) => a.ticker.localeCompare(b.ticker),
    };
    return [...xs].sort(by[sort]);
  }, [data, sector, sort]);

  const add = async (t: string) => {
    setMsg(null);
    try { await api.addHolding(t); setMsg(`${t} added.`); reload(); }
    catch (e: any) { setMsg(`Could not add ${t}: ${e.message}`); }
  };
  const remove = async (t: string) => {
    if (!window.confirm(`Remove ${t} from your portfolio?`)) return;
    try { await api.removeHolding(t); reload(); } catch (e: any) { setMsg(`Could not remove ${t}: ${e.message}`); }
  };

  const s = data?.summary;
  return (
    <div>
      <h1 className="w-semi text-[24px] font-bold">Portfolio</h1>
      {s && (
        <p className="mt-1 text-[14px] text-dim">
          <span className="w-cond text-fg">{data.count}</span> holdings, equal-weight day move{" "}
          <span className={`w-cond font-semibold ${tone(s.equal_weight_move)}`}>{pct(s.equal_weight_move, true, 2)}</span>,{" "}
          <span className="w-cond">{s.up}</span> up and <span className="w-cond">{s.down}</span> down on {s.date ? shortDate(s.date) : "the last session"} (EOD)
        </p>
      )}
      <div className="mt-4"><TickerSearch onPick={add} /></div>
      {msg && <p className="mt-2 text-[13px] text-dim" role="status">{msg}</p>}

      <div className="no-scrollbar mt-4 flex gap-1.5 overflow-x-auto">
        <Chip active={!sector} onClick={() => setSector("")}>All</Chip>
        {(data?.sectors || []).map((x: string) => <Chip key={x} active={sector === x} onClick={() => setSector(x)}>{x}</Chip>)}
      </div>
      <div className="mt-3 flex items-center gap-2 text-[13px]">
        <label className="flex items-center gap-1.5 text-dim">Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} className="rounded border border-line bg-surface px-2 py-1 text-fg">
            <option value="signals">Signals</option><option value="move">Move</option><option value="volume">Volume</option><option value="az">A–Z</option>
          </select></label>
        <Button small className="ml-auto" onClick={() => setEdit(!edit)}>{edit ? "Done" : "Edit"}</Button>
      </div>

      {error && <div className="mt-4"><ErrorBox what="the portfolio" error={error} retry={reload} /></div>}
      {loading && !data && <div className="mt-4"><LoadingRows n={6} /></div>}
      {data && items.length === 0 && <div className="mt-4"><Empty title="No holdings yet">Search above to add NSE companies.</Empty></div>}
      <ul className="hairline mt-3 border-y border-line">
        {items.map((x) => {
          const p = x.price;
          return (
            <li key={x.ticker} className="flex items-center gap-3 py-2.5">
              {edit && (
                <button onClick={() => remove(x.ticker)} aria-label={`Remove ${x.ticker}`} className="rounded p-1 text-down hover:bg-down/10"><X size={16} /></button>
              )}
              <a href={href(`research/${x.ticker}`)} onClick={(e) => { if (edit) e.preventDefault(); }} className="flex min-w-0 flex-1 items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="w-cond text-[15px] font-bold">{x.ticker}</span>
                    {x.top_priority_7d && ["critical", "high"].includes(x.top_priority_7d) && <PriorityDot p={x.top_priority_7d} size={7} />}
                    {x.signals_7d > 0 && <span className="text-[11px] text-dim">{x.signals_7d} signal{x.signals_7d > 1 ? "s" : ""}</span>}
                  </div>
                  <div className="truncate text-[12px] text-dim">{x.name}</div>
                </div>
                <Spark data={x.spark} width={64} height={24} />
                <div className="w-[86px] shrink-0 text-right">
                  <div className="w-cond text-[14px]">{p ? price(p.close) : "N/A"}</div>
                  <div className={`w-cond text-[13px] font-semibold ${tone(p?.return_pct)}`}>{pct(p?.return_pct, true, 2)}</div>
                </div>
                <div className={`w-cond hidden w-12 shrink-0 text-right text-[13px] sm:block ${p?.volume_ratio >= 2 ? "font-semibold text-warn" : "text-dim"}`}>
                  {p?.volume_ratio ? `${p.volume_ratio.toFixed(1)}×` : ""}
                </div>
              </a>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-[12px] text-faint">End-of-day prices. Volume is today against the 20-session average; amber at 2× or more. Not real-time.</p>
      {edit && <p className="mt-1 text-[12px] text-faint">Removing a holding stops its filings appearing in the brief.</p>}
      <div className="mt-6"><Button small onClick={() => go("research")}><Plus size={14} /> Research a company outside the portfolio</Button></div>
    </div>
  );
}
