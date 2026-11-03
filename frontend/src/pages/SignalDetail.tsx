import { ArrowLeft, ExternalLink, HelpCircle, Linkedin, Microscope, Pin } from "lucide-react";
import { useEffect } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAsk } from "../components/Ask";
import { ErrorState, H2, ListSkeleton, MaterialityStrip, PriorityTag, SourceBadge, StatusPill } from "../components/ui";
import { post, useApi } from "../lib/api";
import { COMPONENTS, cr, crShort, pct, tone, when } from "../lib/format";
import { back, go } from "../lib/router";

export default function SignalDetail({ id }: { id: string }) {
  const { data: d, error, loading, reload } = useApi(`/api/signals/${id}`);
  const { setTicker, ask } = useAsk();
  useEffect(() => { if (d?.ticker) setTicker(d.ticker); }, [d?.ticker]);
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !d) return <ListSkeleton rows={6} />;
  const e = d.enrichment ?? {};
  const why = e.why ?? {};

  return (
    <article>
      <button onClick={back} className="mb-4 inline-flex items-center gap-1 text-[13px] text-dim hover:text-fg"><ArrowLeft className="h-4 w-4" />Back</button>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-dim">
        <button onClick={() => go("research", d.ticker)} className="text-[16px] font-bold text-fg hover:underline">{d.ticker}</button>
        <span>{d.company}</span><span>{d.sector}</span>
        {!d.in_portfolio && <span className="text-faint">Not in portfolio</span>}
      </div>
      <h1 className="w-semi mt-2 text-[22px] font-semibold leading-tight md:text-[26px]">{d.summary}</h1>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-dim">
        <PriorityTag p={d.priority} score={d.score} />
        <span>{d.category_label}{d.category_method === "llm" ? " (LLM-classified)" : ""}</span>
        <span>{when(d.published_at)}</span>
        <SourceBadge source={d.source} />
        <button onClick={() => post(`/api/signals/${d.id}/triage`, { action: d.triage === "pin" ? "clear" : "pin" }).then(reload)} className={`inline-flex items-center gap-1 ${d.triage === "pin" ? "text-up" : "hover:text-fg"}`}><Pin className="h-3.5 w-3.5" />{d.triage === "pin" ? "Pinned" : "Pin"}</button>
      </div>
      <p className="mt-3 text-[13.5px] text-dim">Filed as: {d.subject}</p>

      {/* ---------------- Why should I care? */}
      <section className="mt-6 rounded border border-line bg-surface p-4">
        <h2 className="w-wide text-[17px] font-bold">Why should I care?</h2>
        <WhyBlock title="What happened" tag="Confirmed from the filing">
          <ul className="space-y-1">{(why.what_happened ?? []).map((x: string, i: number) => <li key={i} className="num">{x}</li>)}</ul>
        </WhyBlock>
        {why.implication && <WhyBlock title="What it could mean" tag="Inference, not a fact"><p>{why.implication}</p><p className="mt-1 text-dim">Size: {why.financial_size}</p></WhyBlock>}
        <WhyBlock title="Is this unusual for the company?"><ul className="space-y-1">{(why.is_it_unusual ?? []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></WhyBlock>
        <WhyBlock title="What history supports this"><ul className="space-y-1">{(why.history ?? []).map((x: string, i: number) => <li key={i} className="num">{x}</li>)}</ul></WhyBlock>
        {why.uncertain?.length > 0 && <WhyBlock title="What remains uncertain"><ul className="space-y-1">{why.uncertain.map((x: string, i: number) => <li key={i} className={x.startsWith("ILLUSTRATIVE") ? "text-warn" : ""}>{x}</li>)}</ul></WhyBlock>}
      </section>

      {e.results && <ResultsCard card={e.results} />}
      {e.management && <People m={e.management} />}

      <H2>Questions worth asking</H2>
      <ul className="space-y-1.5">
        {(e.questions ?? []).map((q: string) => (
          <li key={q}>
            <button onClick={() => { setTicker(d.ticker); ask(q.replace(/\s*\(.*?\)\s*$/, ""), d.ticker); }} className="flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-[14px] hover:bg-surface">
              <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-info" /><span>{q}</span>
            </button>
          </li>
        ))}
        <li><button onClick={() => go("research", d.ticker)} className="flex items-center gap-2 px-2 py-1.5 text-[14px] text-info hover:underline"><Microscope className="h-4 w-4" />Open {d.ticker} research</button></li>
      </ul>

      <H2>How FINN ranked this</H2>
      <div className="rounded border border-line p-3">
        <div className="mb-2 flex items-baseline justify-between"><span className="num w-cond text-[28px] font-semibold">{Math.round(d.score)}</span><span className="text-[12px] text-dim">of 100, weighted sum of five rules</span></div>
        <MaterialityStrip breakdown={d.score_breakdown} score={d.score} height={10} showLegend />
        <table className="num mt-3 w-full text-[13px]">
          <thead><tr className="text-left text-[11.5px] text-dim"><th className="pb-1 font-normal">Component</th><th className="pb-1 text-right font-normal">Score</th><th className="pb-1 text-right font-normal">Weight</th><th className="pb-1 text-right font-normal">Adds</th></tr></thead>
          <tbody>
            {COMPONENTS.map((c) => {
              const b = d.score_breakdown?.[c.key];
              if (!b) return null;
              return (
                <tr key={c.key} className="border-t border-line align-top">
                  <td className="py-1.5 pr-2"><span className="mr-1.5 inline-block h-2 w-2 rounded-sm" style={{ background: c.color }} />{c.label}<div className="text-[12px] text-dim">{b.reason}</div></td>
                  <td className="py-1.5 text-right">{b.value}</td><td className="py-1.5 text-right text-dim">{b.weight}</td><td className="py-1.5 text-right font-semibold">{b.contribution}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {d.price_context?.length > 5 && <PriceContext rows={d.price_context} at={d.published_at} />}

      <H2>Original filing</H2>
      {d.attachment_url ? (
        <a href={d.attachment_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-[14px] text-info hover:underline"><ExternalLink className="h-4 w-4" />Open on the exchange</a>
      ) : (
        <div className="text-[13px] text-dim">{d.source === "demo" ? "Illustrative filing text (no exchange link in demo mode):" : "No attachment link."}</div>
      )}
      {d.body && <pre className="scroll-thin mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded border border-line bg-surface p-3 font-sans text-[12.5px] leading-relaxed text-dim">{d.body}</pre>}

      {d.related?.length > 0 && (
        <>
          <H2>Earlier filings from {d.ticker}</H2>
          <ul className="divide-y divide-line border-y border-line">
            {d.related.map((r: any) => (
              <li key={r.id}><button onClick={() => go("signal", r.id)} className="flex w-full items-baseline gap-3 py-2 text-left text-[13px]"><PriorityTag p={r.priority} /><span className="min-w-0 flex-1">{r.summary}</span><span className="shrink-0 text-[12px] text-faint">{when(r.published_at)}</span></button></li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}

function WhyBlock({ title, tag, children }: { title: string; tag?: string; children: React.ReactNode }) {
  return (
    <div className="mt-4 border-t border-line pt-3 text-[14px] leading-relaxed">
      <div className="mb-1 flex flex-wrap items-baseline gap-2"><h3 className="font-semibold">{title}</h3>{tag && <span className="text-[11.5px] text-dim">{tag}</span>}</div>
      {children}
    </div>
  );
}

export function ResultsCard({ card }: { card: any }) {
  return (
    <section className="mt-6">
      <H2 right={card.verification && <StatusPill status={card.verification.status} />}>Results: {card.period}</H2>
      <div className="text-[12px] text-dim">{card.basis ? `${card.basis[0].toUpperCase()}${card.basis.slice(1)}` : ""}, {card.unit}. Compared with {card.previous_period ?? "previous quarter"} and {card.year_ago_period ?? "same quarter last year"}.</div>
      <div className="mt-2 overflow-x-auto">
        <table className="num w-full text-[13.5px]">
          <thead><tr className="text-left text-[11.5px] text-dim"><th className="py-1 font-normal" /> <th className="py-1 text-right font-normal">{card.period}</th><th className="py-1 text-right font-normal">QoQ</th><th className="py-1 text-right font-normal">YoY</th><th className="hidden py-1 text-right font-normal sm:table-cell">{card.year_ago_period}</th></tr></thead>
          <tbody>
            {card.rows.map((r: any) => (
              <tr key={r.metric} className="border-t border-line">
                <td className="py-2 font-semibold">{r.label}</td>
                <td className="py-2 text-right">{r.current == null ? <span className="text-faint" title={r.note ?? ""}>N/A</span> : crShort(r.current)}</td>
                <td className={`py-2 text-right ${tone(r.qoq_pct)}`}>{pct(r.qoq_pct)}</td>
                <td className={`w-cond py-2 text-right text-[15px] font-semibold ${tone(r.yoy_pct)}`}>{pct(r.yoy_pct)}</td>
                <td className="hidden py-2 text-right text-dim sm:table-cell">{crShort(r.year_ago)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {card.margins?.ebitda_margin != null && (
        <div className="num mt-2 text-[13px] text-dim">EBITDA margin {card.margins.ebitda_margin}% vs {card.margins.ebitda_margin_yoy}% a year ago
          {card.margins.ebitda_margin_change_bps_yoy != null && <span className={tone(card.margins.ebitda_margin_change_bps_yoy)}> ({card.margins.ebitda_margin_change_bps_yoy > 0 ? "+" : ""}{card.margins.ebitda_margin_change_bps_yoy} bps)</span>}</div>
      )}
      {card.rows.find((r: any) => r.note) && <div className="mt-1 text-[12px] text-faint">{card.rows.find((r: any) => r.note).note}</div>}
      {card.verification && <div className="mt-1 text-[12px] text-dim">{card.verification.detail}</div>}
      {card.flags?.map((f: string) => <div key={f} className="mt-1 text-[12.5px] text-warn">{f}</div>)}
      {card.trend?.length > 2 && (
        <div className="mt-3 h-44">
          <ResponsiveContainer>
            <ComposedChart data={card.trend} margin={{ top: 6, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="#26354F" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "#8A9BB5", fontSize: 10.5 }} tickFormatter={(v) => v.replace(" FY", " ’")} axisLine={false} tickLine={false} />
              <YAxis yAxisId="l" tick={{ fill: "#8A9BB5", fontSize: 10.5 }} axisLine={false} tickLine={false} tickFormatter={(v) => crShort(v)} />
              <YAxis yAxisId="r" orientation="right" hide domain={["auto", "auto"]} />
              <Tooltip contentStyle={{ background: "#1B2940", border: "1px solid #26354F", borderRadius: 6, fontSize: 12 }} formatter={(v: any, n: any) => [n === "EBITDA margin" ? `${v}%` : cr(v), n]} />
              <Bar yAxisId="l" dataKey="revenue" name="Revenue" fill="#5B9BF0" radius={[2, 2, 0, 0]} maxBarSize={22} />
              <Bar yAxisId="l" dataKey="pat" name="PAT" fill="#3FB98A" radius={[2, 2, 0, 0]} maxBarSize={22} />
              {card.trend.some((t: any) => t.ebitda_margin != null) && <Line yAxisId="r" dataKey="ebitda_margin" name="EBITDA margin" stroke="#E0A84B" strokeWidth={1.6} dot={{ r: 2 }} />}
            </ComposedChart>
          </ResponsiveContainer>
          <div className="mt-1 flex gap-3 text-[11px] text-dim"><Key c="#5B9BF0" l="Revenue" /><Key c="#3FB98A" l="PAT" />{card.trend.some((t: any) => t.ebitda_margin != null) && <Key c="#E0A84B" l="EBITDA margin (right scale)" />}</div>
        </div>
      )}
    </section>
  );
}

const Key = ({ c, l }: { c: string; l: string }) => <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: c }} />{l}</span>;

function People({ m }: { m: any }) {
  return (
    <section className="mt-6">
      <H2>Who is involved</H2>
      <div className="space-y-3">
        {m.people.map((p: any, i: number) => (
          <div key={i} className="rounded border border-line p-3">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[15px] font-semibold">{p.name ?? "Name not stated"}</span>
              <span className={`text-[12.5px] ${p.change === "appointment" ? "text-up" : "text-warn"}`}>{p.change}</span>
              <span className="text-[12.5px] text-dim">{p.role}</span>
            </div>
            {(p.effective || p.reason) && <div className="mt-0.5 text-[12.5px] text-dim">{p.effective && `Effective ${p.effective}`}{p.effective && p.reason ? ", " : ""}{p.reason}</div>}
            {p.profile ? <p className="mt-2 text-[13.5px] leading-relaxed">{p.profile}</p> : p.change === "appointment" && <p className="mt-2 text-[13px] text-faint">The filing gives no profile.</p>}
            {p.linkedin_search && <a href={p.linkedin_search} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[12.5px] text-info hover:underline"><Linkedin className="h-3.5 w-3.5" />Search LinkedIn</a>}
          </div>
        ))}
      </div>
      <div className="mt-1 text-[11.5px] text-faint">Background is read from the profile the company must include in the filing (SEBI LODR), extracted by {m.method === "llm" ? "a small LLM" : "rules"}.</div>
    </section>
  );
}

function PriceContext({ rows, at }: { rows: any[]; at: string }) {
  const day = at.slice(0, 10);
  const mark = rows.find((r) => r.date >= day)?.date;
  return (
    <section>
      <H2>Price around the filing</H2>
      <div className="h-36">
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 6, right: 4, left: -14, bottom: 0 }}>
            <CartesianGrid stroke="#26354F" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: "#8A9BB5", fontSize: 10.5 }} tickFormatter={(v) => v.slice(5)} axisLine={false} tickLine={false} minTickGap={24} />
            <YAxis yAxisId="p" domain={["auto", "auto"]} tick={{ fill: "#8A9BB5", fontSize: 10.5 }} axisLine={false} tickLine={false} width={52} />
            <YAxis yAxisId="v" hide />
            <Tooltip contentStyle={{ background: "#1B2940", border: "1px solid #26354F", borderRadius: 6, fontSize: 12 }} />
            <Bar yAxisId="v" dataKey="volume" name="Volume" fill="#33446280" maxBarSize={8} />
            <Line yAxisId="p" dataKey="close" name="Close" stroke="#E6ECF5" strokeWidth={1.5} dot={false} />
            {mark && <ReferenceLine yAxisId="p" x={mark} stroke="#E0A84B" strokeDasharray="3 3" label={{ value: "filing", fill: "#E0A84B", fontSize: 10, position: "insideTopRight" }} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="text-[11.5px] text-faint">End-of-day closes and volumes.</div>
    </section>
  );
}
