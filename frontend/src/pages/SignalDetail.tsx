import { ArrowLeft, ExternalLink, Pin, PinOff } from "lucide-react";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { clock, cr, longDate, price, shortDate } from "../lib/format";
import { href } from "../lib/router";
import { DemoBadge, ErrorBox, LoadingRows, Pill, PriorityLabel, ResultsTable, Section, Strip, useAsk, useAsync } from "../components/ui";
import { useEffect, useState } from "react";

const tip = { contentStyle: { background: "#1B2940", border: "1px solid #26354F", borderRadius: 6, fontSize: 12 }, labelStyle: { color: "#8A9BB5" } };

function WhyPanel({ why, demo }: { why: any; demo: boolean }) {
  const rows: [string, string, React.ReactNode][] = [
    ["What happened", "Confirmed from the filing", <ul className="space-y-1">{why.what_happened.map((w: string) => <li key={w}>{w}</li>)}</ul>],
    ["What it could mean", "Inference, not a fact", why.implication],
    ["Is this unusual?", "", <ul className="space-y-1">{why.is_it_unusual.map((w: string) => <li key={w}>{w}</li>)}<li>{why.financial_size}</li></ul>],
    ["What history supports this", "", (
      <span>{why.history.same_category_90d} similar filing{why.history.same_category_90d === 1 ? "" : "s"} from this company in 90 days
        {why.history.last_same_category ? `, the last on ${shortDate(why.history.last_same_category)}` : ""}.</span>)],
    ["What remains uncertain", "", (
      <ul className="space-y-1">{why.uncertain.map((u: string) => <li key={u} className={demo && u.startsWith("ILLUSTRATIVE") ? "text-warn" : ""}>{u}</li>)}</ul>)],
  ];
  return (
    <section className="mt-6 rounded border border-line bg-surface p-4">
      <h2 className="w-wide text-[18px] font-bold">Why should I care?</h2>
      <dl className="hairline mt-2">
        {rows.map(([t, note, body]) => (
          <div key={t} className="py-2.5">
            <dt className="text-[14px] font-semibold">{t} {note && <em className="ml-1 text-[12px] font-normal not-italic text-dim">({note})</em>}</dt>
            <dd className="mt-1 text-[14px] leading-relaxed text-fg/85">{body}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default function SignalDetail({ id }: { id: number }) {
  const { data: s, error, loading, reload, setData } = useAsync<any>(() => api.signal(id), [id]);
  const ask = useAsk();
  const [showText, setShowText] = useState(false);
  useEffect(() => { if (s) ask.setTicker(s.ticker); /* eslint-disable-next-line */ }, [s?.ticker]);

  if (loading && !s) return <LoadingRows n={5} />;
  if (error) return <ErrorBox what="this signal" error={error} retry={reload} />;
  if (!s) return null;
  const enr = s.enrichment || {};
  const card = enr.results;
  const people = enr.people || [];
  const demo = s.source === "demo";
  const pinned = s.triage === "pin";
  const togglePin = () => {
    const a = pinned ? "clear" : "pin";
    api.triage(s.id, a).then(() => setData({ ...s, triage: a === "clear" ? null : "pin" })).catch(() => {});
  };
  const px = s.price_context?.prices || [];

  return (
    <div>
      <a href={href("brief")} className="inline-flex items-center gap-1 text-[14px] text-dim hover:text-fg"><ArrowLeft size={16} /> Brief</a>
      <div className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <a href={href(`research/${s.ticker}`)} className="w-cond text-[20px] font-bold hover:text-info">{s.ticker}</a>
        <span className="text-[14px] text-dim">{s.company}{s.sector ? `, ${s.sector}` : ""}</span>
        {!s.in_portfolio && <span className="text-[12px] text-warn">Not in portfolio</span>}
      </div>
      <h1 className="w-semi mt-2 text-[22px] font-bold leading-snug md:text-[26px]">{s.summary}</h1>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] text-dim">
        <PriorityLabel p={s.priority} score={s.score} />
        <span>{s.category_label}{s.category_method === "llm" ? " (LLM-classified)" : ""}</span>
        <span>{longDate(s.published_at)}, {clock(s.published_at)} IST</span>
        <DemoBadge show={demo} />
        <button onClick={togglePin} aria-pressed={pinned} className={`ml-auto inline-flex items-center gap-1 rounded border px-2 py-1 ${pinned ? "border-info/50 text-info" : "border-line text-dim hover:text-fg"}`}>
          {pinned ? <PinOff size={14} /> : <Pin size={14} />} {pinned ? "Pinned" : "Pin"}
        </button>
      </div>
      <p className="mt-2 text-[13px] text-faint">Filed as: {s.subject}</p>

      {enr.why && <WhyPanel why={enr.why} demo={demo} />}

      {card && (
        <Section title={`Results, ${card.period_label}`} aside={card.verification && <Pill status={card.verification.status} />}>
          <p className="mb-2 text-[12px] text-dim">
            {card.basis} basis, {card.unit}, compared with {card.previous_label || "the previous quarter"} and {card.year_ago_label || "a year ago"}.
            {card.verification?.detail ? ` ${card.verification.detail}.` : ""}
          </p>
          <ResultsTable card={card} />
          {card.trend?.length > 1 && (
            <div className="mt-4 h-[210px]">
              <ResponsiveContainer>
                <ComposedChart data={card.trend} margin={{ top: 8, right: 4, left: -8, bottom: 0 }}>
                  <CartesianGrid stroke="#26354F" vertical={false} />
                  <XAxis dataKey="label" tick={{ fill: "#8A9BB5", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#26354F" }} interval="preserveStartEnd" />
                  <YAxis yAxisId="l" tick={{ fill: "#8A9BB5", fontSize: 11 }} tickLine={false} axisLine={false} width={52} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v)} />
                  <YAxis yAxisId="r" orientation="right" hide domain={["auto", "auto"]} />
                  <Tooltip {...tip} formatter={(v: any, n: any) => (n === "EBITDA margin" ? `${Number(v).toFixed(1)}%` : cr(v))} />
                  <Legend wrapperStyle={{ fontSize: 12, color: "#8A9BB5" }} />
                  <Bar yAxisId="l" dataKey="revenue" name="Revenue" fill="#5B9BF0" radius={[2, 2, 0, 0]} />
                  <Bar yAxisId="l" dataKey="pat" name="PAT" fill="#3FB98A" radius={[2, 2, 0, 0]} />
                  {!card.is_financial && <Line yAxisId="r" dataKey="ebitda_margin" name="EBITDA margin" stroke="#E0A84B" strokeWidth={2} dot={{ r: 2 }} />}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </Section>
      )}

      {people.length > 0 && (
        <Section title="Who is involved">
          <div className="grid gap-3 sm:grid-cols-2">
            {people.map((p: any) => (
              <div key={p.name} className="rounded border border-line bg-surface p-3.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[16px] font-semibold">{p.name}</span>
                  <span className={`text-[13px] ${p.change === "joins" ? "text-up" : "text-warn"}`}>{p.change === "joins" ? "Joins" : p.change === "leaves" ? "Leaves" : "Retires"}</span>
                </div>
                <div className="text-[14px] text-dim">{p.role}</div>
                {(p.effective || p.reason) && <div className="mt-1 text-[13px] text-dim">{p.effective ? `Effective ${p.effective}` : ""}{p.effective && p.reason ? ". " : ""}{p.reason ? p.reason.charAt(0).toUpperCase() + p.reason.slice(1) : ""}</div>}
                {p.profile && <p className="mt-2 text-[14px] leading-relaxed text-fg/85">{p.profile}</p>}
                <a href={p.linkedin_search} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[13px] text-info">Search LinkedIn <ExternalLink size={12} /></a>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-faint">Background is read from the profile the company must include in the filing (SEBI LODR). LinkedIn is not scraped.</p>
        </Section>
      )}

      {enr.questions?.length > 0 && (
        <Section title="Questions worth asking">
          <ul className="hairline border-y border-line">
            {enr.questions.map((q: string) => (
              <li key={q}><button onClick={() => ask.open(q.replace(/\s*\([^)]*\)\s*$/, ""), s.ticker)} className="w-full py-2.5 text-left text-[14px] hover:text-info">{q}</button></li>
            ))}
          </ul>
          <a href={href(`research/${s.ticker}`)} className="mt-2 inline-block text-[14px] text-info">Open {s.ticker} research</a>
        </Section>
      )}

      <Section title="How FINN ranked this">
        <div className="flex items-end gap-4">
          <div className="w-wide text-[40px] font-bold leading-none">{s.score.toFixed(0)}</div>
          <div className="min-w-0 flex-1 pb-1"><Strip breakdown={s.breakdown} height={10} legend /></div>
        </div>
        <div className="mt-3">
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-[12px] text-dim">
              <th className="py-1 font-normal">Component</th><th className="py-1 font-normal">Reason</th>
              <th className="py-1 text-right font-normal">Score</th><th className="hidden py-1 text-right font-normal sm:table-cell">Weight</th>
              <th className="py-1 text-right font-normal">Adds</th></tr></thead>
            <tbody>
              {s.breakdown.map((b: any) => (
                <tr key={b.key} className="border-t border-line align-top">
                  <td className="py-2 pr-2"><span className="inline-flex items-center gap-1.5 whitespace-nowrap"><span className="h-2 w-2 rounded-[2px]" style={{ background: `var(--c-${b.key}, ${({ category: "#5B9BF0", financial: "#3FB98A", deviation: "#E0A84B", relevance: "#A48BE8", novelty: "#4FC3C9" } as any)[b.key]})` }} />{b.label}</span></td>
                  <td className="py-2 pr-2 text-dim">{b.reason}</td>
                  <td className="w-cond py-2 text-right">{b.value.toFixed(0)}</td>
                  <td className="w-cond hidden py-2 text-right text-dim sm:table-cell">{(b.weight * 100).toFixed(0)}%</td>
                  <td className="w-cond py-2 text-right font-semibold">{b.contribution.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {px.length > 1 && (
        <Section title="Price around the filing">
          <div className="h-[200px]">
            <ResponsiveContainer>
              <ComposedChart data={px} margin={{ top: 8, right: 4, left: -8, bottom: 0 }}>
                <CartesianGrid stroke="#26354F" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d) => shortDate(d)} tick={{ fill: "#8A9BB5", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#26354F" }} minTickGap={24} />
                <YAxis yAxisId="p" domain={["auto", "auto"]} tick={{ fill: "#8A9BB5", fontSize: 11 }} tickLine={false} axisLine={false} width={52} />
                <YAxis yAxisId="v" orientation="right" hide />
                <Tooltip {...tip} labelFormatter={(d) => shortDate(String(d))} formatter={(v: any, n: any) => (n === "Close" ? price(v) : Number(v).toLocaleString("en-IN"))} />
                <Bar yAxisId="v" dataKey="volume" name="Volume" fill="#26354F" />
                <Line yAxisId="p" dataKey="close" name="Close" stroke="#5B9BF0" strokeWidth={2} dot={false} />
                <ReferenceLine yAxisId="p" x={s.price_context.reaction_date} stroke="#E0A84B" strokeDasharray="4 3" label={{ value: "filing", fill: "#E0A84B", fontSize: 11, position: "insideTopRight" }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Section>
      )}

      <Section title="Original filing">
        {s.attachment_url ? (
          <a href={s.attachment_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[14px] text-info">Open on the exchange <ExternalLink size={13} /></a>
        ) : (
          <div>
            <button onClick={() => setShowText(!showText)} className="text-[14px] text-info" aria-expanded={showText}>{showText ? "Hide" : "Show"} the {demo ? "demo " : ""}filing text</button>
            {showText && (
              <pre className="mt-2 max-h-[320px] overflow-auto whitespace-pre-wrap rounded border border-line bg-surface p-3 text-[12px] leading-relaxed text-dim">
                {[s.body, s.attachment_text].filter(Boolean).join("\n\n").replace(/\f/g, "\n\n— page break —\n\n")}
              </pre>
            )}
          </div>
        )}
      </Section>

      {s.related?.length > 0 && (
        <Section title={`Earlier filings from ${s.ticker}`}>
          <ul className="hairline border-y border-line">
            {s.related.map((r: any) => (
              <li key={r.id}><a href={href(`signal/${r.id}`)} className="flex items-baseline gap-3 py-2 text-[14px] hover:text-info">
                <span className="w-cond w-14 shrink-0 text-dim">{shortDate(r.published_at)}</span>
                <span className="min-w-0 flex-1 truncate">{r.summary}</span>
                <PriorityLabel p={r.priority} />
              </a></li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
