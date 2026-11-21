// 任务页“过程”与“结构”的数据：把本题的事件账与每个会话的活动合成一条轨迹（任务详情 v6 §2.2、§2.3）。
// 纯函数，只排版两路数据里已有的字段：不内嵌 reducer，不推导图的状态。会话起止、结局、花费都取事件体原样；
// 模型调用的 token 取活动条目 turn（CLI 流自带的 usage），花费取端点代理的 cost 事件，两者按会话内序号对齐，对不上就各自单列。
import type { ActCall, ActItem, ActResult, ActThink, ActTurn } from "../api/activity-types";
import type { Event } from "../api/types";

export type Kind =
  | "think" | "turn" | "cost" | "say" | "call" | "end"
  | "session" | "file" | "plan" | "human" | "scope" | "deliver" | "judge" | "budget" | "alert";
export type Filter = "all" | "think" | "turn" | "tool" | "exec" | "error" | "orch" | "human" | "deliver";
export const FILTERS: Filter[] = ["all", "think", "turn", "tool", "exec", "error", "orch", "human", "deliver"];
export const FILTER_WORD: Record<Filter, string> = {
  all: "全部", think: "思考", turn: "模型调用", tool: "工具", exec: "命令", error: "出错", orch: "编排", human: "人的操作", deliver: "交付与判定",
};

export type Cost = { usd_milli: number; tokens_in: number; tokens_cached: number; tokens_out: number; model: string };
export type CallState = "now" | "ok" | "bad" | "gone";

export type Entry = {
  key: string;
  /** 归属的会话；任务级的事件（新建、指导、授权、交付后的追问……）为 null。 */
  lease: string | null;
  /** 任务级事件发生时正在跑的会话：排进那个会话的分组里，标“你”。 */
  during: string | null;
  round: number;
  /** 排序用的毫秒时刻：事件取 ts；活动条目取会话开始的 ts + t，没有 t（回放）时跟着前一条与 exec 留档的时刻走。 */
  at: number;
  /** 两路合并后的稳定次序。 */
  order: number;
  kind: Kind;
  item?: ActItem;
  result?: ActResult;
  /** 工具调用的状态：在做、成功、出错、没等到结果（会话已结束）。 */
  state?: CallState;
  /** 工具耗时（毫秒）：结果的 t − 调用的 t；回放时没有 t，为 null。 */
  dur?: number | null;
  /** 执行层登记的留档（exec 的结果，或事件里登记的文件）。 */
  artifact?: string;
  cost?: Cost;
  ev?: Event;
  /** 工具名：活动里的 tool；事件来的执行写执行器记的 tool。 */
  tool?: string;
  /** 搜索用的纯文本（命令、输出、自述、思考、事件体的文字）。 */
  text: string;
  /** 已入账（活动分段登记进事件账）；null 表示这个会话不入账。 */
  anchored?: boolean | null;
};

export type Round = { n: number; entries: Entry[]; turns: number; calls: number; from: number; to: number };
export type SessionGroup = {
  lease: string; kind: string; active: boolean; seq: number; start: number; end: number | null; outcome: string | null;
  target: string | null; role: string | null; model: string | null;
  /** 接力：同一目标上前一个会话（只看事件里的 target，不猜）。 */
  after: string | null;
  rounds: Round[]; entries: Entry[];
  turns: number; calls: number; failed: number; usd_milli: number; tokens: { in: number; out: number; cache_read: number };
};
export type Block = { type: "entry"; entry: Entry } | { type: "session"; group: SessionGroup };
export type Totals = {
  sessions: number; live: number; turns: number; calls: number; failed: number;
  tokensIn: number; tokensOut: number; cacheRead: number; usd_milli: number; models: string[];
};
export type Trace = { entries: Entry[]; blocks: Block[]; sessions: SessionGroup[]; counts: Record<Filter, number>; totals: Totals };

export type ActFeed = { items: ActItem[]; anchored: number | null; live: boolean; now: string | null };

