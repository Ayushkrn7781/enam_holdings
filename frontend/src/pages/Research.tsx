import { ArrowDownRight, ArrowRight, ArrowUpRight, Download, FileText, Minus, Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Citation, Rich, useAsk } from "../components/Ask";
import { Empty, ErrorState, H2, ListSkeleton, Sparkline, SourceBadge, StatusPill } from "../components/ui";
import { del, fileUrl, post, useApi } from "../lib/api";
import { cr, crShort, pct, rupee, times, tone } from "../lib/format";
import { go } from "../lib/router";
import { TickerSearch } from "./Portfolio";
import { ResultsCard } from "./SignalDetail";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "guidance", label: "Promise vs delivered" },
  { key: "health", label: "Health" },
  { key: "case", label: "Bull vs bear" },
  { key: "documents", label: "Documents" },
];

export default function Research({ ticker, tab }: { ticker?: string; tab?: string }) {
  if (!ticker) return <ResearchHome />;
  return <Company ticker={ticker.toUpperCase()} tab={tab ?? "overview"} />;
}

function ResearchHome() {
  const pf = useApi("/api/portfolio");
  const withDocs = (pf.data?.items ?? []).filter((i: any) => i.has_documents);
  return (
    <div>
      <h1 className="w-semi text-[24px] font-semibold">Research</h1>
      <p className="mt-1 max-w-prose text-[14px] text-dim">Any NSE company, analysed only from its own annual reports, concall transcripts and reported financials. No news, no broker notes.</p>
      <div className="mt-4"><TickerSearch placeholder="Search any NSE ticker or company" cta="Open" onPick={(t) => go("research", t)} /></div>
      <H2>Primary documents indexed</H2>
      <div className="flex flex-wrap gap-2">
        {["TRENT", ...withDocs.map((i: any) => i.ticker)].filter((v, i, a) => a.indexOf(v) === i).map((t) => (
          <button key={t} onClick={() => go("research", t, "guidance")} className="rounded border border-line px-3 py-2 text-left hover:border-info">
            <div className="text-[14px] font-bold">{t}</div><div className="text-[12px] text-dim">Promise vs delivered</div>
          </button>
        ))}
      </div>
      <H2>Your holdings</H2>
      <div className="flex flex-wrap gap-1.5">
        {(pf.data?.items ?? []).map((i: any) => <button key={i.ticker} onClick={() => go("research", i.ticker)} className="rounded-full border border-line px-2.5 py-1 text-[12.5px] text-dim hover:text-fg">{i.ticker}</button>)}
      </div>
    </div>
  );
}

