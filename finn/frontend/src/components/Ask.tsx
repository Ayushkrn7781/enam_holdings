import { ArrowUp, ChevronDown, FileText, Loader2, ShieldCheck, Sparkles } from "lucide-react";
import { createContext, Fragment, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { fileUrl, post } from "../lib/api";
import { Sheet, SourceBadge } from "./ui";

type Turn = { q: string; ticker: string; res?: any; error?: string };
type Ctx = { ticker: string | null; setTicker: (t: string | null) => void; ask: (q: string, ticker?: string) => void };
const AskCtx = createContext<Ctx>({ ticker: null, setTicker: () => {}, ask: () => {} });
export const useAsk = () => useContext(AskCtx);

const SUGGESTED = [
  "What does this company do?",
  "Has management delivered on its guidance?",
  "Compare the last four quarters",
  "How much debt does it carry?",
  "Is cash flow consistent with reported profits?",
  "What risks does management disclose?",
];

export function AskProvider({ children }: { children: ReactNode }) {
  const [ticker, setTicker] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const ask = (q: string, t?: string) => {
    const tk = (t ?? ticker ?? "").toUpperCase();
    setOpen(true);
    if (!tk) { setTurns((x) => [...x, { q, ticker: "", error: "Pick a company first — open one from Portfolio or Research, or type its ticker." }]); return; }
    const idx = turns.length;
    setTurns((x) => [...x, { q, ticker: tk }]);
    post("/api/research/query", { ticker: tk, question: q })
      .then((res) => setTurns((x) => x.map((tt, i) => (i === idx ? { ...tt, res } : tt))))
      .catch((e) => setTurns((x) => x.map((tt, i) => (i === idx ? { ...tt, error: e.message } : tt))));
  };
  return (
    <AskCtx.Provider value={{ ticker, setTicker, ask }}>
      {children}
      <AskSheet open={open} onClose={() => setOpen(false)} turns={turns} ticker={ticker} ask={ask} />
    </AskCtx.Provider>
  );
}

export function AskBar() {
  const { ticker, ask } = useAsk();
  const [q, setQ] = useState("");
  const submit = (e: React.FormEvent) => { e.preventDefault(); if (q.trim().length > 2) { ask(q.trim()); setQ(""); } };
  return (
    <form onSubmit={submit} className="flex items-center gap-2 rounded-full border border-line bg-raised py-1 pl-3 pr-1 shadow-[0_8px_30px_rgba(0,0,0,.35)]">
      <Sparkles className="h-4 w-4 shrink-0 text-up" aria-hidden />
      <span className="shrink-0 rounded-sm bg-ink px-1.5 py-px text-[11.5px] font-semibold text-dim">{ticker ?? "No company"}</span>
      <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Ask FINN"
        placeholder={ticker ? `Ask about ${ticker}…` : "Open a company, then ask…"}
        className="min-w-0 flex-1 bg-transparent py-1.5 text-[14px] placeholder:text-faint focus:outline-none" />
      <button type="submit" aria-label="Send" disabled={q.trim().length < 3}
        className="grid h-8 w-8 place-items-center rounded-full bg-up text-ink disabled:bg-line disabled:text-faint"><ArrowUp className="h-4 w-4" /></button>
    </form>
  );
}

function AskSheet({ open, onClose, turns, ticker, ask }: { open: boolean; onClose: () => void; turns: Turn[]; ticker: string | null; ask: Ctx["ask"] }) {
  const [q, setQ] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns, open]);
  return (
    <Sheet open={open} onClose={onClose} title={<div className="flex items-center gap-2"><Sparkles className="h-4 w-4 shrink-0 text-up" /><span className="whitespace-nowrap font-semibold">Ask FINN</span><span className="hidden truncate text-[12px] text-dim sm:inline">Answers come only from the company's own filings</span></div>}>
      <div className="space-y-6">
        {turns.length === 0 && <div className="text-sm text-dim">Ask anything about {ticker ?? "a company"}. Numbers are computed from reported financials; narrative answers cite the annual report or concall page they came from.</div>}
        {turns.map((t, i) => <TurnView key={i} t={t} />)}
        <div ref={end} />
      </div>
      <div className="sticky bottom-0 -mx-4 mt-4 border-t border-line bg-surface px-4 pb-1 pt-3">
        <div className="no-scrollbar -mx-1 mb-2 flex gap-2 overflow-x-auto px-1">
          {SUGGESTED.map((s) => (
            <button key={s} onClick={() => ask(s)} className="shrink-0 rounded-full border border-line px-3 py-1 text-[12.5px] text-dim hover:border-info hover:text-fg">{s}</button>
          ))}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); if (q.trim().length > 2) { ask(q.trim()); setQ(""); } }} className="flex gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Follow up on ${ticker ?? "…"}`} aria-label="Follow-up question"
            className="min-w-0 flex-1 rounded border border-line bg-ink px-3 py-2 text-[14px] placeholder:text-faint focus:border-info focus:outline-none" />
          <button className="rounded bg-up px-3 text-[13px] font-semibold text-ink">Ask</button>
        </form>
      </div>
    </Sheet>
  );
}

