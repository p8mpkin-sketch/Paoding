// 总览（工作台设计 §1 模块一）：题目列表的纯函数排版。只计数服务端给的终态与时刻，不推断等级或“阶段”。
import type { ProblemItem, Terminal } from "../api/types";

/** 进行中：未关的题，按开题先后。 */
export const runningOf = (items: ProblemItem[]) => items.filter((p) => !p.closed);
/** 回收站里的（含过期的）不进总览的最近列表与趋势；读数照算（软删不动账）。 */
const kept = (p: ProblemItem) => p.shelf !== "trash" && p.shelf !== "purged";

/** 最近完成：已关的题，后关的在前；filter 为空即全部。 */
export function recentOf(items: ProblemItem[], filter: Terminal | null): ProblemItem[] {
  return items
    .filter((p) => p.closed && kept(p) && (filter === null || p.terminal === filter))
    .sort((a, b) => (b.closed_seq ?? 0) - (a.closed_seq ?? 0));
}

export function terminalCounts(items: ProblemItem[]): Record<Terminal, number> {
  const c: Record<Terminal, number> = { solved: 0, accepted: 0, delivered: 0, unsolved: 0 };
  for (const p of items) if (p.closed && p.terminal) c[p.terminal]++;
  return c;
}

/** 在途租约按种类计数，按种类首次出现的先后（服务端已按 issued_seq 排好）。 */
export function leaseKinds(p: ProblemItem): { kind: string; n: number }[] {
  const out: { kind: string; n: number }[] = [];
  for (const l of p.active) {
    const x = out.find((o) => o.kind === l.kind);
    if (x) x.n++;
    else out.push({ kind: l.kind, n: 1 });
  }
  return out;
}

/** 本机时区的日界：返回某个毫秒时刻所在那天 0 点的毫秒数。 */
export function dayStart(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export type DayBucket = { day: number; closed: number; solved: number };

/**
 * 最近 days 天（含今天）按关题日计数。closed_ts 为 null 的已关题（老图服务）不计入。
 * 成功率 = solved ÷ 当天已关题数（异议 web-workbench 第 6 条）；当天没有关题时为 null。
 */
export function dailySeries(items: ProblemItem[], now: number, days = 7): DayBucket[] {
  const today = dayStart(now);
  const starts: number[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    starts.push(d.getTime());
  }
  const out = starts.map((day) => ({ day, closed: 0, solved: 0 }));
  for (const p of items) {
    if (!p.closed || p.closed_ts === null) continue;
    const i = starts.indexOf(dayStart(p.closed_ts));
    if (i < 0) continue;
    out[i].closed++;
    if (p.terminal === "solved") out[i].solved++;
  }
  return out;
}

export const solvedToday = (items: ProblemItem[], now: number) =>
  items.filter((p) => p.terminal === "solved" && p.closed_ts !== null && dayStart(p.closed_ts) === dayStart(now)).length;

export const ratio = (b: DayBucket): number | null => (b.closed ? b.solved / b.closed : null);

/** 墙钟“已用 / 上限”，按分钟。 */
export const minutes = (s: number) => (s < 60 ? `${s} 秒` : s < 3600 ? `${Math.floor(s / 60)} 分` : `${Math.floor(s / 3600)} 时 ${Math.floor((s % 3600) / 60)} 分`);
