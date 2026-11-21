// 总览（工作台设计 §1 模块一）：题目列表的纯函数排版。只计数服务端给的终态与时刻，不推断等级或“阶段”。
import type { BudgetPoint, ProblemItem, Terminal } from "../api/types";

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

// —— v6（今日、读数）：花费序列的纯算术（docs/design/pages-v6 §1） ——

/** 一个任务的花费序列拆成“每一点比前一点多花的钱”，各带时刻；没有 ts 的点记在 untimed。 */
export function spendDeltas(points: BudgetPoint[]): { ts: number; usd: number; tokens: number }[] {
  const out: { ts: number; usd: number; tokens: number }[] = [];
  let pu = 0, pt = 0;
  for (const p of points) {
    if (p.ts !== null) out.push({ ts: p.ts, usd: p.usd_milli - pu, tokens: p.tokens - pt });
    pu = p.usd_milli; pt = p.tokens;
  }
  return out;
}

/** 从 since（毫秒，含）起各任务一共花了多少；以及有多少钱落在没有时刻的点上（不计入，旁注）。 */
export function spendSince(series: BudgetPoint[][], since: number): { usd: number; tasks: number; untimed: number } {
  let usd = 0, tasks = 0, untimed = 0;
  for (const pts of series) {
    const d = spendDeltas(pts).filter((x) => x.ts >= since).reduce((a, x) => a + x.usd, 0);
    if (d > 0) { usd += d; tasks++; }
    const timed = spendDeltas(pts).reduce((a, x) => a + x.usd, 0);
    untimed += (pts.at(-1)?.usd_milli ?? 0) - timed;
  }
  return { usd, tasks, untimed };
}

export type SpendDay = { day: number; usd: number; tokens: number; tasks: number };

/** 最近 days 天（含今天）按天合计的花费、令牌与当天有花费的任务数。 */
export function spendByDay(series: BudgetPoint[][], now: number, days = 7): SpendDay[] {
  const today = dayStart(now);
  const starts: number[] = [];
  for (let i = days - 1; i >= 0; i--) { const d = new Date(today); d.setDate(d.getDate() - i); starts.push(d.getTime()); }
  const out = starts.map((day) => ({ day, usd: 0, tokens: 0, tasks: 0 }));
  for (const pts of series) {
    const hit = new Set<number>();
    for (const x of spendDeltas(pts)) {
      const i = starts.indexOf(dayStart(x.ts));
      if (i < 0) continue;
      out[i].usd += x.usd; out[i].tokens += x.tokens;
      if (x.usd > 0) hit.add(i);
    }
    for (const i of hit) out[i].tasks++;
  }
  return out;
}

/** 已结束任务的用时分桶（秒）。 */
export const WALL_BUCKETS: { label: string; lo: number; hi: number }[] = [
  { label: "1 分以内", lo: 0, hi: 60 }, { label: "1–5 分", lo: 60, hi: 300 }, { label: "5–15 分", lo: 300, hi: 900 },
  { label: "15–60 分", lo: 900, hi: 3600 }, { label: "1 小时以上", lo: 3600, hi: Infinity },
];
export function wallHistogram(items: ProblemItem[]): number[] {
  const out = WALL_BUCKETS.map(() => 0);
  for (const p of items) if (p.closed) { const i = WALL_BUCKETS.findIndex((b) => p.wall.elapsed_s >= b.lo && p.wall.elapsed_s < b.hi); if (i >= 0) out[i]++; }
  return out;
}

/** 已结束里“做成了”的比例：判定通过、已验收、已交付 ÷ 已结束；没有已结束的为 null。 */
export function doneRate(items: ProblemItem[]): number | null {
  const ended = items.filter((p) => p.closed);
  if (!ended.length) return null;
  return ended.filter((p) => p.terminal === "solved" || p.terminal === "accepted" || p.terminal === "delivered").length / ended.length;
}