type B = Record<string, unknown>;
const str = (x: unknown) => (typeof x === "string" ? x : "");
const num = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : 0);

/** 事件体里的文字（两层以内的字符串），给搜索用。 */
function textOf(body: B): string {
  const out: string[] = [];
  const walk = (v: unknown, d: number) => {
    if (typeof v === "string") { if (v.length < 4000) out.push(v); }
    else if (d < 3 && Array.isArray(v)) v.forEach((x) => walk(x, d + 1));
    else if (d < 3 && v && typeof v === "object") Object.values(v).forEach((x) => walk(x, d + 1));
  };
  walk(body, 0);
  return out.join(" ");
}

/** 事件属于哪个会话：开会话的就是它自己；其余看事件体与发起者里写明的会话。 */
function leaseOf(e: Event): string | null {
  const b = e.body as B;
  if (e.kind === "lease") return `l_${e.seq}`;
  if (e.kind === "release" || e.kind === "expire_lease") return str(b.lease) || null;
  if (e.kind === "cost") return str(b.task_id) || null;
  const p = b.producer as B | undefined;
  return str(p?.session) || str(b.lease) || e.actor.session || null;
}

const KIND_OF: Record<string, Kind> = {
  lease: "session", release: "session", expire_lease: "session",
  add_fact: "plan", add_intent: "plan", abandon_intent: "plan",
  open_problem: "human", hint: "human", approve: "human", follow_up: "human", halt: "human", budget_add: "human", accept: "human", revoke_scope: "human", profile_override: "human",
  request_scope: "scope", grant_scope: "scope",
  deliver: "deliver", close_problem: "deliver",
  request_judge: "judge", judge_verdict: "judge",
  budget_mark: "budget", extend: "budget",
  alert: "alert", scope_violation: "alert",
  kb_query: "call",
};

/** 一条进了“哪些筛选”。all 不在里面。 */
export function filtersOf(x: Entry): Filter[] {
  const f: Filter[] = [];
  switch (x.kind) {
    case "think": f.push("think"); break;
    case "turn": case "cost": f.push("turn"); break;
    case "call": f.push("tool"); if (x.tool === "exec" || x.ev?.kind === "register_artifact") f.push("exec"); if (x.state === "bad") f.push("error"); break;
    case "session": case "plan": case "budget": f.push("orch"); break;
    case "scope": f.push("human", "orch"); break;
    case "human": f.push("human"); break;
    case "deliver": case "judge": f.push("deliver"); break;
    case "alert": f.push("error"); break;
    case "end": if (!(x.item as { ok?: boolean }).ok) f.push("error"); f.push("orch"); break;
    default: break;
  }
  if (x.kind === "turn" && (x.item as ActTurn | undefined)?.stop === "max_tokens") f.push("error");
  return f;
}

export function matches(x: Entry, filter: Filter, q: string, lease: string | null): boolean {
  if (lease && x.lease !== lease && x.during !== lease) return false;
  if (filter !== "all" && !filtersOf(x).includes(filter)) return false;
  if (q) {
    const needle = q.toLowerCase();
    if (!x.text.toLowerCase().includes(needle)) return false;
  }
  return true;
}

/**
 * 合成轨迹。events 是本题到当前时刻为止的事件（升序）；acts 是每个会话的活动（按条目序号升序）。
 * 返回扁平的条目、按会话分组的块、各筛选的计数与合计。
 */
