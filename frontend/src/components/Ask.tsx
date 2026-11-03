// Ask FINN: the docked question bar and the conversation sheet.
import { useEffect, useRef, useState } from "react";
import { ChevronDown, ExternalLink, Search, SendHorizontal, X } from "lucide-react";
import { api } from "../lib/api";
import { AnswerText, SourceBadge } from "./ui";

interface Turn { id: number; ticker: string | null; question: string; res?: any; error?: string; loading: boolean }

const SUGGEST = [
  "Did management deliver on its guidance?",
  "What was PAT growth YoY?",
  "Show the last four quarters",
  "Is debt rising?",
  "What are the key risks?",
  "What does the company do?",
];

export function AskBar({ ticker, onOpen }: { ticker: string | null; onOpen: () => void }) {
  return (
    <button onClick={onOpen}
      className="flex w-full items-center gap-2 rounded-full border border-line bg-surface/95 px-3 py-2.5 text-left shadow-[0_6px_24px_rgba(0,0,0,.35)] backdrop-blur hover:border-info/50"
      aria-label="Ask FINN">
      <Search size={16} className="shrink-0 text-dim" />
      {ticker && <span className="w-cond shrink-0 rounded border border-line bg-raised px-1.5 py-[1px] text-[12px] font-semibold">{ticker}</span>}
      <span className="truncate text-[14px] text-dim">{ticker ? `Ask about ${ticker}…` : "Ask FINN about any company…"}</span>
    </button>
  );
}

