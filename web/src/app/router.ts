// 极小的路由：路径 + 查询串，状态全在 URL 里。
// 题内 URL：/p/<pid>?as_of=<seq>&node=<id>（HMI 设计 §10.4）。不带 as_of 即链头实时。
import { useSyncExternalStore } from "react";

/** 题库筛选：都在 URL 里，空串即不筛。 */
export type BankFilter = { q: string; terminal: string; judge: string };
export const NO_FILTER: BankFilter = { q: "", terminal: "", judge: "" };

export type Route =
  /** 首页就是新建任务的输入框（v5 第三期）；今日看板挪到 /today。 */
  | { page: "home" }
  | { page: "today" }
  | ({ page: "problems" } & Partial<BankFilter>)
  /** /new 是一句话开题的输入框；/new/advanced 是四步向导（高级模式，克隆也到这里）。 */
  | { page: "new"; advanced?: boolean; from?: string }
  | { page: "import" }
  /** 从已登记的外部平台导入（external-verdict §5.8）；task 给了即直接领那一题。 */
  | { page: "platform"; id?: string }
  | { page: "readings" }
  | { page: "inbox" }
  | { page: "settings" }
  | { page: "models" }
  | { page: "knowledge"; tab: "sources" | "memory" }
  | { page: "problem"; pid: string; asOf: number | null; node: string | null };

export function parseRoute(pathname: string, search: string): Route {
  const q = new URLSearchParams(search);
  const m = pathname.match(/^\/p\/([^/]+)\/?$/);
  if (m) {
    const raw = q.get("as_of");
    const n = raw === null ? NaN : Number(raw);
    return { page: "problem", pid: decodeURIComponent(m[1]), asOf: Number.isInteger(n) && n > 0 ? n : null, node: q.get("node") };
  }
  if (pathname === "/new/advanced") return q.get("from") ? { page: "new", advanced: true, from: q.get("from")! } : { page: "new", advanced: true };
  if (pathname === "/new") return q.get("from") ? { page: "new", advanced: true, from: q.get("from")! } : { page: "new" };
  if (pathname === "/import") return { page: "import" };
  if (pathname === "/import/platform") return q.get("id") ? { page: "platform", id: q.get("id")! } : { page: "platform" };
  if (pathname === "/today") return { page: "today" };
  if (pathname === "/readings") return { page: "readings" };
  if (pathname === "/inbox") return { page: "inbox" };
  if (pathname === "/settings") return { page: "settings" };
  if (pathname === "/models") return { page: "models" };
  if (pathname === "/knowledge") return { page: "knowledge", tab: "sources" };
  if (pathname === "/knowledge/memory") return { page: "knowledge", tab: "memory" };
  if (pathname === "/tasks") return { page: "problems", q: q.get("q") ?? "", terminal: q.get("terminal") ?? "", judge: q.get("judge") ?? "" };
  if (pathname === "/problems") return { page: "problems", q: q.get("q") ?? "", terminal: q.get("terminal") ?? "", judge: q.get("judge") ?? "" };
  return { page: "home" };
}

export function hrefOf(r: Route): string {
  switch (r.page) {
    case "home": return "/";
    case "today": return "/today";
    case "problems": {
      const q = new URLSearchParams();
      for (const k of ["q", "terminal", "judge"] as const) if (r[k]) q.set(k, r[k]!);
      const s = q.toString();
      return `/problems${s ? `?${s}` : ""}`;
    }
    case "new": return r.advanced || r.from ? `/new/advanced${r.from ? `?from=${encodeURIComponent(r.from)}` : ""}` : "/new";
    case "import": return "/import";
    case "platform": return `/import/platform${r.id ? `?id=${encodeURIComponent(r.id)}` : ""}`;
    case "readings": return "/readings";
    case "inbox": return "/inbox";
    case "settings": return "/settings";
    case "models": return "/models";
    case "knowledge": return r.tab === "memory" ? "/knowledge/memory" : "/knowledge";
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
