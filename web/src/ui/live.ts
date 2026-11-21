// 今日、任务库、读数共用的读取（docs/design/pages-v6 §1）：只按需读、只排版。
// - 待办：human_todo > 0 的任务读 /work 的 human 项；
// - 智能体此刻在做什么：在跑任务读 /status 的在途会话，再读每个会话活动的摘要（after 取极大，只要 now/last_say/计数，不拉条目）；
// - 花费：/budget 与 /budget/series，按任务读一次，链头变了才重读。
import { useEffect, useRef, useState } from "react";
import type { ActCall, ActSay } from "../api/activity-types";
import type { BudgetResponse, BudgetSeriesResponse, HumanWorkItem, ProblemItem } from "../api/types";
import { useServices } from "../app/context";

const SUMMARY_ONLY = 1_000_000_000; // 活动端点的游标：比任何序号都大，应答里只剩摘要
const NO_ACTIVITY = new Set(["judge", "rejudge"]);
export const AGENT_POLL_MS = 5000;
export const MAX_LIVE = 12;

/** 有待办的任务，每件待办的种类与目标（服务端给的 why）。 */
export function useTodos(items: ProblemItem[] | null, head: number | null): Record<string, HumanWorkItem[]> {
  const { api } = useServices();
  const [out, setOut] = useState<Record<string, HumanWorkItem[]>>({});
  const ps = (items ?? []).filter((p) => !p.closed && p.human_todo > 0);
  const key = `${head}|${ps.map((p) => `${p.id}:${p.human_todo}`).join(",")}`;
  useEffect(() => {
    let live = true;
    void Promise.all(ps.map((p) => api.work(p.id).then((w) => [p.id, w.items.filter((x): x is HumanWorkItem => x.kind === "human")] as const, () => null)))
      .then((rs) => { if (live) setOut(Object.fromEntries(rs.filter((r): r is readonly [string, HumanWorkItem[]] => r !== null))); });
    return () => { live = false; };
  }, [api, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return out;
}

export type Agent = {
  leases: { id: string; kind: string }[];
  /** 正在做的工具调用（最近开始的那个会话的）；没有为 null。 */
  now: (ActCall & { lease: string }) | null;
  say: ActSay | null;
  turns: number;
  calls: number;
  error: string | null;
};

/** 在跑的任务此刻在做什么：每 5 秒读一次（页面不可见时跳过），最多读前 MAX_LIVE 个在跑的任务。 */
export function useAgents(running: ProblemItem[]): Record<string, Agent> {
  const { api } = useServices();
  const [out, setOut] = useState<Record<string, Agent>>({});
  const ids = running.slice(0, MAX_LIVE).map((p) => p.id);
  const key = ids.join(",");
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    const pull = async () => {
      if (globalThis.document?.visibilityState === "hidden") return;
      const rows = await Promise.all(ids.map(async (pid): Promise<readonly [string, Agent]> => {
        try {
          const st = await api.status(pid);
          const ls = st.leases.filter((l) => l.active && !NO_ACTIVITY.has(l.kind)).map((l) => ({ id: l.id, kind: l.kind }));
          const docs = await Promise.all(ls.map((l) => api.activity(l.id, SUMMARY_ONLY).then((d) => ({ l, d }), () => null)));
          const ok = docs.filter((x): x is NonNullable<typeof x> => x !== null);
          const doing = ok.filter((x) => x.d.now).at(-1);
          const said = ok.filter((x) => x.d.last_say).at(-1);
          return [pid, {
            leases: ls, now: doing ? { ...doing.d.now!, lease: doing.l.id } : null, say: said?.d.last_say ?? null,
            turns: ok.reduce((a, x) => a + (x.d.turns ?? 0), 0), calls: ok.reduce((a, x) => a + x.d.calls, 0), error: null,
          }] as const;
        } catch (e) {
          return [pid, { leases: [], now: null, say: null, turns: 0, calls: 0, error: (e as Error).message }] as const;
        }
      }));
      if (alive.current) setOut(Object.fromEntries(rows));
    };
    void pull();
    const t = setInterval(() => void pull(), AGENT_POLL_MS);
    return () => { alive.current = false; clearInterval(t); };
  }, [api, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return out;
}

export const MAX_COST_READS = 200;

/** 各任务的预算与花费序列（读数、今日右栏）。链头变了才重读；任务多于 MAX_COST_READS 时只读最近的。 */
export function useCosts(items: ProblemItem[] | null, head: number | null, want: { budget?: boolean; series?: boolean } = { budget: true, series: true }): {
  budgets: Record<string, BudgetResponse>; series: Record<string, BudgetSeriesResponse>; loading: boolean; capped: boolean;
} {
  const { api } = useServices();
  const [st, setSt] = useState<{ budgets: Record<string, BudgetResponse>; series: Record<string, BudgetSeriesResponse>; loading: boolean }>({ budgets: {}, series: {}, loading: true });
  const xs = [...(items ?? [])].sort((a, b) => b.opened_seq - a.opened_seq).slice(0, MAX_COST_READS);
  const key = `${head}|${xs.length}|${want.budget ? 1 : 0}${want.series ? 1 : 0}`;
  useEffect(() => {
    if (!items) return;
    let live = true;
    void Promise.all(xs.map(async (p) => {
      const [b, s] = await Promise.all([
        want.budget ? api.budget(p.id).catch(() => null) : Promise.resolve(null),
        want.series ? api.budgetSeries(p.id).catch(() => null) : Promise.resolve(null),
      ]);
      return { id: p.id, b, s };
    })).then((rs) => {
      if (!live) return;
      setSt({
        budgets: Object.fromEntries(rs.filter((r) => r.b).map((r) => [r.id, r.b!])),
        series: Object.fromEntries(rs.filter((r) => r.s).map((r) => [r.id, r.s!])),
        loading: false,
      });
    });
    return () => { live = false; };
  }, [api, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...st, capped: (items?.length ?? 0) > MAX_COST_READS };
}
