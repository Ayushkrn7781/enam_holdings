import { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, BookOpen, Briefcase, Newspaper, Settings as Gear } from "lucide-react";
import { api } from "./lib/api";
import { href, useRoute } from "./lib/router";
import { AskContext } from "./components/ui";
import { AskBar, AskSheet } from "./components/Ask";
import Brief from "./pages/Brief";
import SignalDetail from "./pages/SignalDetail";
import Portfolio from "./pages/Portfolio";
import Research from "./pages/Research";
import Alerts from "./pages/Alerts";
import Settings from "./pages/Settings";

const TABS = [
  { key: "brief", label: "Brief", icon: Newspaper },
  { key: "portfolio", label: "Portfolio", icon: Briefcase },
  { key: "research", label: "Research", icon: BookOpen },
  { key: "alerts", label: "Alerts", icon: Bell },
];

export default function App() {
  const route = useRoute();
  const [ticker, setTicker] = useState<string | null>(null);
  const [askOpen, setAskOpen] = useState(false);
  const [seed, setSeed] = useState<{ q?: string; n: number }>({ n: 0 });
  const [mode, setMode] = useState<string | null>(null);
  const [unseen, setUnseen] = useState(0);

  const refreshMeta = useCallback(() => {
    api.status().then((s) => setMode(s.mode)).catch(() => {});
    api.alerts().then((a) => setUnseen(a.unseen)).catch(() => {});
  }, []);
  useEffect(() => { refreshMeta(); }, [refreshMeta, route.name]);

  useEffect(() => {
    if ((route.name === "research") && route.params[0]) setTicker(route.params[0].toUpperCase());
  }, [route.name, route.params]);

  const open = useCallback((q?: string, t?: string) => {
    if (t) setTicker(t);
    setSeed((s) => ({ q, n: s.n + 1 }));
    setAskOpen(true);
  }, []);
  const ctx = useMemo(() => ({ ticker, setTicker, open }), [ticker, open]);

  const active = route.name === "signal" ? "brief" : route.name;
  let page;
  switch (route.name) {
    case "signal": page = <SignalDetail id={Number(route.params[0])} />; break;
    case "portfolio": page = <Portfolio />; break;
    case "research": page = <Research ticker={route.params[0]?.toUpperCase()} tab={route.params[1]} />; break;
    case "alerts": page = <Alerts onSeen={() => setUnseen(0)} />; break;
    case "settings": page = <Settings onReset={refreshMeta} />; break;
    default: page = <Brief />;
  }

  return (
    <AskContext.Provider value={ctx}>
      <div className="min-h-screen md:flex">
        {/* desktop sidebar */}
        <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line px-3 py-5 md:flex">
          <a href={href("brief")} className="w-wide px-2 text-[22px] font-extrabold tracking-tight">FINN</a>
          <nav className="mt-6 space-y-0.5" aria-label="Main">
            {[...TABS, { key: "settings", label: "Settings", icon: Gear }].map((t) => (
              <a key={t.key} href={href(t.key)} aria-current={active === t.key ? "page" : undefined}
                className={`flex items-center gap-2.5 rounded px-2 py-2 text-[14px] ${active === t.key ? "bg-raised text-fg" : "text-dim hover:text-fg"}`}>
                <t.icon size={17} /> {t.label}
                {t.key === "alerts" && unseen > 0 && <span className="w-cond ml-auto rounded-full bg-down px-1.5 text-[11px] font-semibold text-ink">{unseen}</span>}
              </a>
            ))}
          </nav>
          <div className="mt-auto px-2 text-[12px] leading-relaxed text-faint">
            {mode === "demo" ? <><span className="text-warn">Demo data.</span> Synthetic figures and fictional people, frozen at 3 Nov 2026.</> :
              mode === "live" ? "Live data from NSE, screener.in and Yahoo Finance. End-of-day." : null}
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          {/* mobile top bar */}
          <header className="sticky top-0 z-30 flex items-center gap-2 border-b border-line bg-ink/95 px-4 py-2.5 backdrop-blur md:hidden">
            <a href={href("brief")} className="w-wide text-[19px] font-extrabold tracking-tight">FINN</a>
            {mode === "demo" && <a href={href("settings")} className="rounded border border-warn/40 px-1.5 py-[1px] text-[11px] text-warn">Demo data</a>}
            <a href={href("settings")} aria-label="Settings" className="ml-auto rounded p-1.5 text-dim hover:text-fg"><Gear size={19} /></a>
          </header>

          <main className="mx-auto max-w-[920px] px-4 pb-40 pt-4 md:px-8 md:pb-28 md:pt-8">{page}</main>

          {/* docked Ask FINN + mobile tabs */}
          <div className="fixed inset-x-0 bottom-0 z-40 md:left-56">
            <div className="mx-auto max-w-[920px] px-3 pb-2 md:px-8 md:pb-5">
              <AskBar ticker={ticker} onOpen={() => open()} />
            </div>
            <nav aria-label="Tabs" className="flex border-t border-line bg-ink/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
              {TABS.map((t) => (
                <a key={t.key} href={href(t.key)} aria-current={active === t.key ? "page" : undefined}
                  className={`relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${active === t.key ? "text-fg" : "text-faint"}`}>
                  <t.icon size={20} strokeWidth={active === t.key ? 2.2 : 1.8} />
                  {t.label}
                  {t.key === "alerts" && unseen > 0 && <span className="w-cond absolute right-[calc(50%-20px)] top-1 rounded-full bg-down px-1 text-[10px] font-semibold text-ink">{unseen}</span>}
                </a>
              ))}
            </nav>
          </div>
        </div>
      </div>
      <AskSheet open={askOpen} onClose={() => setAskOpen(false)} ticker={ticker} setTicker={setTicker} seed={seed} />
    </AskContext.Provider>
  );
}