function Company({ ticker, tab }: { ticker: string; tab: string }) {
  const { setTicker } = useAsk();
  useEffect(() => setTicker(ticker), [ticker]);
  const co = useApi(`/api/companies/${encodeURIComponent(ticker)}`);
  const [adding, setAdding] = useState(false);

  if (co.error) {
    return (
      <div>
        <h1 className="text-[22px] font-bold">{ticker}</h1>
        <IngestPrompt ticker={ticker} unknown onDone={co.reload} />
      </div>
    );
  }
  const c = co.data;
  const toggle = () => {
    setAdding(true);
    (c.in_portfolio ? del(`/api/portfolio/${encodeURIComponent(ticker)}`) : post("/api/portfolio", { ticker })).finally(() => { setAdding(false); co.reload(); });
  };
  return (
    <div>
      {!c ? <div className="skeleton h-14 w-2/3" /> : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-baseline gap-2"><h1 className="w-wide text-[24px] font-bold leading-none">{ticker}</h1><SourceBadge source={c.price?.source} /></div>
            <div className="mt-1 truncate text-[13.5px] text-dim">{c.name}, {c.sector}</div>
          </div>
          <div className="num shrink-0 text-right">
            <div className="text-[16px] font-semibold">{rupee(c.price?.close)}</div>
            <div className={`text-[13px] ${tone(c.price?.return_pct)}`}>{pct(c.price?.return_pct, true, 2)} <span className="text-dim">1y {pct(c.price?.return_1y_pct, true, 0)}</span></div>
          </div>
        </div>
      )}
      {c && (
        <div className="mt-3 flex items-center gap-3">
          <Sparkline data={c.spark} w={140} h={30} />
          <button onClick={toggle} disabled={adding} className="ml-auto inline-flex items-center gap-1 rounded border border-line px-2.5 py-1 text-[12.5px] text-dim hover:text-fg">
            {c.in_portfolio ? <><Minus className="h-3.5 w-3.5" />Remove from portfolio</> : <><Plus className="h-3.5 w-3.5" />Add to portfolio</>}
          </button>
        </div>
      )}
      <nav className="no-scrollbar -mx-4 mt-4 flex gap-1 overflow-x-auto border-b border-line px-4" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => go("research", ticker, t.key)}
            className={`-mb-px shrink-0 border-b-2 px-2.5 pb-2 pt-1 text-[13.5px] ${tab === t.key ? "border-up text-fg" : "border-transparent text-dim hover:text-fg"}`}>{t.label}</button>
        ))}
      </nav>
      <div className="mt-5">
        {tab === "overview" && <Overview ticker={ticker} />}
        {tab === "guidance" && <Guidance ticker={ticker} />}
        {tab === "health" && <Health ticker={ticker} />}
        {tab === "case" && <BullBear ticker={ticker} />}
        {tab === "documents" && <Documents ticker={ticker} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ overview */

function Overview({ ticker }: { ticker: string }) {
  const { data, error, loading, reload } = useApi(`/api/research/${encodeURIComponent(ticker)}`);
  const [cite, setCite] = useState<number | null>(null);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <ListSkeleton rows={4} />;
  const f = data.financial_snapshot;
  const t = data.trajectory;
  return (
    <div>
      <H2>What the business does</H2>
      <div className="prose-finn max-w-prose text-[14.5px] leading-relaxed"><Rich text={data.business.text} onCite={setCite} /></div>
      {data.business.citations?.length > 0 && (
        <ol className="mt-1 space-y-1">{data.business.citations.map((c: any, i: number) => <Citation key={i} n={i + 1} c={c} open={cite === i + 1} onToggle={() => setCite(cite === i + 1 ? null : i + 1)} />)}</ol>
      )}
      {data.documents.length === 0 && <IngestPrompt ticker={ticker} onDone={reload} mode={data.data_mode} status={data.ingestion} />}

      {f && (
        <>
          <H2 right={<span className="text-[12px] text-dim">FY ending {f.period}</span>}>Financial snapshot</H2>
          <dl className="num grid grid-cols-3 gap-x-4 gap-y-3 border-y border-line py-3 sm:grid-cols-6">
            <Stat k="Revenue" v={crShort(f.revenue)} sub="₹ Cr" />
            <Stat k="EBITDA margin" v={data.company.is_financial ? "N/A" : pct(f.ebitda_margin, false)} sub={data.company.is_financial ? "lender" : ""} />
            <Stat k="PAT" v={crShort(f.pat)} sub={`${pct(f.pat_margin, false)} margin`} />
            <Stat k="ROE" v={pct(f.roe, false)} />
            <Stat k="ROCE" v={data.company.is_financial ? "N/A" : pct(f.roce, false)} />
            <Stat k="Debt / equity" v={data.company.is_financial ? "N/A" : times(f.debt_to_equity)} />
          </dl>
          {f.ttm && <div className="num mt-1.5 text-[12.5px] text-dim">{f.ttm.label}: revenue {cr(f.ttm.revenue)}, PAT {cr(f.ttm.pat)}{f.ttm.ebitda_margin != null ? `, EBITDA margin ${f.ttm.ebitda_margin}%` : ""}</div>}
        </>
      )}

      {t && (
        <>
          <H2>Trajectory</H2>
          <p className="max-w-prose text-[14px]">{t.takeaway}</p>
          <div className="mt-2 h-52">
            <ResponsiveContainer>
              <ComposedChart data={t.series} margin={{ top: 6, right: 4, left: -14, bottom: 0 }}>
                <CartesianGrid stroke="#26354F" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "#8A9BB5", fontSize: 11 }} tickFormatter={(v) => "FY" + v.slice(-2)} axisLine={false} tickLine={false} />
                <YAxis yAxisId="l" tick={{ fill: "#8A9BB5", fontSize: 10.5 }} axisLine={false} tickLine={false} tickFormatter={(v) => crShort(v)} width={58} />
                <YAxis yAxisId="r" orientation="right" hide domain={[0, "auto"]} />
                <Tooltip contentStyle={{ background: "#1B2940", border: "1px solid #26354F", borderRadius: 6, fontSize: 12 }} formatter={(v: any, n: any) => [String(n).includes("margin") ? `${v}%` : cr(v), n]} />
                <Bar yAxisId="l" dataKey="revenue" name="Revenue" fill="#5B9BF0" radius={[2, 2, 0, 0]} maxBarSize={34} />
                <Bar yAxisId="l" dataKey="pat" name="PAT" fill="#3FB98A" radius={[2, 2, 0, 0]} maxBarSize={34} />
                {!data.company.is_financial && <Line yAxisId="r" dataKey="ebitda_margin" name="EBITDA margin" stroke="#E0A84B" strokeWidth={1.6} dot={{ r: 2.5 }} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-3 text-[11px] text-dim"><K c="#5B9BF0" l="Revenue" /><K c="#3FB98A" l="PAT" />{!data.company.is_financial && <K c="#E0A84B" l="EBITDA margin (right scale)" />}</div>
        </>
      )}
      {data.latest_quarter && <ResultsCard card={data.latest_quarter} />}
    </div>
  );
}

