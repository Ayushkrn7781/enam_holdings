// Display formatting. All numbers arrive computed from the API; nothing here does finance maths.

function indianGroup(n: number): string {
  const s = Math.trunc(Math.abs(n)).toString();
  if (s.length <= 3) return s;
  const head = s.slice(0, -3);
  const tail = s.slice(-3);
  return head.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + tail;
}

export function cr(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "N/A";
  const sign = x < 0 ? "−" : "";
  const abs = Math.abs(x);
  const frac = digits ? "." + abs.toFixed(digits).split(".")[1] : "";
  return `${sign}₹${indianGroup(Math.round(abs * 10 ** digits) / 10 ** digits)}${frac} Cr`;
}

export function num(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined) return "N/A";
  return indianGroup(Math.round(x)) + (digits ? "." + Math.abs(x).toFixed(digits).split(".")[1] : "");
}

export function pct(x: number | null | undefined, signed = true, digits = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "N/A";
  const v = x.toFixed(digits);
  if (!signed) return `${v}%`;
  return x > 0 ? `+${v}%` : x < 0 ? `−${Math.abs(x).toFixed(digits)}%` : `${v}%`;
}

export function tone(x: number | null | undefined): string {
  if (x === null || x === undefined) return "text-dim";
  return x > 0 ? "text-up" : x < 0 ? "text-down" : "text-dim";
}

export function price(x: number | null | undefined): string {
  if (x === null || x === undefined) return "N/A";
  return "₹" + indianGroup(x) + "." + x.toFixed(2).split(".")[1];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// Timestamps are naive IST from the API; parse them as wall-clock values.
function parts(iso: string) {
  const [d, t = "00:00:00"] = iso.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [hh, mm] = t.split(":").map(Number);
  return { y, m, day, hh, mm, date: new Date(y, m - 1, day, hh, mm) };
}

export function shortDate(iso: string): string {
  const p = parts(iso);
  return `${p.day} ${MONTHS[p.m - 1]}`;
}

export function longDate(iso: string): string {
  const p = parts(iso);
  return `${DAYS[p.date.getDay()]}, ${p.day} ${MONTHS_LONG[p.m - 1]}`;
}

export function clock(iso: string): string {
  const p = parts(iso);
  return `${String(p.hh).padStart(2, "0")}:${String(p.mm).padStart(2, "0")}`;
}

export function relTime(iso: string, anchorIso?: string): string {
  const a = anchorIso ? parts(anchorIso).date : new Date();
  const d = parts(iso).date;
  const mins = Math.round((a.getTime() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.round(h / 24);
  if (days < 7) return `${days}d ago`;
  return shortDate(iso);
}

export const PRIORITY_COLOR: Record<string, string> = {
  critical: "#E5675F", high: "#E0A84B", medium: "#5B9BF0", low: "#5C6C86",
};

export const COMPONENT_COLOR: Record<string, string> = {
  category: "#5B9BF0", financial: "#3FB98A", deviation: "#E0A84B", relevance: "#A48BE8", novelty: "#4FC3C9",
};

export const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  exceeded: { label: "Beaten", cls: "text-up border-up/40 bg-up/10" },
  achieved: { label: "Met", cls: "text-up border-up/40 bg-up/10" },
  missed: { label: "Missed", cls: "text-down border-down/40 bg-down/10" },
  pending: { label: "Pending", cls: "text-dim border-line bg-raised" },
  long_dated: { label: "Long-dated", cls: "text-dim border-line bg-raised" },
  not_comparable: { label: "Not comparable", cls: "text-faint border-line bg-raised" },
  qualitative: { label: "Qualitative", cls: "text-faint border-line bg-raised" },
  stable: { label: "Stable", cls: "text-up border-up/40 bg-up/10" },
  monitor: { label: "Monitor", cls: "text-warn border-warn/40 bg-warn/10" },
  elevated: { label: "Elevated", cls: "text-down border-down/40 bg-down/10" },
  insufficient: { label: "Insufficient data", cls: "text-faint border-line bg-raised" },
  verified: { label: "Verified against filing", cls: "text-up border-up/40 bg-up/10" },
  mismatch: { label: "Mismatch with filing", cls: "text-down border-down/40 bg-down/10" },
  single_source: { label: "Filing only", cls: "text-warn border-warn/40 bg-warn/10" },
  unverified: { label: "Not cross-checked", cls: "text-warn border-warn/40 bg-warn/10" },
  indexed: { label: "Indexed", cls: "text-up border-up/40 bg-up/10" },
  failed: { label: "Failed", cls: "text-down border-down/40 bg-down/10" },
  downloaded: { label: "Downloaded", cls: "text-dim border-line bg-raised" },
  discovered: { label: "Found", cls: "text-dim border-line bg-raised" },
};