function Sources({ cites, openN, setOpenN }: { cites: any[]; openN: number | null; setOpenN: (n: number | null) => void }) {
  if (!cites.length) return null;
  return (
    <div className="mt-3">
      <div className="mb-1 text-[13px] text-dim">Sources</div>
      <ol className="hairline rounded border border-line">
        {cites.map((c) => {
          const open = openN === c.n;
          return (
            <li key={c.n} id={`cite-${c.n}`}>
              <button onClick={() => setOpenN(open ? null : c.n)} className="flex w-full items-start gap-2 px-2.5 py-2 text-left text-[13px] hover:bg-raised/60">
                <span className="mt-[1px] inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-info/40 text-[11px] text-info">{c.n}</span>
                <span className="min-w-0 flex-1">
                  <span className="text-fg">{c.document}</span>
                  <span className="text-dim">{c.period ? `, ${c.period}` : ""}{c.page ? `, p.${c.page}` : ""}{c.speaker ? `, ${c.speaker}` : ""}</span>
                </span>
                <SourceBadge source={c.source} />
                <ChevronDown size={14} className={`mt-0.5 shrink-0 text-dim transition-transform ${open ? "rotate-180" : ""}`} />
              </button>
              {open && (
                <div className="px-2.5 pb-2.5 pl-9 text-[13px] text-dim">
                  <blockquote className="border-l-2 border-line pl-2.5 italic text-fg/80">{c.text}</blockquote>
                  {c.document_id && <a className="mt-1.5 inline-flex items-center gap-1 text-info" href={`/api/documents/${c.document_id}/file${c.page ? `#page=${c.page}` : ""}`} target="_blank" rel="noreferrer">Open document <ExternalLink size={12} /></a>}
                  {c.url && !String(c.url).startsWith("demo://") && <a className="ml-3 mt-1.5 inline-flex items-center gap-1 text-info" href={c.url} target="_blank" rel="noreferrer">Open original <ExternalLink size={12} /></a>}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function TurnView({ t }: { t: Turn }) {
  const [openN, setOpenN] = useState<number | null>(null);
  const [why, setWhy] = useState(false);
  const cite = (n: number) => {
    setOpenN(n);
    setTimeout(() => document.getElementById(`cite-${n}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 30);
  };
  return (
    <div className="py-4">
      <div className="flex items-baseline gap-2">
        {t.ticker && <span className="w-cond rounded border border-line bg-raised px-1.5 py-[1px] text-[12px] font-semibold">{t.ticker}</span>}
        <div className="text-[15px] font-semibold">{t.question}</div>
      </div>
      {t.loading && <div className="mt-3 space-y-2"><div className="skeleton h-3 w-3/4" /><div className="skeleton h-3 w-1/2" /></div>}
      {t.error && <div className="mt-3 text-[14px] text-down">{t.error}</div>}
      {t.res && (
        <div className="mt-2.5">
          <div className="mb-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-dim">
            <span className="rounded border border-info/30 bg-info/10 px-1.5 py-[1px] text-info">{t.res.route_label}</span>
            <span>{t.res.engine}</span>
            <span className="w-cond">{t.res.latency_ms} ms</span>
          </div>
          <AnswerText text={t.res.answer} onCite={cite} />
          {t.res.citations?.length > 0 && (
            <div className="mt-3 text-[13px]">
              <button onClick={() => setWhy(!why)} className="inline-flex items-center gap-1 text-dim hover:text-fg" aria-expanded={why}>
                Evidence strength: <span className={`capitalize ${t.res.confidence.label === "high" ? "text-up" : t.res.confidence.label === "medium" ? "text-warn" : "text-down"}`}>{t.res.confidence.label}</span>
                <ChevronDown size={13} className={why ? "rotate-180" : ""} />
              </button>
              {why && (
                <div className="mt-1.5 rounded border border-line p-2.5 text-dim">
                  {Object.entries(t.res.confidence.factors).map(([k, v]) => (
                    <div key={k} className="flex justify-between"><span>{k.replace(/_/g, " ")}</span><span className="w-cond text-fg">{(v as number).toFixed(2)}</span></div>
                  ))}
                  <div className="mt-1.5 text-[12px]">Four evidence factors, not a calibrated probability.</div>
                </div>
              )}
            </div>
          )}
          <Sources cites={t.res.citations || []} openN={openN} setOpenN={setOpenN} />
        </div>
      )}
    </div>
  );
}

let turnSeq = 0;

export function AskSheet({ open, onClose, ticker, setTicker, seed }:
  { open: boolean; onClose: () => void; ticker: string | null; setTicker: (t: string | null) => void; seed: { q?: string; n: number } }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [editTicker, setEditTicker] = useState(false);
  const [tickerDraft, setTickerDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const ask = async (question: string) => {
    const qq = question.trim();
    if (qq.length < 3) return;
    const id = ++turnSeq;
    setQ("");
    if (!ticker) {
      setTurns((ts) => [...ts, { id, ticker: null, question: qq, loading: false, error: "Pick a company first: tap the ticker chip and type an NSE symbol." }]);
      return;
    }
    setTurns((ts) => [...ts, { id, ticker, question: qq, loading: true }]);
    try {
      const res = await api.ask(ticker, qq);
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, loading: false, res } : t)));
    } catch (e: any) {
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, loading: false, error: `${e.message} Try again.` } : t)));
    }
  };

  useEffect(() => { if (open && seed.q) ask(seed.q); /* eslint-disable-next-line */ }, [seed.n]);
  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 60); }, [open]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [turns]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && open) onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/55 md:items-center" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Ask FINN" onClick={(e) => e.stopPropagation()}
        className="sheet-in flex max-h-[88vh] w-full flex-col rounded-t-sheet border border-line bg-surface md:max-h-[80vh] md:max-w-[640px] md:rounded-sheet">
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <div className="w-wide text-[15px] font-extrabold">Ask FINN</div>
          <div className="min-w-0 flex-1 truncate text-[12px] text-dim">Answers from annual reports, transcripts and reported financials only</div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-dim hover:bg-raised hover:text-fg"><X size={18} /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-4">
          {turns.length === 0 && (
            <div className="py-6 text-[14px] text-dim">
              Ask about {ticker ? <span className="text-fg">{ticker}</span> : "a company"}. FINN routes each question: numbers are computed from reported financials,
              guidance is graded against actuals, and everything else is answered from cited passages. When the documents do not
              support an answer, it says so.
            </div>
          )}
          <div className="hairline">{turns.map((t) => <TurnView key={t.id} t={t} />)}</div>
          <div ref={endRef} />
        </div>
        <div className="border-t border-line px-3 pb-[max(12px,env(safe-area-inset-bottom))] pt-2.5">
          <div className="no-scrollbar mb-2 flex gap-1.5 overflow-x-auto">
            {SUGGEST.map((s) => (
              <button key={s} onClick={() => ask(s)} className="shrink-0 whitespace-nowrap rounded-full border border-line px-2.5 py-1 text-[12px] text-dim hover:text-fg">{s}</button>
            ))}
          </div>
          <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex items-center gap-2 rounded-full border border-line bg-ink px-2 py-1.5 focus-within:border-info/60">
            {editTicker ? (
              <input autoFocus value={tickerDraft} onChange={(e) => setTickerDraft(e.target.value.toUpperCase())}
                onBlur={() => { if (tickerDraft.trim()) setTicker(tickerDraft.trim()); setEditTicker(false); }}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.target as HTMLInputElement).blur(); } }}
                className="w-cond w-24 rounded bg-raised px-1.5 py-0.5 text-[12px] font-semibold outline-none" placeholder="TICKER" aria-label="Company ticker" />
            ) : (
              <button type="button" onClick={() => { setTickerDraft(ticker || ""); setEditTicker(true); }}
                className="w-cond shrink-0 rounded border border-line bg-raised px-1.5 py-0.5 text-[12px] font-semibold" aria-label="Change company">
                {ticker || "Pick company"}
              </button>
            )}
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} maxLength={500}
              placeholder={ticker ? `Ask about ${ticker}…` : "Ask a follow-up…"} aria-label="Question"
              className="min-w-0 flex-1 bg-transparent px-1 text-[15px] outline-none placeholder:text-faint" />
            <button type="submit" aria-label="Send" disabled={q.trim().length < 3}
              className="rounded-full bg-info p-1.5 text-ink disabled:opacity-40"><SendHorizontal size={16} /></button>
          </form>
        </div>
      </div>
    </div>
  );
}
