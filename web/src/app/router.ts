// 极小的路由：路径 + 查询串，状态全在 URL 里。
// 题内 URL：/p/<pid>?as_of=<seq>&node=<id>（HMI 设计 §10.4）。不带 as_of 即链头实时。
import { useSyncExternalStore } from "react";

export type Route =
  | { page: "problems" }
  | { page: "new" }
  | { page: "readings" }
  | { page: "problem"; pid: string; asOf: number | null; node: string | null };

export function parseRoute(pathname: string, search: string): Route {
  const q = new URLSearchParams(search);
  const m = pathname.match(/^\/p\/([^/]+)\/?$/);
  if (m) {
    const raw = q.get("as_of");
    const n = raw === null ? NaN : Number(raw);
    return { page: "problem", pid: decodeURIComponent(m[1]), asOf: Number.isInteger(n) && n > 0 ? n : null, node: q.get("node") };
  }
  if (pathname === "/new") return { page: "new" };
  if (pathname === "/readings") return { page: "readings" };
  return { page: "problems" };
}

export function hrefOf(r: Route): string {
  switch (r.page) {
    case "problems": return "/";
    case "new": return "/new";
    case "readings": return "/readings";
    case "problem": {
      const q = new URLSearchParams();
      if (r.asOf !== null) q.set("as_of", String(r.asOf));
      if (r.node) q.set("node", r.node);
      const s = q.toString();
      return `/p/${encodeURIComponent(r.pid)}${s ? `?${s}` : ""}`;
    }
  }
}

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((fn) => fn());
if (typeof window !== "undefined") window.addEventListener("popstate", notify);

export function navigate(r: Route, replace = false): void {
  const href = hrefOf(r);
  if (replace) window.history.replaceState(null, "", href);
  else window.history.pushState(null, "", href);
  notify();
}

const key = () => window.location.pathname + window.location.search;
export function useRoute(): Route {
  const k = useSyncExternalStore((fn) => (listeners.add(fn), () => listeners.delete(fn)), key);
  const i = k.indexOf("?");
  return parseRoute(i < 0 ? k : k.slice(0, i), i < 0 ? "" : k.slice(i));
}
