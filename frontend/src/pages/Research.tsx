import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, ChevronDown, ExternalLink, RefreshCw } from "lucide-react";
import { CartesianGrid, ComposedChart, Bar, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { cr, pct, price, tone } from "../lib/format";
import { go, href } from "../lib/router";
import { AnswerText, Button, Chip, DemoBadge, Empty, ErrorBox, LoadingRows, Pill, ResultsTable, Section, SourceBadge, Spark, useAsk, useAsync } from "../components/ui";
import { TickerSearch } from "./Portfolio";

const TABS = [
  { key: "overview", label: "Overview" }, { key: "guidance", label: "Promise vs delivered" },
  { key: "health", label: "Health" }, { key: "bullbear", label: "Bull vs bear" }, { key: "documents", label: "Documents" },
];
const tip = { contentStyle: { background: "#1B2940", border: "1px solid #26354F", borderRadius: 6, fontSize: 12 }, labelStyle: { color: "#8A9BB5" } };

function Home() {
  const pf = useAsync<any>(() => api.portfolio(), []);
  const docs = ["DIXON", "TITAN", "TRENT"];
  return (
    <div>
      <h1 className="w-semi text-[24px] font-bold">Research</h1>
      <p className="mt-1 text-[14px] text-dim">Any NSE company, answered only from its annual reports, concall transcripts and reported financials.</p>
      <div className="mt-4"><TickerSearch onPick={(t) => go(`research/${t}`)} placeholder="Search any NSE ticker or company" autoFocus /></div>
      <Section title="Documents indexed">
        <div className="flex flex-wrap gap-1.5">
          {docs.map((t) => <Chip key={t} onClick={() => go(`research/${t}/guidance`)}><span className="w-cond font-semibold text-fg">{t}</span> Promise vs delivered</Chip>)}
        </div>
      </Section>
      <Section title="Your holdings">
        <div className="flex flex-wrap gap-1.5">
          {(pf.data?.items || []).map((x: any) => <Chip key={x.ticker} onClick={() => go(`research/${x.ticker}`)}><span className="w-cond">{x.ticker}</span></Chip>)}
        </div>
      </Section>
    </div>
  );
}

function Citations({ cites }: { cites: any[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!cites?.length) return null;
  return (
    <ul className="mt-2 space-y-1 text-[13px]">
      {cites.map((c) => (
        <li key={c.n}>
          <button onClick={() => setOpen(open === c.n ? null : c.n)} className="flex items-center gap-1.5 text-dim hover:text-fg" aria-expanded={open === c.n}>
            <span className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-info/40 text-[11px] text-info">{c.n}</span>
            {c.document}{c.page ? `, p.${c.page}` : ""} <ChevronDown size={12} className={open === c.n ? "rotate-180" : ""} />
          </button>
          {open === c.n && <blockquote className="ml-6 mt-1 border-l-2 border-line pl-2.5 text-fg/80">{c.text}</blockquote>}
        </li>
      ))}
    </ul>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="py-2.5">
      <div className="text-[12px] text-dim">{label}</div>
      <div className="w-cond text-[20px] font-semibold leading-tight">{value}</div>
      {sub && <div className="text-[12px] text-faint">{sub}</div>}
    </div>
  );
}

function Overview({ d, onIngest }: { d: any; onIngest: () => void }) {
  const o = d.overview;
  const f = o.financials;
  const hasDocs = d.documents.some((x: any) => x.status === "indexed");
  return (
    <div>
      <Section title="Business">
        {o.business?.text ? <AnswerText text={o.business.text} /> : <p className="text-[14px] text-dim">No business description yet.</p>}
        <Citations cites={o.business?.citations || []} />
        {!hasDocs && (
          <div className="mt-3 rounded border border-line p-3 text-[14px]">
            <div className="text-dim">No annual report or transcripts are indexed for {d.ticker}, so narrative and guidance questions cannot be answered yet.</div>
            <Button small className="mt-2" onClick={onIngest}><RefreshCw size={14} /> Fetch and index {d.ticker}</Button>
            {d.ingestion && <div className="mt-2 text-[12px] text-dim">Last fetch: {d.ingestion.status}{d.ingestion.steps ? `. ${Object.entries(d.ingestion.steps).map(([k, v]) => `${k}: ${typeof v === "string" ? v : "ok"}`).join("; ")}` : ""}</div>}
          </div>
        )}
      </Section>
      {f && (
        <Section title={`Financial snapshot, ${f.period}`} aside={<SourceBadge source={f.source} />}>
          <div className="grid grid-cols-2 gap-x-6 border-y border-line sm:grid-cols-3">
            <Stat label="Revenue" value={cr(f.revenue)} />
            <Stat label="EBITDA margin" value={f.ebitda_margin === null ? "N/A" : `${f.ebitda_margin.toFixed(1)}%`} sub={f.is_financial ? "Not meaningful for lenders" : undefined} />
            <Stat label="PAT" value={cr(f.pat)} sub={f.pat_margin !== null ? `${f.pat_margin.toFixed(1)}% margin` : undefined} />
            <Stat label="ROE" value={f.roe === null ? "N/A" : `${f.roe.toFixed(1)}%`} />
            <Stat label="ROCE" value={f.roce === null || f.roce === undefined ? "N/A" : `${f.roce.toFixed(1)}%`} />
            <Stat label="Debt to equity" value={f.de === null || f.de === undefined ? "N/A" : `${f.de.toFixed(2)}×`} />
          </div>
          {f.ttm_label && <p className="mt-2 text-[13px] text-dim">{f.ttm_label}: revenue <span className="w-cond text-fg">{cr(f.ttm_revenue)}</span>, PAT <span className="w-cond text-fg">{cr(f.ttm_pat)}</span></p>}
        </Section>
      )}
      {o.trajectory && (
        <Section title="Trajectory">
          <p className="text-[14px]">{o.trajectory.takeaway}</p>
          <div className="mt-3 h-[200px]">
            <ResponsiveContainer>
              <ComposedChart data={o.trajectory.series} margin={{ top: 8, right: 4, left: -8, bottom: 0 }}>
                <CartesianGrid stroke="#26354F" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "#8A9BB5", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#26354F" }} />
                <YAxis yAxisId="l" tick={{ fill: "#8A9BB5", fontSize: 11 }} tickLine={false} axisLine={false} width={52} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v)} />
                <YAxis yAxisId="r" orientation="right" hide domain={["auto", "auto"]} />
                <Tooltip {...tip} formatter={(v: any, n: any) => (n === "EBITDA margin" ? `${Number(v).toFixed(1)}%` : cr(v))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar yAxisId="l" dataKey="revenue" name="Revenue" fill="#5B9BF0" radius={[2, 2, 0, 0]} />
                <Bar yAxisId="l" dataKey="pat" name="PAT" fill="#3FB98A" radius={[2, 2, 0, 0]} />
                {!d.is_financial && <Line yAxisId="r" dataKey="ebitda_margin" name="EBITDA margin" stroke="#E0A84B" strokeWidth={2} dot={{ r: 2 }} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Section>
      )}
      {o.latest_quarter && (
        <Section title={`Latest quarter, ${o.latest_quarter.period_label}`}>
          <ResultsTable card={o.latest_quarter} />
        </Section>
      )}
    </div>
  );
}

function Dumbbell({ rows }: { rows: any[] }) {
  const fams: Record<string, any[]> = {};
  rows.forEach((r) => { (fams[r.metric] = fams[r.metric] || []).push(r); });
  return (
    <div className="space-y-5">
      {Object.entries(fams).map(([m, rs]) => {
        const vals = rs.flatMap((r) => [r.low, r.high ?? r.low, r.actual]).filter((v) => v !== null && v !== undefined);
        const lo = Math.floor(Math.min(...vals) - 1), hi = Math.ceil(Math.max(...vals) + 1);
        const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
        const ticks = [lo, Math.round((lo + hi) / 2), hi];
        return (
          <div key={m}>
            <div className="mb-1.5 text-[13px] text-dim">{m === "ebitda_margin" ? "EBITDA margin, %" : m === "pat_growth" ? "PAT growth, % YoY" : "Revenue growth, % YoY"}</div>
            <div className="space-y-2.5">
              {rs.map((r, i) => {
                const hiV = r.high ?? hi;
                const met = r.status !== "missed";
                return (
                  <div key={i} className="grid grid-cols-[92px_1fr] items-center gap-2 sm:grid-cols-[150px_1fr]">
                    <div className="text-[12px] leading-tight"><span className="text-fg">{r.label.replace(/^(Revenue growth|EBITDA margin|PAT growth) /, "")}</span><span className="block text-faint">said {r.said_in}</span></div>
                    <div className="relative h-7">
                      <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
                      <div className="absolute top-1/2 h-3 -translate-y-1/2 rounded-[2px] bg-info/30 ring-1 ring-info/50"
                        style={{ left: x(r.low), width: `calc(${x(hiV)} - ${x(r.low)} + ${r.high === r.low ? "3px" : "0px"})` }}
                        title={`Guided ${r.low}${r.high === null ? "+" : r.high !== r.low ? `–${r.high}` : ""}%`} />
                      <div className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-ink"
                        style={{ left: x(r.actual), background: met ? "#3FB98A" : "#E5675F" }} />
                      <div className={`w-cond absolute -top-1 -translate-x-1/2 text-[11px] font-semibold ${met ? "text-up" : "text-down"}`} style={{ left: x(r.actual) }}>{r.actual.toFixed(1)}</div>
                    </div>
                  </div>
                );
              })}
              <div className="grid grid-cols-[92px_1fr] gap-2 sm:grid-cols-[150px_1fr]">
                <div />
                <div className="w-cond relative h-3 text-[10px] text-faint">{ticks.map((t) => <span key={t} className="absolute -translate-x-1/2" style={{ left: x(t) }}>{t}%</span>)}</div>
              </div>
            </div>
          </div>
        );
      })}
      <div className="flex flex-wrap gap-4 text-[12px] text-dim">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-5 rounded-[2px] bg-info/30 ring-1 ring-info/50" /> Guided range</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-up" /> Reported, met or beaten</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-down" /> Reported, missed</span>
      </div>
    </div>
  );
}

function Guidance({ t }: { t: string }) {
  const { data: g, error, loading, reload } = useAsync<any>(() => api.guidance(t), [t]);
  if (loading && !g) return <LoadingRows n={4} />;
  if (error) return <ErrorBox what="guidance" error={error} retry={reload} />;
  if (!g) return null;
  if (g.status !== "ok") return <div className="mt-5"><Empty title="No graded guidance yet">{g.interpretation} Fetch the company's documents from the Overview tab first.</Empty></div>;
  const s = g.summary;
  const byCall: Record<string, any[]> = {};
  g.rows.forEach((r: any) => { (byCall[r.said_in] = byCall[r.said_in] || []).push(r); });
  return (
    <div>
      <div className="mt-6 flex items-end gap-4">
        <div className="w-wide text-[56px] font-bold leading-none">{s.hit_rate === null ? "N/A" : `${s.hit_rate.toFixed(0)}%`}</div>
        <div className="pb-1 text-[14px] text-dim">of {s.graded} gradeable promises met or beaten, across {s.calls_covered.length} calls</div>
      </div>
      <div className="mt-3 grid grid-cols-4 border-y border-line">
        {[["Beaten", s.beaten, "text-up"], ["Met", s.met, "text-up"], ["Missed", s.missed, "text-down"], ["Pending", s.counts.pending, "text-dim"]].map(([l, v, c]) => (
          <div key={l as string} className="py-2"><div className="text-[12px] text-dim">{l}</div><div className={`w-cond text-[22px] font-semibold ${c}`}>{v}</div></div>
        ))}
      </div>
      <p className="mt-4 text-[15px] leading-relaxed">{g.interpretation}</p>
      {g.interpretation_method === "llm" && <p className="mt-1 text-[12px] text-faint">Written by the model from the computed table below.</p>}
      {g.revisions.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {g.revisions.map((r: any, i: number) => (
            <li key={i} className="flex items-center gap-2 text-[14px]">
              {r.direction === "up" ? <ArrowUpRight size={17} className="text-up" /> : <ArrowDownRight size={17} className="text-down" />}
              <span>{r.metric_label} {r.horizon}: <span className="w-cond">{r.from} → {r.to}</span> <span className="text-dim">({r.from_call} to {r.to_call} call)</span></span>
            </li>
          ))}
        </ul>
      )}
      {g.chart.length > 0 && <Section title="Guided versus reported"><Dumbbell rows={g.chart} /></Section>}
      <Section title="Every statement, by call">
        {Object.entries(byCall).map(([call, rs]) => (
          <div key={call} className="mb-4">
            <h3 className="text-[14px] font-semibold text-dim">{call} call</h3>
            <ul className="hairline border-y border-line">
              {rs.map((r: any) => (
                <li key={r.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[14px]">
                    <span className="font-semibold">{r.metric_label}</span>
                    <span className="text-dim">{r.horizon}</span>
                    <span className="w-cond">guided {r.target}</span>
                    {r.actual !== null && <span className="w-cond">reported {r.unit === "%" ? `${r.actual.toFixed(1)}%` : r.actual}</span>}
                    <Pill status={r.status} />
                    {r.revised && <span className={`text-[12px] ${r.revised === "up" ? "text-up" : "text-down"}`}>revised {r.revised}</span>}
                  </div>
                  <blockquote className="mt-2 border-l-2 border-info/50 pl-3 text-[14px] italic leading-relaxed text-fg/85">“{r.statement}”</blockquote>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12px] text-dim">
                    <span>{r.speaker}</span><span>p.{r.citation.page}</span><span>{r.commitment.replace("_", " ")}</span><span>{r.method === "llm" ? "LLM-extracted, verbatim-checked" : "rules-extracted"}</span>
                    {r.how_computed && <span className="text-faint">{r.how_computed}</span>}
                    {r.citation.document_id && <a className="inline-flex items-center gap-1 text-info" href={`/api/documents/${r.citation.document_id}/file#page=${r.citation.page}`} target="_blank" rel="noreferrer">Transcript <ExternalLink size={11} /></a>}
                    <DemoBadge show={r.citation.source === "demo"} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Section>
      <Section title="Caveats">
        <ul className="space-y-1 text-[13px] text-dim">{g.uncertainties.map((u: string) => <li key={u}>{u}</li>)}</ul>
      </Section>
    </div>
  );
}

const LABEL_COLOR: Record<string, string> = { stable: "text-up", monitor: "text-warn", elevated: "text-down", insufficient: "text-dim" };

function Health({ t }: { t: string }) {
  const { data: h, error, loading, reload } = useAsync<any>(() => api.health(t), [t]);
  if (loading && !h) return <LoadingRows n={5} />;
  if (error) return <ErrorBox what="financial health" error={error} retry={reload} />;
  if (!h) return null;
  return (
    <div>
      <div className="mt-6">
        <div className={`w-wide text-[34px] font-bold capitalize leading-none ${LABEL_COLOR[h.overall]}`}>{h.overall}</div>
        <p className="mt-2 text-[15px]">{h.reason}</p>
        <p className="mt-1 text-[12px] text-dim">Data completeness <span className="w-cond">{Math.round((h.data_completeness || 0) * 100)}%</span>{h.years?.length ? `, ${h.years[0]}–${h.years[h.years.length - 1]}` : ""}</p>
        {h.lender_note && <p className="mt-2 text-[13px] text-warn">{h.lender_note}</p>}
        <p className="mt-2 text-[12px] text-faint">{h.disclaimer}</p>
      </div>
      {h.pillars.map((p: any) => (
        <Section key={p.pillar} title={p.pillar} aside={<Pill status={p.label} />}>
          <ul className="hairline border-y border-line">
            {p.checks.map((c: any) => (
              <li key={c.metric} className="py-2.5">
                <div className="flex items-center gap-3">
                  <span className="min-w-0 flex-1 truncate text-[14px] font-medium">{c.metric}</span>
                  {c.history?.length > 1 && <Spark data={c.history.map((x: any) => x[1])} width={56} height={20} color="#8A9BB5" />}
                  <span className="w-cond w-20 shrink-0 text-right text-[15px] font-semibold">
                    {c.current === null ? "" : c.unit === "%" ? `${Number(c.current).toFixed(1)}%` : c.unit === "x" ? `${Number(c.current).toFixed(2)}×` : c.unit === "days" ? `${Math.round(c.current)}d` : cr(c.current)}
                  </span>
                  <Pill status={c.label} />
                </div>
                <p className="mt-1 text-[13px] text-dim">{c.interpretation}{c.direction && c.history?.length > 1 ? ` Trend ${c.direction}.` : ""}</p>
                {c.evidence && (
                  <details className="mt-1 text-[13px]">
                    <summary className="cursor-pointer text-info">Evidence, p.{c.evidence.page}</summary>
                    <blockquote className="mt-1 border-l-2 border-line pl-2.5 text-fg/80">{c.evidence.excerpt}</blockquote>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </Section>
      ))}
    </div>
  );
}

function BullBear({ t }: { t: string }) {
  const { data: b, error, loading, reload } = useAsync<any>(() => api.bullBear(t), [t]);
  if (loading && !b) return <LoadingRows n={3} />;
  if (error) return <ErrorBox what="the bull and bear case" error={error} retry={reload} />;
  if (!b) return null;
  return (
    <div className="mt-6">
      <div className="grid gap-4 md:grid-cols-2">
        {[["Bull case", b.bull, "border-up"], ["Bear case", b.bear, "border-down"]].map(([title, pts, c]) => (
          <div key={title as string} className={`border-l-2 ${c} pl-3.5`}>
            <h3 className="w-semi text-[17px] font-semibold">{title}</h3>
            {(pts as string[]).length ? (
              <ul className="mt-2 space-y-2">{(pts as string[]).map((p) => <li key={p}><AnswerText text={p} /></li>)}</ul>
            ) : <p className="mt-2 text-[14px] text-dim">Nothing in the data supports this side yet.</p>}
          </div>
        ))}
      </div>
      <p className="mt-4 text-[12px] text-faint">{b.note}</p>
    </div>
  );
}

function Documents({ d, onIngest }: { d: any; onIngest: () => void }) {
  return (
    <div className="mt-5">
      {d.documents.length === 0 ? (
        <Empty title="No documents yet">Fetch the latest annual report and four concall transcripts from screener.in.</Empty>
      ) : (
        <ul className="hairline border-y border-line">
          {d.documents.map((x: any) => (
            <li key={x.id} className="flex items-start gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium">{x.title}</div>
                <div className="mt-0.5 text-[12px] text-dim">{x.doc_type.replace("_", " ")}{x.period ? `, ${x.period}` : ""}{x.pages ? `, ${x.pages} pages` : ""}, <span className="w-cond">{x.passages}</span> passages indexed</div>
                {x.error && <div className="text-[12px] text-down">{x.error}</div>}
              </div>
              <Pill status={x.status} />
              {x.file_url && <a href={x.file_url} target="_blank" rel="noreferrer" className="text-[13px] text-info">PDF</a>}
            </li>
          ))}
        </ul>
      )}
      <Button small className="mt-3" onClick={onIngest}><RefreshCw size={14} /> Re-fetch from screener.in</Button>
      {d.ingestion && <p className="mt-2 text-[12px] text-dim">Last fetch: {d.ingestion.status} at {d.ingestion.at}</p>}
    </div>
  );
}

export default function Research({ ticker, tab = "overview" }: { ticker?: string; tab?: string }) {
  const ask = useAsk();
  const { data: d, error, loading, reload, setData } = useAsync<any>(() => (ticker ? api.research(ticker) : Promise.resolve(null)), [ticker]);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { if (ticker) ask.setTicker(ticker); /* eslint-disable-next-line */ }, [ticker]);
  useEffect(() => setNote(null), [ticker]);
  if (!ticker) return <Home />;
  if (loading && !d) return <LoadingRows n={5} />;
  if (error) return (
    <div>
      <ErrorBox what={`research for ${ticker}`} error={error} retry={reload} />
      <div className="mt-4"><Button small onClick={() => api.ingest(ticker).then(() => setNote(`Fetching ${ticker} from Yahoo Finance and screener.in in the background. Try again in a minute.`)).catch((e) => setNote(e.message))}><RefreshCw size={14} /> Fetch and index {ticker}</Button></div>
      {note && <p className="mt-2 text-[13px] text-dim">{note}</p>}
    </div>
  );
  if (!d) return null;
  const p = d.price;
  const ingest = () => {
    api.ingest(ticker).then(() => setNote(`Fetching ${ticker} in the background. This needs network access to screener.in; refresh in a minute.`))
      .catch((e) => setNote(`Could not start: ${e.message}`));
  };
  const toggleHold = async () => {
    try {
      if (d.in_portfolio) await api.removeHolding(ticker); else await api.addHolding(ticker);
      setData({ ...d, in_portfolio: !d.in_portfolio });
    } catch (e: any) { setNote(e.message); }
  };
  return (
    <div>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="w-wide text-[28px] font-bold leading-none">{d.ticker}</h1>
            <SourceBadge source={d.source} />
          </div>
          <div className="mt-1 truncate text-[14px] text-dim">{d.name}{d.sector ? `, ${d.sector}` : ""}</div>
        </div>
        {p && (
          <div className="shrink-0 text-right">
            <div className="w-cond text-[18px] font-semibold">{price(p.close)}</div>
            <div className="w-cond text-[13px]"><span className={tone(p.return_pct)}>{pct(p.return_pct, true, 2)}</span> <span className="text-dim">day</span> <span className={tone(p.return_1y_pct)}>{pct(p.return_1y_pct)}</span> <span className="text-dim">1y</span></div>
          </div>
        )}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div className="min-w-0 flex-1"><Spark data={d.spark} width={600} height={36} fluid /></div>
        <Button small onClick={toggleHold}>{d.in_portfolio ? "Remove from portfolio" : "Add to portfolio"}</Button>
      </div>
      {note && <p className="mt-2 text-[13px] text-dim" role="status">{note}</p>}
      <nav className="no-scrollbar -mx-4 mt-4 flex gap-1 overflow-x-auto border-b border-line px-4 md:mx-0 md:px-0" aria-label="Research views">
        {TABS.map((x) => (
          <a key={x.key} href={href(`research/${ticker}/${x.key}`)} aria-current={tab === x.key ? "page" : undefined}
            className={`shrink-0 whitespace-nowrap border-b-2 px-2.5 pb-2 pt-1 text-[14px] ${tab === x.key ? "border-info text-fg" : "border-transparent text-dim hover:text-fg"}`}>{x.label}</a>
        ))}
      </nav>
      {tab === "guidance" ? <Guidance t={ticker} /> : tab === "health" ? <Health t={ticker} /> : tab === "bullbear" ? <BullBear t={ticker} />
        : tab === "documents" ? <Documents d={d} onIngest={ingest} /> : <Overview d={d} onIngest={ingest} />}
    </div>
  );
}
