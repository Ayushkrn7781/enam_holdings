// Hand-built primitives. Hairline rows over cards; 6px radius; no eyebrow labels.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import type { Breakdown } from "../lib/api";
import { COMPONENT_COLOR, PRIORITY_COLOR, STATUS_STYLE, cr, pct, tone } from "../lib/format";

// ---------------------------------------------------------------- async data
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const run = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    fn().then(
      (d) => { if (id === seq.current) { setData(d); setLoading(false); } },
      (e) => { if (id === seq.current) { setError(e?.message || "Something failed"); setLoading(false); } },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { run(); }, [run]);
  return { data, error, loading, reload: run, setData };
}

// ---------------------------------------------------------------- Ask FINN context
interface AskCtx { ticker: string | null; setTicker: (t: string | null) => void; open: (q?: string, t?: string) => void }
export const AskContext = createContext<AskCtx>({ ticker: null, setTicker: () => {}, open: () => {} });
export const useAsk = () => useContext(AskContext);

// ---------------------------------------------------------------- the signature element
export function Strip({ breakdown, height = 6, legend = false }: { breakdown: Breakdown[]; height?: number; legend?: boolean }) {
  const total = breakdown.reduce((a, b) => a + (b.contribution || 0), 0) || 1;
  return (
    <div>
      <div className="flex w-full overflow-hidden rounded-[3px] bg-raised" style={{ height }}
        role="img" aria-label={"Materiality: " + breakdown.map((b) => `${b.label} ${b.contribution.toFixed(1)}`).join(", ")}>
        {breakdown.map((b) => (
          <div key={b.key} style={{ width: `${(b.contribution / 100) * 100}%`, background: COMPONENT_COLOR[b.key] }}
            className="h-full border-r border-ink/60 last:border-r-0" title={`${b.label}: ${b.contribution.toFixed(1)} of ${total.toFixed(0)}`} />
        ))}
      </div>
      {legend && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-dim">
          {breakdown.map((b) => (
            <span key={b.key} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: COMPONENT_COLOR[b.key] }} />
              {b.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function PriorityDot({ p, size = 8 }: { p: string; size?: number }) {
  return <span className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: PRIORITY_COLOR[p] }} />;
}

export function PriorityLabel({ p, score }: { p: string; score?: number | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px]">
      <PriorityDot p={p} />
      <span className="capitalize" style={{ color: PRIORITY_COLOR[p] }}>{p}</span>
      {score !== undefined && score !== null && <span className="w-cond text-dim">{score.toFixed(0)}</span>}
    </span>
  );
}

export function Pill({ status, label }: { status: string; label?: string }) {
  const s = STATUS_STYLE[status] || { label: status, cls: "text-dim border-line bg-raised" };
  return (
    <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded border px-1.5 py-[1px] text-[12px] ${s.cls}`}>
      {label || s.label}
    </span>
  );
}

export function DemoBadge({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return (
    <span className="inline-flex shrink-0 items-center rounded border border-warn/40 px-1.5 py-[1px] text-[11px] text-warn"
      title="Illustrative demo data: synthetic figures, fictional people">Demo</span>
  );
}

export function SourceBadge({ source }: { source: string }) {
  if (source === "demo") return <DemoBadge />;
  return <span className="inline-flex items-center rounded border border-line px-1.5 py-[1px] text-[11px] text-dim">{source}</span>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function LoadingRows({ n = 4 }: { n?: number }) {
  return (
    <div className="space-y-3 py-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  );
}

export function ErrorBox({ what, error, retry }: { what: string; error: string; retry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded border border-down/40 bg-down/5 p-3 text-[14px]" role="alert">
      <AlertTriangle size={18} className="mt-0.5 shrink-0 text-down" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">Could not load {what}</div>
        <div className="text-dim">{error}</div>
      </div>
      {retry && (
        <button onClick={retry} className="inline-flex shrink-0 items-center gap-1.5 rounded border border-line px-2.5 py-1.5 text-[13px] hover:bg-raised">
          <RotateCcw size={14} /> Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-line px-4 py-6 text-center">
      <div className="font-semibold">{title}</div>
      {children && <div className="mt-1 text-[14px] text-dim">{children}</div>}
    </div>
  );
}

export function Spark({ data, width = 72, height = 24, color, fluid }: { data: number[]; width?: number; height?: number; color?: string; fluid?: boolean }) {
  const v = data.filter((x) => x !== null && x !== undefined);
  if (v.length < 2) return <svg width={width} height={height} />;
  const min = Math.min(...v), max = Math.max(...v);
  const span = max - min || 1;
  const pts = v.map((y, i) => `${((i / (v.length - 1)) * width).toFixed(1)},${(height - 2 - ((y - min) / span) * (height - 4)).toFixed(1)}`);
  const c = color || (v[v.length - 1] >= v[0] ? "#3FB98A" : "#E5675F");
  return (
    <svg width={fluid ? "100%" : width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden
      preserveAspectRatio={fluid ? "none" : undefined} className={fluid ? "block" : "shrink-0"}>
      <polyline points={pts.join(" ")} fill="none" stroke={c} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"
        vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }:
  { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={`rounded-[4px] px-2.5 py-1 text-[13px] ${value === o.value ? "bg-raised text-fg" : "text-dim hover:text-fg"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className={`relative h-6 w-10 shrink-0 rounded-full transition-colors ${on ? "bg-info" : "bg-line"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-fg transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </button>
  );
}

export function Button({ children, onClick, primary, small, disabled, className = "", type = "button", title }:
  { children: ReactNode; onClick?: () => void; primary?: boolean; small?: boolean; disabled?: boolean; className?: string; type?: "button" | "submit"; title?: string }) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title}
      className={`inline-flex items-center justify-center gap-1.5 rounded font-medium disabled:opacity-50 ${small ? "px-2.5 py-1.5 text-[13px]" : "px-3.5 py-2 text-[14px]"} ${primary ? "bg-info text-ink hover:bg-info/90" : "border border-line text-fg hover:bg-raised"} ${className}`}>
      {children}
    </button>
  );
}

export function Section({ title, aside, children, className = "" }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`mt-7 ${className}`}>
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <h2 className="w-semi text-[17px] font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

// ---------------------------------------------------------------- results
export function ResultsTable({ card }: { card: any }) {
  return (
    <div>
      <table className="w-full text-[14px]">
        <thead>
          <tr className="text-left text-[12px] text-dim">
            <th className="py-1.5 font-normal">Metric</th>
            <th className="py-1.5 text-right font-normal">{card.period_label}</th>
            <th className="py-1.5 text-right font-normal">QoQ</th>
            <th className="py-1.5 text-right font-normal">YoY</th>
            <th className="hidden py-1.5 text-right font-normal sm:table-cell">{card.year_ago_label || "Year ago"}</th>
          </tr>
        </thead>
        <tbody className="hairline">
          {card.rows.map((r: any) => (
            <tr key={r.key} className="border-t border-line">
              <td className="py-2 font-medium">{r.label}</td>
              <td className="w-cond py-2 text-right">{r.current === null ? "N/A" : cr(r.current)}</td>
              <td className={`w-cond py-2 text-right font-semibold ${tone(r.qoq)}`}>{pct(r.qoq)}</td>
              <td className={`w-cond py-2 text-right font-semibold ${tone(r.yoy)}`}>{pct(r.yoy)}</td>
              <td className="w-cond hidden py-2 text-right text-dim sm:table-cell">{r.year_ago === null || r.year_ago === undefined ? "N/A" : cr(r.year_ago)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {card.margins?.ebitda_margin !== null && card.margins?.ebitda_margin !== undefined && (
        <div className="mt-2 text-[13px] text-dim">
          EBITDA margin <span className="w-cond font-semibold text-fg">{card.margins.ebitda_margin.toFixed(1)}%</span>
          {card.margins.ebitda_margin_year_ago !== null && card.margins.ebitda_margin_year_ago !== undefined && (
            <> against {card.margins.ebitda_margin_year_ago.toFixed(1)}% a year ago,{" "}
              <span className={tone(card.margins.ebitda_margin_yoy_bps)}>
                {card.margins.ebitda_margin_yoy_bps > 0 ? "+" : ""}{card.margins.ebitda_margin_yoy_bps} bps
              </span></>
          )}
        </div>
      )}
      {card.lender_note && <div className="mt-2 text-[13px] text-dim">{card.lender_note}</div>}
      {card.flags?.length > 0 && (
        <ul className="mt-2 space-y-1 text-[13px] text-warn">{card.flags.map((f: string) => <li key={f}>{f}</li>)}</ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- answer renderer
// paragraphs, "- " bullets, **bold**, [n] citation chips, "⚠︎ *unverified*" tags
function inline(text: string, onCite?: (n: number) => void, keyBase = "") {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\[\d+\]|⚠︎ \*unverified\*)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<strong key={keyBase + i++} className="font-semibold text-fg">{t.slice(2, -2)}</strong>);
    else if (t.startsWith("[")) {
      const n = Number(t.slice(1, -1));
      out.push(
        <button key={keyBase + i++} onClick={() => onCite?.(n)}
          className="mx-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-info/40 bg-info/10 px-1 align-[1px] text-[11px] text-info hover:bg-info/20"
          aria-label={`Show source ${n}`}>{n}</button>);
    } else out.push(<span key={keyBase + i++} className="ml-1 rounded border border-warn/40 px-1 text-[11px] text-warn">unverified</span>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function AnswerText({ text, onCite }: { text: string; onCite?: (n: number) => void }) {
  const blocks = text.split(/\n\s*\n/);
  return (
    <div className="space-y-2.5 text-[15px] leading-relaxed text-fg/90">
      {blocks.map((b, bi) => {
        const lines = b.split("\n").filter(Boolean);
        if (lines.length && lines.every((l) => l.startsWith("- "))) {
          return (
            <ul key={bi} className="space-y-1.5">
              {lines.map((l, li) => (
                <li key={li} className="flex gap-2"><span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-dim" />
                  <span>{inline(l.slice(2), onCite, `${bi}-${li}-`)}</span></li>
              ))}
            </ul>
          );
        }
        return <p key={bi}>{lines.map((l, li) => <span key={li}>{li > 0 && <br />}{inline(l, onCite, `${bi}-${li}-`)}</span>)}</p>;
      })}
    </div>
  );
}

export function Chip({ children, onClick, active }: { children: ReactNode; onClick?: () => void; active?: boolean }) {
  return (
    <button onClick={onClick}
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded border px-2.5 py-1 text-[13px] ${active ? "border-info/60 bg-info/10 text-fg" : "border-line text-dim hover:text-fg"}`}>
      {children}
    </button>
  );
}
