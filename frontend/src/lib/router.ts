// Hash routing: #/brief, #/signal/12, #/research/TITAN/guidance
import { useEffect, useState } from "react";

export interface Route { name: string; params: string[] }

export function parseHash(h: string = window.location.hash): Route {
  const parts = h.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  return { name: parts[0] || "brief", params: parts.slice(1) };
}

export function useRoute(): Route {
  const [r, setR] = useState(parseHash());
  useEffect(() => {
    const on = () => {
      setR(parseHash());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r;
}

export function go(path: string) {
  window.location.hash = path.startsWith("#") ? path : `#/${path.replace(/^\//, "")}`;
}

export const href = (path: string) => `#/${path.replace(/^\//, "")}`;