export function buildTrace(events: Event[], acts: Record<string, ActFeed>): Trace {
  const evById = new Map<string, Event>();
  const leaseEv = new Map<string, Event>();
  const ends = new Map<string, Event>();
  const costs = new Map<string, Event[]>();
  for (const e of events) {
    if (e.kind === "register_artifact") evById.set(`a_${e.seq}`, e);
    if (e.kind === "lease") leaseEv.set(`l_${e.seq}`, e);
    if (e.kind === "release" || e.kind === "expire_lease") { const l = leaseOf(e); if (l) ends.set(l, e); }
    if (e.kind === "cost") { const l = leaseOf(e); if (l) costs.set(l, [...(costs.get(l) ?? []), e]); }
  }
  let order = 0;
  const out: Entry[] = [];
  // 被活动里的 exec 结果引用的留档：并进那次工具调用，不在事件里重复列
  const absorbed = new Set<string>();

  // —— 活动条目 ——
  for (const [lease, feed] of Object.entries(acts)) {
    const start = leaseEv.get(lease)?.ts ?? 0;
    const results = new Map(feed.items.filter((x): x is ActResult => x.kind === "result").map((x) => [x.id, x]));
    const turns = feed.items.filter((x): x is ActTurn => x.kind === "turn");
    const cs = costs.get(lease) ?? [];
    const paired = cs.length > 0 && cs.length === turns.length;
    let ti = 0;
    let prev = start;
    for (const x of feed.items) {
      if (x.kind === "result") continue;
      const r = x.kind === "call" ? results.get(x.id) : undefined;
      const artTs = r?.artifact ? evById.get(r.artifact)?.ts : undefined;
      let at = typeof x.t === "number" ? start + x.t : prev;
      if (artTs !== undefined && typeof x.t !== "number") at = Math.max(prev, artTs - 1);
      prev = Math.max(prev, at);
      const anchored = feed.anchored === null ? null : Math.max(x.n, r?.n ?? 0) <= feed.anchored;
      const base = { key: `${lease}#${x.n}`, lease, during: null, round: x.round, at, order: order++, item: x, anchored };
      if (x.kind === "turn") {
        const c = paired ? cs[ti] : undefined;
        ti++;
        out.push({ ...base, kind: "turn", text: `${x.model} ${x.stop}`, ...(c ? { cost: costOf(c) } : {}) });
      } else if (x.kind === "think") {
        out.push({ ...base, kind: "think", text: (x as ActThink).text });
      } else if (x.kind === "say") {
        out.push({ ...base, kind: "say", text: x.text });
      } else if (x.kind === "end") {
        out.push({ ...base, kind: "end", text: x.gist });
      } else {
        const c = x as ActCall;
        const state: CallState = r ? (r.ok ? "ok" : "bad") : feed.live ? "now" : "gone";
        const dur = r && typeof r.t === "number" && typeof c.t === "number" ? Math.max(0, r.t - c.t) : null;
        if (r?.artifact) absorbed.add(r.artifact);
        out.push({ ...base, kind: "call", tool: c.tool, state, dur, result: r, ...(r?.artifact ? { artifact: r.artifact } : {}), text: `${c.tool} ${c.gist} ${r?.gist ?? ""}` });
      }
    }
    if (!paired) {
      for (const c of cs) out.push({ key: `cost@${c.seq}`, lease, during: null, round: 0, at: c.ts, order: order++, kind: "cost", ev: c, cost: costOf(c), text: str((c.body as B).model) });
    }
  }

  // —— 事件条目 ——
  for (const e of events) {
    if (e.kind === "cost") {
      const l = leaseOf(e);
      if (l && acts[l]) continue; // 已在上面按会话处理
      out.push({ key: `cost@${e.seq}`, lease: l, during: null, round: 0, at: e.ts, order: order++, kind: "cost", ev: e, cost: costOf(e), text: str((e.body as B).model) });
      continue;
    }
    let kind: Kind | undefined = KIND_OF[e.kind];
    const b = e.body as B;
    let tool: string | undefined;
    let artifact: string | undefined;
    if (e.kind === "register_artifact") {
      const id = `a_${e.seq}`;
      if (absorbed.has(id)) continue;
      artifact = id;
      const exec = b.exec as B | undefined;
      if (b.class === "exec" && exec) { kind = "call"; tool = str(exec.tool) || "exec"; }
      else if (b.class === "judge") kind = "judge";
      else kind = "file";
    }
    if (e.kind === "kb_query") tool = "查资料";
    if (!kind) continue;
    const lease = leaseOf(e);
    const bad = e.kind === "register_artifact" && num((b.exec as B | undefined)?.exit_code) !== 0;
    out.push({
      key: `e${e.seq}`, lease: kind === "human" || kind === "scope" || kind === "budget" ? (e.actor.kind === "adapter" ? lease : null) : lease,
      during: null, round: 0, at: e.ts, order: order++, kind, ev: e, text: `${e.kind} ${textOf(b)}`,
      ...(tool ? { tool } : {}), ...(artifact ? { artifact } : {}), ...(kind === "call" ? { state: bad ? "bad" as const : "ok" as const, dur: null } : {}),
    });
  }

  out.sort((a, b) => a.at - b.at || a.order - b.order);
  out.forEach((x, i) => { x.order = i; });

  // —— 会话分组 ——
  const groups = new Map<string, SessionGroup>();
  const lastOnTarget = new Map<string, string>();
  for (const [id, e] of leaseEv) {
    const b = e.body as B;
    const end = ends.get(id);
    const target = str(b.target) || null;
    const g: SessionGroup = {
      lease: id, kind: str(b.kind), active: !end, seq: e.seq, start: e.ts, end: end?.ts ?? null,
      outcome: end ? (str((end.body as B).outcome) || (end.kind === "expire_lease" ? "超时" : null)) : null,
      target, role: e.actor.role ?? null, model: null, after: target ? lastOnTarget.get(target) ?? null : null,
      rounds: [], entries: [], turns: 0, calls: 0, failed: 0, usd_milli: 0, tokens: { in: 0, out: 0, cache_read: 0 },
    };
    if (target) lastOnTarget.set(target, id);
    groups.set(id, g);
  }
  // 任务级事件发生时有会话在跑：排进最近开始、还没结束的那个会话
  for (const x of out) {
    if (x.lease || x.kind === "session") continue;
    let best: SessionGroup | null = null;
    for (const g of groups.values()) if (g.start <= x.at && (g.end === null || x.at <= g.end) && (!best || g.start > best.start)) best = g;
    if (best) x.during = best.lease;
  }
  for (const x of out) {
    const g = groups.get(x.lease ?? x.during ?? "");
    if (!g) continue;
    g.entries.push(x);
    if (x.lease !== g.lease) continue;
    if (x.kind === "turn") {
      g.turns++;
      const t = x.item as ActTurn;
      g.tokens.in += num(t.in); g.tokens.out += num(t.out); g.tokens.cache_read += num(t.cache_read);
      if (t.model) g.model = t.model;
    }
    if (x.kind === "call") { g.calls++; if (x.state === "bad") g.failed++; }
    if (x.cost) g.usd_milli += x.cost.usd_milli;
    if (x.kind === "cost") {
      // 没有活动的会话（或对不上）：模型调用以代理的计量为准
      if (!acts[g.lease]?.items.some((i) => i.kind === "turn")) {
        g.turns++; g.tokens.in += x.cost!.tokens_in; g.tokens.out += x.cost!.tokens_out; g.tokens.cache_read += x.cost!.tokens_cached;
      }
      if (x.cost!.model) g.model = g.model ?? x.cost!.model;
    }
  }
  for (const g of groups.values()) {
    const by = new Map<number, Round>();
    for (const x of g.entries) {
      const n = x.lease === g.lease && x.item ? x.round : by.size ? [...by.keys()].at(-1)! : 0;
      const r = by.get(n) ?? { n, entries: [], turns: 0, calls: 0, from: x.at, to: x.at };
      r.entries.push(x); r.to = Math.max(r.to, x.at);
      if (x.kind === "turn" && x.lease === g.lease) r.turns++;
      if (x.kind === "call" && x.lease === g.lease) r.calls++;
      by.set(n, r);
    }
    g.rounds = [...by.values()];
  }
  const sessions = [...groups.values()].sort((a, b) => a.start - b.start || a.seq - b.seq);

  // —— 块：会话按开始的时刻插进任务级条目之间 ——
  const blocks: Block[] = [];
  const placed = new Set<string>();
  for (const x of out) {
    const g = x.lease ? groups.get(x.lease) : x.during ? groups.get(x.during) : undefined;
    if (g) {
      if (!placed.has(g.lease)) { placed.add(g.lease); blocks.push({ type: "session", group: g }); }
      continue;
    }
    blocks.push({ type: "entry", entry: x });
  }
  for (const g of sessions) if (!placed.has(g.lease)) blocks.push({ type: "session", group: g });

  const counts = Object.fromEntries(FILTERS.map((f) => [f, 0])) as Record<Filter, number>;
  for (const x of out) { counts.all++; for (const f of filtersOf(x)) counts[f]++; }
  const models = new Set<string>();
  for (const g of sessions) if (g.model) models.add(g.model);
  for (const x of out) if (x.kind === "turn" && (x.item as ActTurn).model) models.add((x.item as ActTurn).model);
  const sum = (f: (g: SessionGroup) => number) => sessions.reduce((a, g) => a + f(g), 0);
  const looseCost = out.filter((x) => x.cost && !groups.has(x.lease ?? "")).reduce((a, x) => a + x.cost!.usd_milli, 0);
  const totals: Totals = {
    sessions: sessions.length, live: sessions.filter((g) => g.active).length,
    turns: sum((g) => g.turns), calls: out.filter((x) => x.kind === "call").length, failed: out.filter((x) => x.kind === "call" && x.state === "bad").length,
    tokensIn: sum((g) => g.tokens.in), tokensOut: sum((g) => g.tokens.out), cacheRead: sum((g) => g.tokens.cache_read),
    usd_milli: sum((g) => g.usd_milli) + looseCost, models: [...models].sort(),
  };
  return { entries: out, blocks, sessions, counts, totals };
}

