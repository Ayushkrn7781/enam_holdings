import { AlertTriangle, X } from "lucide-react";
import { ReactNode, useEffect } from "react";
import { COMPONENTS, PRIORITY } from "../lib/format";

export function PriorityTag({ p, score }: { p?: string | null; score?: number | null }) {
  const m = PRIORITY[p ?? "low"] ?? PRIORITY.low;
  return (
    <span className={`inline-flex items-center gap-1.5 text-[12px] font-semibold ${m.cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} aria-hidden />
      {m.label}
      {score != null && <span className="num font-normal text-dim">{Math.round(score)}</span>}
    </span>
  );
}

/** The signature element: the materiality score drawn as its five weighted contributions. */
export function MaterialityStrip({ breakdown, score, height = 6, showLegend = false }: { breakdown?: any; score?: number | null; height?: number; showLegend?: boolean }) {
  if (!breakdown) return <div className="rounded-full bg-line" style={{ height }} />;
  return (
    <div>
      <div className="flex w-full overflow-hidden rounded-full bg-line/60" style={{ height }} role="img"
        aria-label={`Materiality ${Math.round(score ?? 0)} of 100: ` + COMPONENTS.map((c) => `${c.label} ${breakdown[c.key]?.contribution ?? 0}`).join(", ")}>
        {COMPONENTS.map((c) => (
          <div key={c.key} style={{ width: `${breakdown[c.key]?.contribution ?? 0}%`, background: c.color }} className="h-full border-r border-ink/70 last:border-0" />
        ))}
      </div>
      {showLegend && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-dim">
          {COMPONENTS.map((c) => (
            <span key={c.key} className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: c.color }} />{c.label}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export function Sparkline({ data, w = 84, h = 26, positive }: { data: number[]; w?: number; h?: number; positive?: boolean }) {
  if (!data || data.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...data), max = Math.max(...data);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - 2 - ((v - min) / (max - min || 1)) * (h - 4)}`).join(" ");
  const up = positive ?? data[data.length - 1] >= data[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <polyline points={pts} fill="none" stroke={up ? "#3FB98A" : "#E5675F"} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export const Skeleton = ({ className = "" }: { className?: string }) => <div className={`skeleton ${className}`} />;

export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-4 py-2" aria-busy>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="space-y-2"><Skeleton className="h-3 w-1/3" /><Skeleton className="h-4 w-5/6" /><Skeleton className="h-1.5 w-full" /></div>
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded border border-down/40 bg-down/10 p-3 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-down" />
      <div className="flex-1">
        <div className="text-fg">Couldn't load this.</div>
        <div className="text-dim">{message}</div>
      </div>
      {onRetry && <button onClick={onRetry} className="text-info hover:underline">Try again</button>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-line px-4 py-8 text-center">
      <div className="font-semibold">{title}</div>
      {children && <div className="mt-1 text-sm text-dim">{children}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, size = "md" }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; size?: "sm" | "md" }) {
  return (
    <div className="inline-flex rounded border border-line bg-surface p-0.5" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
          className={`rounded-sm ${size === "sm" ? "px-2 py-0.5 text-[12px]" : "px-3 py-1 text-[13px]"} transition-colors ${value === o.value ? "bg-raised text-fg" : "text-dim hover:text-fg"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Sheet({ open, onClose, children, title }: { open: boolean; onClose: () => void; children: ReactNode; title?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", k); document.body.style.overflow = ""; };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/55 md:items-center" onClick={onClose}>
      <div role="dialog" aria-modal className="sheet-in flex max-h-[88vh] w-full flex-col rounded-t-deck border border-line bg-surface md:max-w-2xl md:rounded-deck" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0 flex-1">{title}</div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-dim hover:bg-raised hover:text-fg"><X className="h-5 w-5" /></button>
        </div>
        <div className="scroll-thin overflow-y-auto px-4 py-4">{children}</div>
      </div>
    </div>
  );
}

export function SourceBadge({ source }: { source?: string | null }) {
  if (!source) return null;
  const demo = source === "demo";
  return (
    <span className={`rounded-sm px-1.5 py-px text-[10.5px] font-semibold ${demo ? "bg-warn/15 text-warn" : "bg-up/15 text-up"}`}
      title={demo ? "Illustrative demo data — not a real filing or real figures" : `Source: ${source}`}>
      {demo ? "Demo data" : source}
    </span>
  );
}

export function H2({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 mt-6 flex items-baseline justify-between gap-3 first:mt-0">
      <h2 className="text-[15px] font-semibold">{children}</h2>
      {right}
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const m: Record<string, string> = {
    exceeded: "bg-up/15 text-up", achieved: "bg-up/10 text-up", missed: "bg-down/15 text-down", pending: "bg-raised text-dim",
    long_dated: "bg-raised text-faint", qualitative: "bg-raised text-faint", not_comparable: "bg-raised text-faint",
    stable: "bg-up/10 text-up", monitor: "bg-warn/15 text-warn", elevated: "bg-down/15 text-down", insufficient: "bg-raised text-faint",
    verified: "bg-up/10 text-up", mismatch: "bg-down/15 text-down", single_source: "bg-raised text-dim",
  };
  const label: Record<string, string> = { long_dated: "Long-dated", not_comparable: "Not comparable", single_source: "Single source", insufficient: "Insufficient data" };
  return <span className={`whitespace-nowrap rounded-sm px-1.5 py-px text-[11.5px] font-semibold ${m[status] ?? "bg-raised text-dim"}`}>{label[status] ?? status[0].toUpperCase() + status.slice(1)}</span>;
}
