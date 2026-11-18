// 视图模型：view(as_of) 的纯函数（HMI 设计 §3.9）。
// 入参全部是图服务对同一序号给出的投影；这里只做排版前的整理：
// 不读本机时钟（时间取事件的 ts），排序只用 seq 与 id，不算等级，不解释事件体的语义。
import type {
  Badge, BudgetResponse, GraphView, IntentState, Level, Predicate, Profile, ProfileOverride, Risk, ScopeRule,
  StatusView, Tagged, Terminal, WireTick, WorkItem, WorkView,
} from "../api/types";
import { layout, type Layout } from "./layout";
import { levelWord } from "./levels";
import { ticksOf, type Tick } from "./ticks";

export type NodeRow = {
  id: string;
  kind: "fact" | "intent";
  created_seq: number;
  level: Level | null;
  /** 等级词表里的说法；E3、E3d、X 带判官名。 */
  levelWord: string;
  state: IntentState | null;
  flags: { disputed: boolean; stale: boolean; unstable: boolean };
  /** 判据卡：带判据的对象才有。缩略徽章取它的 label（判官名@版本）。 */
  predicate: Predicate | null;
  /** 谓词摘要：判官、规格引用、expect。节点行首显示它，标题退到第二位。 */
  predicateText: string | null;
  claim_type: "observation" | "inference" | null;
  risk: Risk | null;
  title: Tagged;
  summary: Tagged;
  premises: string[];
  grounds: string[];
  expected_gain: Tagged<number> | null;
};
export type HintRow = { id: string; created_seq: number; ts: number | null; author: string; text: Tagged; about: string | null; closed: boolean };
export type FrontierGroup = { key: "hints" | "disputed" | "human" | "intents" | "premises" | "facts"; title: string; ids: string[] };
export type TodoItem = Extract<WorkItem, { kind: "human" }>;
export type BudgetVM = {
  spent: number; reserved: number; cap: number;
  /** 千分比，整数，避免浮点在两次渲染之间出现不同的舍入。 */
  spentPermille: number; reservedPermille: number;
  verifySpent: number; verifyCap: number;
  wallSpent: number; wallCap: number;
  byKind: { kind: string; usd_milli: number }[];
  marks: number[];
  markLines: number[];
  review: boolean;
};
/** 在途会话：status.leases 里 active 的那些。since_ms 用事件时钟（签发那条事件的 ts 到本序号的 now_ts），不读本机时钟。 */
export type SessionRow = { id: string; kind: string; target: string | null; holder: string; issued_seq: number; reserve_usd_milli: number; since_ms: number | null };
export type ViewModel = {
  pid: string;
  seq: number;
  /** 图服务给的该序号的状态哈希；与视图模型一一对应（HT-10）。 */
  state_hash: string | null;
  title: Tagged;
  closed: boolean;
  terminal: Terminal | null;
  profile: Profile;
  derivedProfile: Profile;
  profileOverrides: ProfileOverride[];
  scope: ScopeRule[];
  goal: { predicate: Predicate; badge: Badge; levelWord: string; statement: Tagged; accept: "judge" | "human" };
  rows: NodeRow[];
  hints: HintRow[];
  frontier: FrontierGroup[];
  todo: TodoItem[];
  sessions: SessionRow[];
  budget: BudgetVM;
  ticks: Tick[];
  layout: Layout;
};

export type Projections = { status: StatusView; view: GraphView; budget: BudgetResponse; work: WorkView };

const FRONTIER_TITLES: Record<FrontierGroup["key"], string> = {
  hints: "活跃 Hint",
  disputed: "争议与不稳定的节点",
  human: "待人处理",
  intents: "未结束的 Intent",
  premises: "未结束 Intent 的前提",
  facts: "未到终态的论断",
};
const FRONTIER_ORDER = Object.keys(FRONTIER_TITLES) as FrontierGroup["key"][];

