// Thin typed client over the FINN API.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError(0, "Could not reach the FINN server.");
  }
  const text = await r.text();
  const body = text ? JSON.parse(text) : null;
  if (!r.ok) throw new ApiError(r.status, (body && (body.detail || body.error)) || `Request failed (${r.status})`);
  return body as T;
}

const qs = (p: Record<string, unknown>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, String(x)));
    else u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
};

export type Priority = "critical" | "high" | "medium" | "low";

export interface Breakdown { key: string; label: string; contribution: number; value: number; weight: number; reason: string }
export interface ResultsRow { key: string; label: string; current: number | null; previous?: number | null; year_ago?: number | null; qoq: number | null; yoy: number | null; note?: string | null }
export interface Signal {
  id: number; ticker: string; company: string; sector: string | null; published_at: string; subject: string;
  exchange_category: string | null; category: string; category_label: string; subtype: string; category_method: string;
  score: number; priority: Priority; summary: string; is_duplicate: boolean; source: string; attachment_url: string | null;
  breakdown: Breakdown[]; why_rank: string; triage: "pin" | "dismiss" | null;
  results_preview?: { period_label: string; verification: string | null; rows: ResultsRow[] };
  bio_preview?: { name: string; role: string | null; change: string | null; profile: string | null };
}
export interface Digest {
  anchor: string; window: { start: string; end: string; hours: number }; headline: string;
  lines: { label: string; tickers: string[] }[];
  counts: { filings: number; companies: number; critical: number; high: number; medium: number; routine: number };
  items: Signal[]; routine: Signal[]; routine_summary: { label: string; count: number }[];
  moves: { ticker: string; kind: string; message: string; value: number; date: string; priority: string }[];
  data_mode: string;
}

export const api = {
  status: () => req<any>("/api/system/data-status"),
  demoReset: () => req<any>("/api/system/demo-reset", { method: "POST" }),
  evalResults: () => req<any>("/api/system/eval"),
  categories: () => req<{ categories: { key: string; label: string; importance: number }[] }>("/api/meta/categories"),
  digest: (p: Record<string, unknown>) => req<Digest>(`/api/digest${qs(p)}`),
  signal: (id: number) => req<any>(`/api/signals/${id}`),
  triage: (id: number, action: "pin" | "dismiss" | "clear") =>
    req<any>(`/api/signals/${id}/triage`, { method: "POST", body: JSON.stringify({ action }) }),
  portfolio: () => req<any>("/api/portfolio"),
  addHolding: (ticker: string) => req<any>("/api/portfolio", { method: "POST", body: JSON.stringify({ ticker }) }),
  removeHolding: (ticker: string) => req<any>(`/api/portfolio/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
  search: (q: string) => req<{ results: any[] }>(`/api/companies/search${qs({ q })}`),
  research: (t: string) => req<any>(`/api/research/${encodeURIComponent(t)}`),
  guidance: (t: string) => req<any>(`/api/research/${encodeURIComponent(t)}/management-guidance`),
  health: (t: string) => req<any>(`/api/research/${encodeURIComponent(t)}/financial-health`),
  bullBear: (t: string) => req<any>(`/api/research/${encodeURIComponent(t)}/bull-bear`),
  documents: (t: string) => req<any>(`/api/research/${encodeURIComponent(t)}/documents`),
  ingest: (t: string) => req<any>(`/api/research/${encodeURIComponent(t)}/ingest`, { method: "POST" }),
  ask: (ticker: string, question: string) =>
    req<any>("/api/research/query", { method: "POST", body: JSON.stringify({ ticker, question }) }),
  alerts: () => req<any>("/api/alerts"),
  addAlert: (body: Record<string, unknown>) => req<any>("/api/alerts", { method: "POST", body: JSON.stringify(body) }),
  patchAlert: (id: number, body: Record<string, unknown>) =>
    req<any>(`/api/alerts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteAlert: (id: number) => req<any>(`/api/alerts/${id}`, { method: "DELETE" }),
  alertsSeen: () => req<any>("/api/alerts/seen", { method: "POST" }),
  weights: () => req<any>("/api/settings/materiality"),
  putWeights: (weights: Record<string, number>) =>
    req<any>("/api/settings/materiality", { method: "PUT", body: JSON.stringify({ weights }) }),
};