function TurnView({ t }: { t: Turn }) {
  const [openCite, setOpenCite] = useState<number | null>(null);
  const r = t.res;
  return (
    <div>
      <div className="mb-2 flex items-baseline gap-2"><span className="text-[12px] font-semibold text-dim">{t.ticker}</span><span className="font-semibold">{t.q}</span></div>
      {t.error && <div className="text-sm text-down">{t.error}</div>}
      {!r && !t.error && <div className="flex items-center gap-2 text-sm text-dim"><Loader2 className="h-4 w-4 animate-spin" />Routing your question…</div>}
      {r && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11.5px]">
            <span className="rounded-sm bg-info/15 px-1.5 py-px font-semibold text-info">{r.route_label}</span>
            <span className="text-dim">{r.engine}</span>
            <span className="text-faint">{r.latency_ms} ms</span>
          </div>
          <div className="prose-finn text-[14.5px] leading-relaxed text-fg/90"><Rich text={r.answer} onCite={(n) => setOpenCite(openCite === n ? null : n)} /></div>
          <Confidence c={r.confidence} />
          {r.citations?.length > 0 && (
            <div className="mt-3 border-t border-line pt-2">
              <div className="mb-1 text-[12px] text-dim">Sources ({r.citations.length})</div>
              <ol className="space-y-1">
                {r.citations.map((c: any, i: number) => <Citation key={i} n={i + 1} c={c} open={openCite === i + 1} onToggle={() => setOpenCite(openCite === i + 1 ? null : i + 1)} />)}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Confidence({ c }: { c: any }) {
  if (!c) return null;
  const col = c.label === "high" ? "text-up" : c.label === "medium" ? "text-warn" : "text-down";
  return (
    <details className="mt-2 text-[12px] text-dim">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5"><ShieldCheck className={`h-3.5 w-3.5 ${col}`} />Evidence strength: <span className={`font-semibold ${col}`}>{c.label}</span><ChevronDown className="h-3 w-3" /></summary>
      <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 pl-5 sm:grid-cols-4">
        {Object.entries(c.factors ?? {}).map(([k, v]) => <div key={k}><span className="text-faint">{k.replace(/_/g, " ")}</span> <span className="num text-fg">{String(v)}</span></div>)}
      </div>
      <div className="mt-1 pl-5 text-faint">{c.note}</div>
    </details>
  );
}

export function Citation({ n, c, open, onToggle }: { n: number; c: any; open: boolean; onToggle: () => void }) {
  const href = c.url?.startsWith("demo://") ? null : c.url;
  return (
    <li className="text-[12.5px]">
      <button onClick={onToggle} className="flex w-full items-start gap-2 text-left hover:text-fg">
        <span className="num mt-px shrink-0 rounded-sm bg-raised px-1 text-[11px] text-dim">{n}</span>
        <span className="min-w-0 flex-1 text-dim">
          <FileText className="mr-1 inline h-3 w-3" />{c.document}{c.period ? `, ${c.period}` : ""}{c.page ? `, p.${c.page}` : ""}{c.speaker ? ` — ${c.speaker}` : ""}
        </span>
        <SourceBadge source={c.source} />
      </button>
      {open && (
        <div className="ml-7 mt-1 border-l-2 border-info/50 pl-2 text-[12.5px] leading-relaxed text-fg/80">
          {c.excerpt ?? "Structured financial table."}
          {href && <a href={href} target="_blank" rel="noreferrer" className="ml-1 text-info hover:underline">Open original</a>}
        </div>
      )}
    </li>
  );
}

/** Minimal renderer for FINN answers: paragraphs, "- " bullets, **bold**, [n] citation markers, ⚠︎ unverified flags. */
export function Rich({ text, onCite }: { text: string; onCite?: (n: number) => void }) {
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*|\[\d+\]|⚠︎ \*unverified\*)/g).map((part, i) => {
      if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>;
      const m = part.match(/^\[(\d+)\]$/);
      if (m) return <button key={i} onClick={() => onCite?.(+m[1])} className="num mx-0.5 rounded-sm bg-raised px-1 align-[1px] text-[10.5px] text-info hover:bg-info/20">{m[1]}</button>;
      if (part.startsWith("⚠︎")) return <span key={i} className="ml-1 rounded-sm bg-warn/15 px-1 text-[11px] text-warn" title="A number in this sentence was not found in the cited excerpt">unverified</span>;
      return <Fragment key={i}>{part}</Fragment>;
    });
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) { blocks.push(<ul key={blocks.length}>{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = []; } };
  for (const line of (text ?? "").split("\n")) {
    if (/^\s*-\s+/.test(line)) list.push(line.replace(/^\s*-\s+/, ""));
    else { flush(); if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>); }
  }
  flush();
  return <>{blocks}</>;
}