export function predicateText(p: Predicate | null): string | null {
  if (!p) return null;
  const parts = [p.label];
  if (p.spec_ref) parts.push(`规格 ${p.spec_ref}`);
  const keys = Object.keys(p.expect ?? {}).sort();
  if (keys.length) parts.push(`expect ${keys.map((k) => `${k}=${JSON.stringify(p.expect[k])}`).join(" ")}`);
  if (p.sealed?.length) parts.push(`${p.sealed.length} 项 vault 引用`);
  return parts.join(" ｜ ");
}

const permille = (part: number, whole: number) => (whole > 0 ? Math.min(1000, Math.floor((part * 1000) / whole)) : 0);
const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** 四份投影必须出自同一序号，否则拒绝拼装（宁可不显示，也不显示拼出来的状态）。 */
export function sameSeq(p: Projections): boolean {
  return p.status.as_of === p.view.as_of && p.view.as_of === p.budget.as_of && p.budget.as_of === p.work.as_of;
}

export function buildViewModel(pid: string, p: Projections, ticks: readonly WireTick[]): ViewModel {
  if (!sameSeq(p)) throw new Error("投影不在同一序号");
  const { status, view, budget, work } = p;
  const seq = status.as_of;

  const rows: NodeRow[] = [
    ...status.facts.map((f): NodeRow => ({
      id: f.id, kind: "fact", created_seq: f.seq, level: f.level, levelWord: levelWord(f.level, f.level_word, f.predicate),
      state: null, flags: { disputed: f.disputed, stale: f.stale, unstable: f.unstable },
      predicate: f.predicate, predicateText: predicateText(f.predicate), claim_type: f.claim_type, risk: null,
      title: f.title, summary: f.summary, premises: [...f.premises], grounds: [...f.grounds], expected_gain: null,
    })),
    ...status.intents.map((i): NodeRow => ({
      id: i.id, kind: "intent", created_seq: i.seq, level: i.level, levelWord: levelWord(i.level, i.level_word, i.predicate),
      state: i.status, flags: { disputed: false, stale: false, unstable: false },
      predicate: i.predicate, predicateText: predicateText(i.predicate), claim_type: null, risk: i.risk,
      title: i.title, summary: i.summary, premises: [...i.premises], grounds: [], expected_gain: i.expected_gain,
    })),
  ].sort((a, b) => a.created_seq - b.created_seq || cmp(a.id, b.id));

  const hints: HintRow[] = [...status.hints]
    .sort((a, b) => a.seq - b.seq || cmp(a.id, b.id))
    .map((h) => ({ id: h.id, created_seq: h.seq, ts: h.ts ?? null, author: h.author, text: h.text, about: h.about, closed: h.closed }));

  const seqOf = new Map<string, number>([...rows.map((r) => [r.id, r.created_seq] as const), ...hints.map((h) => [h.id, h.created_seq] as const)]);
  const idsOf = (key: FrontierGroup["key"]): string[] => (key === "human" ? view.frontier.human.map((w) => w.target) : view.frontier[key]);
  const frontier: FrontierGroup[] = FRONTIER_ORDER.map((key) => ({
    key,
    title: FRONTIER_TITLES[key],
    ids: [...new Set(idsOf(key))].filter((id) => seqOf.has(id)).sort((a, b) => seqOf.get(a)! - seqOf.get(b)! || cmp(a, b)),
  }));

  const todo = work.items
    .filter((w): w is TodoItem => w.kind === "human")
    .sort((a, b) => cmp(a.why, b.why) || cmp(a.target, b.target));

  const tsOf = new Map(ticks.map((t) => [t.seq, t.ts]));
  const now = status.problem.now_ts;
  const sessions: SessionRow[] = status.leases
    .filter((l) => l.active)
    .sort((a, b) => a.issued_seq - b.issued_seq || cmp(a.id, b.id))
    .map((l) => {
      const at = tsOf.get(l.issued_seq);
      return { id: l.id, kind: l.kind, target: l.target ?? null, holder: l.holder, issued_seq: l.issued_seq, reserve_usd_milli: l.reserve.usd_milli, since_ms: at === undefined ? null : Math.max(0, now - at) };
    });

  const cap = budget.cap.usd_milli ?? 0;
  const budgetVM: BudgetVM = {
    spent: budget.spent.usd_milli, reserved: budget.reserved.usd_milli, cap,
    spentPermille: permille(budget.spent.usd_milli, cap),
    reservedPermille: permille(budget.reserved.usd_milli, cap),
    verifySpent: budget.verify_spent.usd_milli, verifyCap: Math.floor(cap * budget.verify_share),
    wallSpent: budget.wall.elapsed_s, wallCap: budget.wall.cap_s,
    byKind: Object.keys(budget.by_kind).sort().map((kind) => ({ kind, usd_milli: budget.by_kind[kind].usd_milli })),
    marks: [...budget.marks].sort((a, b) => a - b),
    markLines: [...budget.mark_lines].sort((a, b) => a - b),
    review: budget.review,
  };

  const g = status.goal;
  return {
    pid, seq, state_hash: status.state_hash ?? null,
    title: status.problem.title, closed: status.problem.closed, terminal: status.problem.terminal,
    profile: status.problem.profile, derivedProfile: status.problem.derived_profile, profileOverrides: status.problem.profile_overrides,
    scope: status.problem.scope,
    goal: { predicate: g.predicate, badge: status.problem.terminal_badge, levelWord: levelWord(g.predicate.level, g.predicate.level_word, g.predicate), statement: g.statement, accept: g.accept },
    rows, hints, frontier, todo, sessions, budget: budgetVM,
    ticks: ticksOf(ticks, seq),
    layout: layout({
      nodes: rows.map((r) => ({ id: r.id, kind: r.kind, created_seq: r.created_seq, premises: r.premises })),
      hints: hints.map((h) => ({ id: h.id, created_seq: h.created_seq, about: h.about ?? undefined })),
    }),
  };
}