const K = ({ c, l }: { c: string; l: string }) => <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: c }} />{l}</span>;
const Stat = ({ k, v, sub }: { k: string; v: string; sub?: string }) => (
  <div><dt className="text-[11.5px] text-dim">{k}</dt><dd className="w-cond text-[19px] font-semibold leading-tight">{v}</dd>{sub && <dd className="text-[11px] text-faint">{sub}</dd>}</div>
);

function IngestPrompt({ ticker, onDone, mode, status, unknown }: { ticker: string; onDone: () => void; mode?: any; status?: any; unknown?: boolean }) {
  const [state, setState] = useState<string | null>(status?.status && status.status !== "idle" ? `${status.status}${status.detail ? `: ${status.detail}` : ""}` : null);
  const run = () => {
    setState("Queued…");
    post(`/api/research/${encodeURIComponent(ticker)}/ingest`).then(() => {
      setState("Fetching fundamentals and documents. This takes a minute.");
      setTimeout(onDone, 8000);
    }).catch((e) => setState(e.message));
  };
  return (
    <div className="mt-3 rounded border border-dashed border-line p-4 text-[13.5px]">
      <div className="font-semibold">{unknown ? `${ticker} isn't loaded yet` : `No primary documents for ${ticker} yet`}</div>
      <p className="mt-1 text-dim">
        FINN can fetch {ticker}'s reported financials, latest annual report and last four concall transcripts from screener.in, index them page by page and run the analysis. It works for any NSE ticker where the documents exist.
        {mode?.mode === "demo" && " This deployment runs on the illustrative demo dataset; fetching needs the backend to have internet access to screener.in."}
      </p>
      <button onClick={run} className="mt-3 inline-flex items-center gap-1.5 rounded bg-fg px-3 py-1.5 text-[13px] font-semibold text-ink"><Download className="h-4 w-4" />Fetch and index {ticker}</button>
      {state && <div className="mt-2 text-[12.5px] text-dim">{state}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ promise vs delivered */

function Guidance({ ticker }: { ticker: string }) {
  const { data, error, loading, reload } = useApi(`/api/research/${encodeURIComponent(ticker)}/management-guidance`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <ListSkeleton rows={5} />;
  if (data.status !== "ok") return <Empty title="Guidance can't be established">{data.message}</Empty>;
  const sm = data.summary;
  const byCall: Record<string, any[]> = {};
  for (const r of data.rows) (byCall[r.said_in] ??= []).push(r);
  const calls = Object.keys(byCall).sort((a, b) => order(b) - order(a));
  const graded = data.chart.filter((c: any) => c.actual != null);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
        <div>
          <div className="num w-wide text-[44px] font-bold leading-none">{sm.hit_rate_pct == null ? "N/A" : `${sm.hit_rate_pct}%`}</div>
          <div className="mt-1 text-[12.5px] text-dim">of {sm.graded} gradeable promises met or beaten, across {sm.calls_covered.length} calls</div>
        </div>
        <div className="num flex gap-5 text-[13px]">
          {[["exceeded", "Beaten"], ["achieved", "Met"], ["missed", "Missed"], ["pending", "Pending"]].map(([k, l]) => (
            <div key={k}><div className={`text-[20px] font-semibold ${k === "missed" ? "text-down" : k === "pending" ? "text-dim" : "text-up"}`}>{sm.counts[k] ?? 0}</div><div className="text-[11.5px] text-dim">{l}</div></div>
          ))}
        </div>
      </div>
      <p className="mt-4 max-w-prose text-[14.5px] leading-relaxed">{data.interpretation.text}</p>
      <div className="text-[11.5px] text-faint">{data.interpretation.method === "deterministic" ? "Summary assembled from the graded table." : data.interpretation.method}</div>

      {sm.revisions.length > 0 && (
        <>
          <H2>Revisions</H2>
          <ul className="space-y-1.5">
            {sm.revisions.map((r: any, i: number) => (
              <li key={i} className="flex items-center gap-2 text-[14px]">
                {r.direction === "up" ? <ArrowUpRight className="h-4 w-4 text-up" /> : <ArrowDownRight className="h-4 w-4 text-down" />}
                <span><span className="font-semibold">{r.metric} {r.horizon}</span>: <span className="num">{band(r.from)}</span> <ArrowRight className="inline h-3 w-3 text-dim" /> <span className="num">{band(r.to)}</span> <span className="text-dim">({r.from_call} to {r.to_call} call)</span></span>
              </li>
            ))}
          </ul>
        </>
      )}

      {graded.length > 0 && (
        <>
          <H2>Promised range vs reported</H2>
          <Dumbbells items={graded} />
        </>
      )}

      <H2>Every statement, by call</H2>
      <div className="space-y-5">
        {calls.map((call) => (
          <div key={call}>
            <div className="mb-1 text-[13px] font-semibold text-dim">{call} earnings call</div>
            <ul className="divide-y divide-line border-y border-line">
              {byCall[call].map((r: any) => <Statement key={r.id} r={r} />)}
            </ul>
          </div>
        ))}
      </div>
      <H2>Caveats</H2>
      <ul className="list-disc space-y-1 pl-5 text-[13px] text-dim">{data.uncertainties.map((u: string) => <li key={u}>{u}</li>)}</ul>
    </div>
  );
}

const order = (label: string) => { const m = label.match(/Q(\d) FY(\d+)/); return m ? +m[2] * 10 + +m[1] : 0; };
const band = (b: (number | null)[]) => (b[1] == null ? `≥${b[0]}%` : b[0] === b[1] ? `${b[0]}%` : `${b[0]}–${b[1]}%`);

function Statement({ r }: { r: any }) {
  const tgt = r.target_low == null ? "No number" : r.unit === "INR cr" ? cr(r.target_low) : band([r.target_low, r.target_high]);
  const pdf = r.citation?.url?.startsWith("demo://") ? null : r.citation?.url;
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
        <span className="font-semibold">{r.metric_label}</span>
        <span className="text-dim">for {r.horizon ?? "unspecified period"}</span>
        <span className="num">{tgt}</span>
        {r.actual != null && <span className="num text-dim">reported <span className="text-fg">{r.actual.toFixed(1)}%</span></span>}
        <StatusPill status={r.status} />
        {r.revision && <span className={`text-[11.5px] ${r.revision.direction === "up" ? "text-up" : "text-down"}`}>revised {r.revision.direction}</span>}
      </div>
      <blockquote className="mt-1.5 border-l-2 border-line pl-3 text-[14px] leading-relaxed text-fg/90">“{r.statement}”</blockquote>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[11.5px] text-faint">
        <span>{r.speaker ?? "Management"}, p.{r.citation?.page}</span>
        <span>{r.commitment.replace("_", " ")}</span>
        {r.actual_method && r.status !== "qualitative" && <span>{r.actual_method}</span>}
        {pdf && <a href={pdf} target="_blank" rel="noreferrer" className="text-info hover:underline">transcript</a>}
        <SourceBadge source={r.citation?.source} />
      </div>
    </li>
  );
}

/** Target band (bar) vs reported value (dot) on one shared % axis per metric family. */
function Dumbbells({ items }: { items: any[] }) {
  const groups = [["revenue_growth", "pat_growth"], ["ebitda_margin"]].map((ms) => items.filter((i) => ms.includes(i.metric))).filter((g) => g.length);
  return (
    <div className="space-y-5">
      {groups.map((g, gi) => {
        const vals = g.flatMap((i) => [i.low, i.high, i.actual]).filter((v) => v != null);
        const lo = Math.floor(Math.min(...vals) - 1), hi = Math.ceil(Math.max(...vals) + 1);
        const x = (v: number) => ((v - lo) / (hi - lo)) * 100;
        return (
          <div key={gi}>
            {g.map((i, k) => {
              const ok = i.status !== "missed";
              const high = i.high ?? hi;
              return (
                <div key={k} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] items-center gap-3 py-1.5">
                  <div className="min-w-0 text-[12.5px]"><div className="truncate">{i.label}</div><div className="text-[11px] text-faint">said {i.said_in}</div></div>
                  <div className="relative h-6">
                    <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
                    <div className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded-sm bg-info/35" style={{ left: `${x(i.low)}%`, width: `${Math.max(1.2, x(high) - x(i.low))}%` }} title={`Guided ${band([i.low, i.high])}`} />
                    <div className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink ${ok ? "bg-up" : "bg-down"}`} style={{ left: `${x(i.actual)}%` }} title={`Reported ${i.actual}%`} />
                    <div className={`num absolute -top-1.5 -translate-x-1/2 text-[10.5px] ${ok ? "text-up" : "text-down"}`} style={{ left: `${x(i.actual)}%` }}>{i.actual.toFixed(1)}</div>
                  </div>
                </div>
              );
            })}
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] gap-3"><div /><div className="num flex justify-between text-[10.5px] text-faint"><span>{lo}%</span><span>{hi}%</span></div></div>
          </div>
        );
      })}
      <div className="flex gap-4 text-[11px] text-dim"><span className="inline-flex items-center gap-1"><span className="h-2 w-4 rounded-sm bg-info/35" />Guided range</span><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-up" />Reported, met</span><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-down" />Reported, missed</span></div>
    </div>
  );
}

/* ------------------------------------------------------------------ health */

function Health({ ticker }: { ticker: string }) {
  const { data, error, loading, reload } = useApi(`/api/research/${encodeURIComponent(ticker)}/financial-health`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <ListSkeleton rows={5} />;
  if (!data.checks.length) return <Empty title="Not enough history">{data.note}</Empty>;
  const pillars: Record<string, any[]> = {};
  for (const c of data.checks) (pillars[c.pillar] ??= []).push(c);
  const col = data.overall === "elevated" ? "text-down" : data.overall === "monitor" ? "text-warn" : "text-up";
  return (
    <div>
      <div className="flex items-baseline gap-3"><span className={`w-wide text-[30px] font-bold capitalize ${col}`}>{data.overall}</span><span className="num text-[12.5px] text-dim">data completeness {Math.round(data.data_completeness * 100)}%</span></div>
      <p className="mt-1 text-[14px]">{data.overall_reason}</p>
      {data.is_financial && <p className="mt-1 text-[13px] text-dim">Lender: leverage, EBITDA and working-capital tests are switched off because they don't apply to banks.</p>}
      <p className="mt-1 text-[11.5px] text-faint">{data.disclaimer}</p>
      {Object.entries(pillars).map(([p, cs]) => (
        <div key={p}>
          <H2>{p}</H2>
          <ul className="divide-y divide-line border-y border-line">
            {cs.map((c: any) => (
              <li key={c.metric} className="py-2.5">
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1 text-[14px] font-semibold">{c.metric}</div>
                  {c.history?.length > 1 && <Sparkline data={c.history.map((h: any) => h[1]).filter((v: any) => v != null)} w={56} h={20} positive={c.label === "stable"} />}
                  <div className="num shrink-0 text-right text-[14px]">{c.current == null ? "" : `${c.current.toLocaleString("en-IN", { maximumFractionDigits: 1 })}${["%", "×"].includes(c.unit) ? c.unit : ` ${c.unit}`}`}</div>
                  <StatusPill status={c.label} />
                </div>
                <div className="mt-0.5 text-[12.5px] text-dim">{c.interpretation}{c.direction !== "n/a" && <span className="text-faint"> Trend {c.direction}.</span>}</div>
                {c.evidence && <div className="mt-1.5 border-l-2 border-line pl-2 text-[12.5px] text-dim">“{c.evidence.excerpt}” <span className="text-faint">({c.evidence.document}, p.{c.evidence.page})</span></div>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <div className="mt-2 text-[11.5px] text-faint">Years: {data.periods.join(", ")}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ bull / bear, documents */

function BullBear({ ticker }: { ticker: string }) {
  const { data, error, loading, reload } = useApi(`/api/research/${encodeURIComponent(ticker)}/bull-bear`);
  const [cite, setCite] = useState<number | null>(null);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <ListSkeleton rows={4} />;
  return (
    <div>
      <div className="grid gap-6 sm:grid-cols-2">
        {[["Bull case", data.bull, "border-up"], ["Bear case", data.bear, "border-down"]].map(([t, xs, b]: any) => (
          <div key={t} className={`border-l-2 ${b} pl-3`}>
            <h3 className="w-wide text-[16px] font-bold">{t}</h3>
            <ul className="mt-2 space-y-2 text-[14px] leading-relaxed">{xs.map((x: string, i: number) => <li key={i} className="prose-finn"><Rich text={x} onCite={setCite} /></li>)}</ul>
          </div>
        ))}
      </div>
      {data.citations?.length > 0 && <ol className="mt-4 space-y-1">{data.citations.map((c: any, i: number) => <Citation key={i} n={i + 1} c={c} open={cite === i + 1} onToggle={() => setCite(cite === i + 1 ? null : i + 1)} />)}</ol>}
      <div className="mt-3 text-[11.5px] text-faint">{data.method}. Built from computed health metrics{data.citations?.length ? " and cited primary-document excerpts" : ""}; no outside views.</div>
    </div>
  );
}

function Documents({ ticker }: { ticker: string }) {
  const { data, error, loading, reload } = useApi(`/api/research/${encodeURIComponent(ticker)}/documents`);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <ListSkeleton rows={3} />;
  return (
    <div>
      {data.length === 0 ? <IngestPrompt ticker={ticker} onDone={reload} /> : (
        <ul className="divide-y divide-line border-y border-line">
          {data.map((d: any) => (
            <li key={d.id} className="flex items-center gap-3 py-2.5">
              <FileText className="h-4 w-4 shrink-0 text-dim" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px]">{d.title}</div>
                <div className="num text-[12px] text-dim">{d.doc_type.replace("_", " ")}, {d.period ?? "period n/a"}, {d.pages ?? "?"} pages, {d.chunks} passages indexed{d.error ? `, ${d.error}` : ""}</div>
              </div>
              <StatusPill status={d.status === "indexed" ? "verified" : d.status === "failed" ? "mismatch" : "pending"} />
              {d.file && <a href={fileUrl(d.file)} target="_blank" rel="noreferrer" className="text-[12.5px] text-info hover:underline">PDF</a>}
            </li>
          ))}
        </ul>
      )}
      <button onClick={() => post(`/api/research/${encodeURIComponent(ticker)}/ingest`).then(() => setTimeout(reload, 6000)).catch(() => {})} className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-info hover:underline"><RefreshCw className="h-3.5 w-3.5" />Re-fetch from screener.in</button>
    </div>
  );
}
