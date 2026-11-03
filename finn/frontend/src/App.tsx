import { Bell, BriefcaseBusiness, Microscope, Newspaper, Settings as Cog } from "lucide-react";
import { AskBar, AskProvider } from "./components/Ask";
import { useApi } from "./lib/api";
import { go, useRoute } from "./lib/router";
import Alerts from "./pages/Alerts";
import Brief from "./pages/Brief";
import Portfolio from "./pages/Portfolio";
import Research from "./pages/Research";
import Settings from "./pages/Settings";
import SignalDetail from "./pages/SignalDetail";

const NAV = [
  { key: "brief", label: "Brief", icon: Newspaper },
  { key: "portfolio", label: "Portfolio", icon: BriefcaseBusiness },
  { key: "research", label: "Research", icon: Microscope },
  { key: "alerts", label: "Alerts", icon: Bell },
] as const;

export default function App() {
  return (
    <AskProvider>
      <Shell />
    </AskProvider>
  );
}

function Shell() {
  const route = useRoute();
  const [page, a, b] = route;
  const status = useApi("/api/system/data-status");
  const alerts = useApi("/api/alerts?limit=1", [page]);
  const mode = status.data?.mode;
  const active = page === "signal" ? "brief" : page;

  let body;
  if (page === "signal" && a) body = <SignalDetail id={a} />;
  else if (page === "portfolio") body = <Portfolio />;
  else if (page === "research") body = <Research ticker={a} tab={b} />;
  else if (page === "alerts") body = <Alerts />;
  else if (page === "settings") body = <Settings />;
  else body = <Brief />;

  const unseen = alerts.data?.unseen ?? 0;
  return (
    <div className="min-h-full md:flex">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line bg-ink px-3 py-5 md:flex">
        <Wordmark />
        <nav className="mt-8 space-y-0.5">
          {NAV.map((n) => (
            <button key={n.key} onClick={() => go(n.key)} aria-current={active === n.key ? "page" : undefined}
              className={`flex w-full items-center gap-3 rounded px-3 py-2 text-[14px] ${active === n.key ? "bg-surface text-fg" : "text-dim hover:bg-surface/60 hover:text-fg"}`}>
              <n.icon className="h-4 w-4" />{n.label}
              {n.key === "alerts" && unseen > 0 && <span className="num ml-auto rounded-sm bg-down/20 px-1.5 text-[11px] text-down">{unseen}</span>}
            </button>
          ))}
        </nav>
        <div className="mt-auto space-y-3">
          <button onClick={() => go("settings")} className={`flex w-full items-center gap-3 rounded px-3 py-2 text-[14px] ${active === "settings" ? "bg-surface text-fg" : "text-dim hover:text-fg"}`}><Cog className="h-4 w-4" />Settings</button>
          <ModeNote mode={mode} />
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        {/* mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-ink/95 px-4 py-2.5 backdrop-blur md:hidden">
          <Wordmark />
          <div className="flex items-center gap-1">
            {mode?.mode === "demo" && <button onClick={() => go("settings")} className="rounded-sm bg-warn/15 px-1.5 py-px text-[11px] font-semibold text-warn">Demo data</button>}
            <button onClick={() => go("settings")} aria-label="Settings" className="rounded p-1.5 text-dim hover:text-fg"><Cog className="h-5 w-5" /></button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-3xl px-4 pb-40 pt-4 md:px-8 md:pb-28 md:pt-8">{body}</main>

        {/* docked Ask bar + mobile tab bar */}
        <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 md:left-56">
          <div className="pointer-events-auto mx-auto w-full max-w-3xl px-3 pb-2 md:px-8 md:pb-5"><AskBar /></div>
          <nav className="pointer-events-auto grid grid-cols-4 border-t border-line bg-ink/95 pb-[max(env(safe-area-inset-bottom),6px)] pt-1.5 backdrop-blur md:hidden">
            {NAV.map((n) => (
              <button key={n.key} onClick={() => go(n.key)} aria-current={active === n.key ? "page" : undefined}
                className={`relative flex flex-col items-center gap-0.5 py-1 text-[11px] ${active === n.key ? "text-fg" : "text-faint"}`}>
                <n.icon className="h-5 w-5" />{n.label}
                {n.key === "alerts" && unseen > 0 && <span className="num absolute right-[28%] top-0 rounded-full bg-down px-1 text-[9.5px] font-bold text-ink">{unseen}</span>}
              </button>
            ))}
          </nav>
        </div>
      </div>
    </div>
  );
}

function Wordmark() {
  return (
    <button onClick={() => go("brief")} className="flex items-baseline gap-2 px-1" aria-label="FINN home">
      <span className="w-wide text-[19px] font-extrabold tracking-tight">FINN</span>
      <span className="hidden text-[11.5px] text-faint sm:inline md:hidden lg:inline">Financial Investment Agent</span>
    </button>
  );
}

function ModeNote({ mode }: { mode: any }) {
  if (!mode) return null;
  const demo = mode.mode === "demo";
  return (
    <div className={`rounded border px-3 py-2 text-[12px] leading-snug ${demo ? "border-warn/30 text-warn/90" : "border-line text-dim"}`}>
      <div className="font-semibold">{demo ? "Illustrative demo data" : "Live end-of-day data"}</div>
      <div className="text-dim">As of {mode.as_of}. {demo ? "Synthetic figures; not real filings." : "Refreshed after market close."}</div>
    </div>
  );
}