function costOf(e: Event): Cost {
  const b = e.body as B;
  return { usd_milli: num(b.usd_milli), tokens_in: num(b.tokens_in), tokens_cached: num(b.tokens_cached), tokens_out: num(b.tokens_out), model: str(b.model) };
}

/** 停止原因的说法。 */
export const STOP_WORD: Record<string, string> = {
  tool_use: "要调工具", end_turn: "这一轮说完了", max_tokens: "输出到上限被截断", stop_sequence: "遇到停止符", pause_turn: "暂停", refusal: "拒绝回答",
};

/** token 的短写：1234 → 1.2k。 */
export function tok(n: number): string {
  if (n < 1000) return String(n);
  if (n < 100_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** 毫秒的短写。 */
export function dur(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1).replace(/\.0$/, "")}s`;
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

// —— 执行图的布局（§2.3）：一行一个会话，从左到右按轨迹次序；人的操作在单独的“你”泳道 ——

export type Level = "compact" | "full";
export type GNode = {
  id: string; entry: Entry; lane: number; col: number; kind: "turn" | "call" | "file" | "think" | "say" | "human" | "deliver" | "judge" | "start" | "end" | "session";
  label: string; sub: string; state: "now" | "ok" | "bad" | "idle" | "you" | "need" | "done";
  /** 挂在上一个节点下面（exec 登记的文件）。 */
  below?: boolean;
};
export type GEdge = { from: string; to: string; kind: "seq" | "relay" | "file" | "human" };
export type Lane = { key: string; label: string; sub: string; active: boolean };
export type GraphLayout = { lanes: Lane[]; nodes: GNode[]; edges: GEdge[]; cols: number };

const COMPACT = new Set<Kind>(["turn", "cost", "call", "deliver", "judge", "human", "scope", "session"]);

function nodeKind(x: Entry): GNode["kind"] | null {
  switch (x.kind) {
    case "turn": case "cost": return "turn";
    case "call": return "call";
    case "think": return "think";
    case "say": return "say";
    case "file": return "file";
    case "human": case "scope": return "human";
    case "deliver": return x.ev?.kind === "close_problem" ? "end" : "deliver";
    case "judge": return "judge";
    case "session": return "session";
    default: return null;
  }
}

/** 执行图：取轨迹里的条目排成泳道；until 给出时只画那一刻（含）之前的。 */
export function layoutGraph(trace: Trace, level: Level, labelOf: (x: Entry) => { label: string; sub: string }): GraphLayout {
  const lanes: Lane[] = [{ key: "you", label: "你", sub: "指导、授权、追问", active: false }];
  const laneOf = new Map<string, number>();
  for (const g of trace.sessions) { laneOf.set(g.lease, lanes.length); lanes.push({ key: g.lease, label: g.kind, sub: g.lease, active: g.active }); }
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const lastIn = new Map<number, string>();
  const firstOf = new Map<string, string>();
  const lastOf = new Map<string, string>();
  let col = 0;
  const pendingHuman: string[] = [];
  for (const x of trace.entries) {
    if (level === "compact" && !COMPACT.has(x.kind)) continue;
    const k = nodeKind(x);
    if (!k) continue;
    // 会话起止不单画节点：泳道本身就是会话；只有开会话那一刻作为泳道的起点
    if (x.kind === "session" && x.ev?.kind !== "lease") continue;
    const human = k === "human";
    const lane = human ? 0 : laneOf.get(x.lease ?? "") ?? (x.kind === "deliver" || x.kind === "judge" ? laneOf.get(x.during ?? "") ?? 0 : 0);
    if (k === "file" && x.lease === null && lane === 0 && x.ev?.actor.kind !== "human") continue;
    const id = `n_${x.key}`;
    const { label, sub } = labelOf(x);
    const state: GNode["state"] = x.state === "now" ? "now" : x.state === "bad" ? "bad" : human ? (x.kind === "scope" && x.ev?.kind === "request_scope" ? "need" : "you") : x.kind === "deliver" ? "done" : x.state === "ok" ? "ok" : "idle";
    nodes.push({ id, entry: x, lane, col: col++, kind: k === "session" ? "start" : k, label, sub, state });
    const prev = lastIn.get(lane);
    if (prev && lane !== 0) edges.push({ from: prev, to: id, kind: "seq" });
    if (lane !== 0) {
      lastIn.set(lane, id);
      if (!firstOf.has(x.lease ?? "")) firstOf.set(x.lease ?? "", id);
      lastOf.set(x.lease ?? "", id);
      while (pendingHuman.length) edges.push({ from: pendingHuman.shift()!, to: id, kind: "human" });
    } else if (human) {
      pendingHuman.push(id);
    }
    if (x.kind === "call" && x.artifact && level === "full") {
      const fid = `f_${x.key}`;
      nodes.push({ id: fid, entry: x, lane, col: col - 1, kind: "file", label: x.artifact, sub: "执行留档", state: "idle", below: true });
      edges.push({ from: id, to: fid, kind: "file" });
    }
  }
  // 接力：同一目标上的前一个会话 → 这个会话
  for (const g of trace.sessions) {
    if (!g.after) continue;
    const a = lastOf.get(g.after), b = firstOf.get(g.lease);
    if (a && b) edges.push({ from: a, to: b, kind: "relay" });
  }
  // 只按开始顺序把相邻会话也连起来（一个跑完下一个才起）：画成接力
  for (let i = 1; i < trace.sessions.length; i++) {
    const p = trace.sessions[i - 1], g = trace.sessions[i];
    if (g.after || p.end === null || p.end > g.start) continue;
    const a = lastOf.get(p.lease), b = firstOf.get(g.lease);
    if (a && b) edges.push({ from: a, to: b, kind: "relay" });
  }
  lanes[0].active = nodes.some((n) => n.lane === 0);
  return { lanes, nodes, edges, cols: col };
}