/**
 * 图的聚焦与高亮（工作台设计 §5）：只沿服务端给的 premises 边取闭包，只改样式，不改布局坐标（HT-14）。
 * chain：start 及其全部上游（支撑它的那条链）；focus：再加上全部下游（以它为前提的节点）。
 */
export function emphasisOf(rows: readonly NodeRow[], start: string, mode: "chain" | "focus"): Set<string> {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const out = new Set<string>([start, ...premiseChain(byId, start).map((x) => x.row.id)]);
  if (mode === "focus") {
    const users = new Map<string, string[]>();
    for (const r of rows) for (const p of r.premises) users.set(p, [...(users.get(p) ?? []), r.id]);
    const stack = [start];
    while (stack.length) {
      for (const u of users.get(stack.pop()!) ?? []) if (!out.has(u)) { out.add(u); stack.push(u); }
    }
  }
  return out;
}

/** 按等级分组（列表视图的另一种排法）：顺序固定 X、E3、E3d、E2、E1、E0、无等级；组内按创建序号。 */
export const LEVEL_ORDER = ["X", "E3", "E3d", "E2", "E1", "E0", null] as const;
export function byLevel(rows: readonly NodeRow[]): { level: Level | null; rows: NodeRow[] }[] {
  return LEVEL_ORDER.map((level) => ({ level, rows: rows.filter((r) => r.level === level) })).filter((g) => g.rows.length > 0);
}

/**
 * 沿前提链展开（H6）：从一个节点出发，按广度列出它的全部上游节点。只走结构（premises），不算任何等级。
 * 用来在检视里把上游的 grounds 摆在两次点击之内，并判断整条链上有没有登记过 Artifact。
 */
export function premiseChain(rows: ReadonlyMap<string, NodeRow>, start: string): { row: NodeRow; depth: number }[] {
  const out: { row: NodeRow; depth: number }[] = [];
  const seen = new Set([start]);
  let layer = rows.get(start)?.premises ?? [];
  for (let depth = 1; layer.length > 0; depth++) {
    const next: string[] = [];
    for (const id of layer) {
      if (seen.has(id)) continue;
      seen.add(id);
      const row = rows.get(id);
      if (!row) continue;
      out.push({ row, depth });
      next.push(...row.premises);
    }
    layer = next;
  }
  return out;
}
