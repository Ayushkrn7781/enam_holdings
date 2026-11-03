import { useEffect, useState } from "react";

/** Tiny hash router: #/brief, #/signal/12, #/research/DIXON/guidance ... — deep-linkable, no server config. */
export function useRoute() {
  const parse = () => (window.location.hash.replace(/^#\/?/, "") || "brief").split("/").map(decodeURIComponent);
  const [parts, setParts] = useState<string[]>(parse);
  useEffect(() => {
    const on = () => { setParts(parse()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}
export const go = (...parts: (string | number)[]) => { window.location.hash = "/" + parts.map((p) => encodeURIComponent(String(p))).join("/"); };
export const back = () => (window.history.length > 1 ? window.history.back() : go("brief"));
