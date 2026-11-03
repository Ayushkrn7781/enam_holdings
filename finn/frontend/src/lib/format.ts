/** Indian number formatting: lakh/crore digit grouping. All financial values in FINN are ₹ crore. */
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const cr = (v: number | null | undefined) => (v == null ? "N/A" : `₹${inr.format(v)} Cr`);
export const crShort = (v: number | null | undefined) => (v == null ? "N/A" : inr.format(v));
export const rupee = (v: number | null | undefined) => (v == null ? "N/A" : `₹${inr2.format(v)}`);
export const pct = (v: number | null | undefined, signed = true, d = 1) =>
  v == null ? "N/A" : `${signed && v > 0 ? "+" : ""}${v.toFixed(d)}%`;
export const times = (v: number | null | undefined) => (v == null ? "N/A" : `${v.toFixed(1)}×`);
export const tone = (v: number | null | undefined) => (v == null ? "text-dim" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-dim");
export const vol = (v: number | null | undefined) => {
  if (v == null) return "N/A";
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(1)} L`;
  return inr.format(v);
};

export function when(iso: string, anchor?: string) {
  const d = new Date(iso);
  const ref = anchor ? new Date(anchor) : new Date();
  const mins = Math.round((ref.getTime() - d.getTime()) / 60000);
  if (mins >= 0 && mins < 60) return `${mins}m ago`;
  if (mins >= 0 && mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) + ", " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}
export const dateShort = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export const PRIORITY: Record<string, { label: string; cls: string; dot: string }> = {
  critical: { label: "Critical", cls: "text-down", dot: "bg-down" },
  high: { label: "High", cls: "text-warn", dot: "bg-warn" },
  medium: { label: "Medium", cls: "text-info", dot: "bg-info" },
  low: { label: "Low", cls: "text-faint", dot: "bg-faint" },
};

export const COMPONENTS = [
  { key: "category", label: "Category", color: "#5B9BF0" },
  { key: "financial", label: "Financial size", color: "#3FB98A" },
  { key: "deviation", label: "Unusualness", color: "#E0A84B" },
  { key: "relevance", label: "Relevance to you", color: "#A48BE8" },
  { key: "novelty", label: "Novelty", color: "#4FC3C9" },
] as const;
