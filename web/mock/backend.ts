// 开发与测试用的假图服务。线格式照 graph/SPEC.md 的「HTTP 绑定」，并对着真图服务录下的应答核过
// （tests/contract.test.ts 让同一套前端代码既吃假服务、也吃真应答）。
//
// 这里有一个极简的投影器（事件 → 状态），只为让假数据自洽、让 as_of 回放可演示。
// 它不是内核的副本：等级只按"最近一次裁决"粗算，没有迟滞。前端源码（src/）不得 import 本目录，
// 见 tests/boundaries.test.ts：前端不内嵌 reducer（H3）。
//
// 比真图服务（M0）多出来的东西只有两样，都是 M1 才落地的：续期门（extension 卡、extend、budget_add）
// 与 seen.card_hash 的 stale_view 校验。它们让对应的界面有数据可测。
import { createHash } from "node:crypto";
import type {
  AcceptanceItem, AcceptCheck, AcceptRecord, ApprovalDisplay, Authority, ApprovalFields, ArtifactClass, ArtifactView, Badge, BudgetResponse, Budget, CardKind, Catalog, Event,
  ExecRecord, ExtensionFields, FactNode, ScopeCardFields, ScopeDisplay, GraphView, HintNode, HintTrace, IntentNode, IntentState, JudgeEntry, KnowledgeRef, LeaseRow, Level,
  OpResult, Predicate, ProblemInput, ProblemItem, Profile, ProposalResponse, RegisterName, Risk, ScopeRule, StatusView,
  Tagged, Terminal, WorkItem,
} from "../src/api/types";
import { activityDemo, demoScript, staticScripts, type Script } from "./scenario";
import { kaitiDraft, kaitiExtract, platformRoute } from "./kaiti";

export const sha256 = (data: string | Uint8Array): string => createHash("sha256").update(data).digest("hex");

/** 键排序后的 JSON：假服务里代替 JCS，足够让同一对象得到同一哈希。 */
export function canonical(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  const o = v as Record<string, unknown>;
  return "{" + Object.keys(o).filter((k) => o[k] !== undefined).sort().map((k) => JSON.stringify(k) + ":" + canonical(o[k])).join(",") + "}";
}

export const JUDGES: Record<string, Omit<JudgeEntry, "judge_id">> = {
  replay: { version: "1", grade: "decisive", kind: "builtin", max_cost: 0.01 },
  exact_match: { version: "1", grade: "decisive", kind: "builtin", max_cost: 0 },
  window_assert: { version: "2", grade: "consistent", kind: "deferred", max_cost: 0.2 },
  ext_receipt: { version: "1", grade: "decisive", kind: "deferred", max_cost: 0 }, // 外部判定（假平台 plat-a），见 mock/kaiti.ts
  structure_check: { version: "1", grade: "advisory", kind: "builtin", max_cost: 0 }, // 人工验收道：只给读数
};
const EXTERNAL_RESOURCES = ["telemetry"];
const RISK_RANK: Record<Risk, number> = { r0: 0, r1: 1, r2: 2 };
const LEVEL_WORDS: Record<Level, string> = { E3: "判定通过", E3d: "相符", E2: "模型共识", E1: "单源复核", E0: "猜想", X: "已证伪" };
const REGISTER: Record<string, RegisterName> = {
  "artifact:exec": "证据", "artifact:judge": "证据", "artifact:input": "证据", "artifact:authored": "叙述", "artifact:knowledge": "人",
  title: "叙述", summary: "叙述", hint: "人", human_reason: "人", statement: "人", estimate: "估",
  delivery: "叙述", follow_up: "人",
};
const tag = <T>(src: string, value: T): Tagged<T> => ({ src, register: REGISTER[src], value });

const TEMPLATE_DATA = {
  title: "网络服务练习题",
  maps_to: "Problem",
  judges: ["exact_match"],
  fields: {
    scope: [{ resource: "net", pattern: "<主机>:<端口>", actions: ["connect"], risk: "r0" }],
    goal: { check: { judge_id: "exact_match" }, max_attempts: 5, accept: "judge", lock_judge: true },
    materials: [{ slot: "题面", required: true }],
    budget: { usd_milli: 11500, wall_s: 7200, verify_share: 0.2, bootstrap_share: 0.333 },
    env: { base: "default", baseline_ref: "base@1" },
    b1_cap_usd_milli: 3833,
  },
};
const TEMPLATE_TEXT = JSON.stringify(TEMPLATE_DATA);
export const TEMPLATES: Catalog = { items: [{ name: "service-practice", hash: sha256(TEMPLATE_TEXT), size: TEMPLATE_TEXT.length, signature: null, data: TEMPLATE_DATA, text: TEMPLATE_TEXT }] };

type Art = { id: string; problem_id: string; hash: string; size: number; media_type: string; class: ArtifactClass; parents: string[]; producer: { actor: string; session?: string }; exec?: ExecRecord; knowledge?: KnowledgeRef };
type Fact = { id: string; seq: number; session?: string; title: string; summary: string; claim_type: "observation" | "inference"; check?: { judge_id: string; spec_ref?: string; expect?: Record<string, unknown>; sealed?: { vault: string; digest: string }[] }; premises: string[]; grounds: string[] };
type Intent = { id: string; seq: number; session?: string; abandoned_seq?: number; title: string; summary: string; premises: string[]; risk: Risk; budget: Budget; done?: Fact["check"] & { max_attempts: number }; needs_scope?: ScopeRule[]; expected_gain?: number; rollback?: { text: string } };
type Hint = { id: string; seq: number; ts: number; author: string; text: string; about?: string; closed_seq?: number };
type Lease = { id: string; kind: string; target?: string; holder: string; reserve: Budget; issued_seq: number; expires_at: number; ended_seq?: number; outcome?: string };
type Req = { id: string; seq: number; target: string; judge_id: string; candidate?: string; verdict_seq?: number };
type Verdict = { seq: number; request: string; target: string; result: "pass" | "fail" | "inconclusive"; evidence: string[]; judge: string; version: string; grade: Predicate["grade"]; candidate?: string };
/** 运行时扩权的申请（runtime-grants §4.1）；风险已由“图服务”查表填好，riskRows 是命中的行号（从 1 起）。 */
type ScopeReq = {
  id: string; seq: number; rules: ScopeRule[]; why: string; auto: boolean; blockers: string[]; by: string; session?: string; role?: string;
  intent?: string; riskRows: (number | null)[]; status: "pending" | "granted" | "denied";
  decided?: { seq: number; by: string; via?: "auto" | "approval"; policy_version?: number; reason?: string };
};
type Problem = ProblemInput & { profile: Profile; derived_profile: Profile; opened_seq: number; opened_ts: number; closed_seq?: number; closed_ts?: number; terminal?: Terminal;
  shelf?: { state: "active" | "archived" | "trash"; seq: number; ts: number }; pinned?: boolean; renamed?: { seq: number; from: string }[] };
// 整理（curate，v5 第三期软删）：与 graph/reducer/curate.py 同规则
const TRASH_MS = 30 * 86_400_000;
const trashUntil = (p: Problem) => (p.shelf?.state === "trash" ? p.shelf.ts + TRASH_MS : null);
const shelfOf = (p: Problem, now: number) => { const u = trashUntil(p); return u !== null && now >= u ? "purged" as const : p.shelf?.state ?? "active"; };
type State = {
  seq: number; now: number; problem?: Problem; overrides: StatusView["problem"]["profile_overrides"];
  artifacts: Map<string, Art>; facts: Map<string, Fact>; intents: Map<string, Intent>; hints: Map<string, Hint>;
  leases: Map<string, Lease>; requests: Map<string, Req>; verdicts: Verdict[];
  decisions: Map<string, { decision: "approve" | "deny"; by: string; seq: number; reason: string }>;
  costs: { kind: string; lease: string; model?: string; usd_milli: number; tokens: number; wall_s: number }[];
  capAdd: number; marks: { pct: number; seq: number }[]; extendedSeq: number;
  scopeReqs: Map<string, ScopeReq>;
  acceptLog: AcceptRecord[]; accepted: boolean;
  /** 开放道（open-lane §3.4–§3.5；地图 v0.9 §3.2 ③ 草案）：与图服务同形 */
  deliveries: { id: string; seq: number; lease: string; outcome: "answered" | "partial" | "blocked"; answer?: string; claims: { text: string; refs: string[] }[]; self_check: { what: string; result: "pass" | "fail" | "skipped"; refs: string[]; item?: string }[]; unverified: string[]; needs: string[] }[];
  followUps: { id: string; seq: number; text: string; after_delivery: string | null }[];
  halted: { seq: number } | null; feedback: "adopted" | "rejected" | "none" | null;
};

function project(events: Event[], pid: string, asOf: number): State {
  const s: State = {
    seq: asOf, now: 0, overrides: [], artifacts: new Map(), facts: new Map(), intents: new Map(), hints: new Map(), leases: new Map(),
    requests: new Map(), verdicts: [], decisions: new Map(), costs: [], capAdd: 0, marks: [], extendedSeq: 0, scopeReqs: new Map(),
    acceptLog: [], accepted: false, deliveries: [], followUps: [], halted: null, feedback: null,
  };
  for (const ev of events) {
    if (ev.seq > asOf) break;
    s.now = ev.ts;
    if (ev.problem_id !== pid) continue;
    const b = ev.body as any;
    switch (ev.kind) {
      case "open_problem": s.problem = { ...b, derived_profile: b.profile, opened_seq: ev.seq, opened_ts: ev.ts }; break;
      case "register_artifact": s.artifacts.set(`a_${ev.seq}`, { ...b, id: `a_${ev.seq}`, problem_id: pid }); break;
      case "add_fact": s.facts.set(`f_${ev.seq}`, { ...b, id: `f_${ev.seq}`, seq: ev.seq, session: ev.actor.session }); break;
      case "add_intent": s.intents.set(`i_${ev.seq}`, { ...b, id: `i_${ev.seq}`, seq: ev.seq, session: ev.actor.session }); break;
      case "abandon_intent": { const i = s.intents.get(b.intent); if (i) i.abandoned_seq = ev.seq; break; }
      case "hint":
        if ("close" in b) { const h = s.hints.get(b.close); if (h) h.closed_seq = ev.seq; }
        else s.hints.set(`h_${ev.seq}`, { id: `h_${ev.seq}`, seq: ev.seq, ts: ev.ts, author: ev.actor.id, text: b.text, about: b.about });
        break;
      case "lease": s.leases.set(`l_${ev.seq}`, { id: `l_${ev.seq}`, kind: b.kind, target: b.target, holder: b.holder, reserve: b.reserve, issued_seq: ev.seq, expires_at: ev.ts + b.ttl_s * 1000 }); break;
      case "release": case "expire_lease": { const l = s.leases.get(b.lease); if (l) { l.ended_seq = ev.seq; l.outcome = b.outcome ?? "expired"; } break; }
      case "request_judge": s.requests.set(`j_${ev.seq}`, { id: `j_${ev.seq}`, seq: ev.seq, target: b.target, judge_id: b.judge_id, candidate: b.candidate }); break;
      case "judge_verdict": {
        const r = s.requests.get(b.request);
        if (r) { r.verdict_seq = ev.seq; s.verdicts.push({ seq: ev.seq, request: r.id, target: r.target, result: b.result, evidence: b.evidence ?? [], judge: r.judge_id, version: b.version, grade: b.grade, candidate: r.candidate }); }
        break;
      }
      case "approve": s.decisions.set(b.intent, { decision: b.decision, by: ev.actor.id, seq: ev.seq, reason: b.reason ?? "" }); break;
      case "cost": s.costs.push({ kind: s.leases.get(b.task_id)?.kind ?? "other", lease: b.task_id, ...(b.model ? { model: b.model } : {}), usd_milli: b.usd_milli, tokens: b.tokens_in + (b.tokens_cached ?? 0) + b.tokens_out, wall_s: b.wall_s }); break;
      case "budget_mark": s.marks.push({ pct: b.mark, seq: ev.seq }); break;
      case "budget_add": s.capAdd += b.usd_milli; break;
      case "extend": s.extendedSeq = ev.seq; break;
      case "profile_override": {
        s.overrides.push({ axis: b.axis, value: b.value, derived: b.derived ?? null, by: ev.actor.id, seq: ev.seq, reason: tag("human_reason", b.reason) });
        if (s.problem) s.problem = { ...s.problem, profile: { ...s.problem.profile, [b.axis]: b.value } };
        break;
      }
      case "request_scope":
        s.scopeReqs.set(`r_${ev.seq}`, {
          id: `r_${ev.seq}`, seq: ev.seq, rules: b.rules, why: b.why ?? "", auto: b.auto, blockers: b.blockers ?? [], by: ev.actor.id,
          session: ev.actor.session, role: ev.actor.role, intent: b.intent, riskRows: (b.risk_from ?? []).map((x: number | null) => (x === null ? null : x + 1)), status: "pending",
        });
        break;
      case "grant_scope": {
        const r = s.scopeReqs.get(b.request);
        if (!r) break;
        r.status = b.decision === "approve" ? "granted" : "denied";
        r.decided = { seq: ev.seq, by: ev.actor.id, ...(b.via ? { via: b.via } : {}), ...(b.policy ? { policy_version: b.policy.version } : {}), ...(b.reason ? { reason: b.reason } : {}) };
        if (b.decision === "approve" && s.problem) {
          const scope = [...s.problem.scope, ...(b.rules as ScopeRule[]).map((x) => ({ ...x, granted: { seq: ev.seq, by: ev.actor.id, request: r.id } }))];
          s.problem = { ...s.problem, scope, profile: b.derived, derived_profile: b.derived };
        }
        break;
      }
      case "revoke_scope":
        if (s.problem) {
          const scope = s.problem.scope.map((x, k) => (k === b.rule ? { ...x, revoked: ev.seq } : x));
          s.problem = { ...s.problem, scope, profile: b.derived, derived_profile: b.derived };
        }
        break;
      case "accept":
        s.acceptLog.push({ seq: ev.seq, decision: b.decision, checks: b.checks, ...(b.reason ? { reason: b.reason } : {}) });
        if (b.decision === "accept") s.accepted = true;
        break;
      case "close_problem": if (s.problem) { s.problem.closed_seq = ev.seq; s.problem.closed_ts = ev.ts; s.problem.terminal = b.terminal; if (b.feedback) s.feedback = b.feedback; } break;
      case "deliver": s.deliveries.push({ id: `d_${ev.seq}`, seq: ev.seq, ...b }); break;
      case "follow_up": s.followUps.push({ id: `u_${ev.seq}`, seq: ev.seq, text: b.text, after_delivery: s.deliveries.at(-1)?.id ?? null }); s.capAdd += b.budget_add_usd_milli ?? 0; break;
      case "halt": s.halted = { seq: ev.seq }; break;
      case "curate":
        if (s.problem) {
          const p = { ...s.problem };
          if ("shelf" in b) p.shelf = { state: b.shelf, seq: ev.seq, ts: ev.ts };
          if ("title" in b) { p.renamed = [...(p.renamed ?? []), { seq: ev.seq, from: p.title }]; p.title = b.title; }
          if ("pinned" in b) p.pinned = b.pinned;
          s.problem = p;
        }
        break;
    }
  }
  return s;
}

function levelOf(s: State, target: string): Level {
  // advisory 判官（如结构检查）只给读数，不让对象到 E3（与图服务的等级函数相同）
  const vs = s.verdicts.filter((v) => v.target === target && v.result !== "inconclusive" && JUDGES[v.judge]?.grade !== "advisory");
  if (target === "goal" || s.intents.has(target)) return vs.some((v) => v.result === "pass") ? "E3" : "E0";
  const last = vs[vs.length - 1];
  return !last ? "E0" : last.result === "pass" ? "E3" : "X";
}

function intentState(s: State, i: Intent): IntentState {
  const d = s.decisions.get(i.id);
  if (i.abandoned_seq || d?.decision === "deny") return "abandoned";
  if (i.premises.some((p) => s.facts.has(p) && levelOf(s, p) === "X")) return "abandoned";
  if (i.done && levelOf(s, i.id) === "E3") return "achieved";
  if (((i.needs_scope?.length ?? 0) > 0 || i.risk === "r2") && d?.decision !== "approve") return "needs_human";
  const ls = [...s.leases.values()].filter((l) => l.target === i.id && l.kind === "explore");
  if (ls.some((l) => l.ended_seq === undefined)) return "leased";
  if (ls.length > 0) return "done";
  if (i.premises.some((p) => s.intents.has(p) && levelOf(s, p) !== "E3")) return "blocked";
  return "open";
}

function badge(id: string): Badge {
  const j = JUDGES[id];
  return { judge_id: id, version: j?.version ?? null, grade: j?.grade ?? null, kind: j?.kind ?? null, label: `${id}@${j?.version ?? "?"}` };
}

function predicate(s: State, target: string, check: NonNullable<Fact["check"]>, level: Level | null, max: number | null): Predicate {
  const vs = s.verdicts.filter((v) => v.target === target);
  return {
    target, ...badge(check.judge_id), spec_ref: check.spec_ref ?? null, spec_hash: (check.spec_ref && s.artifacts.get(check.spec_ref)?.hash) || null,
    expect: check.expect ?? {}, sealed: check.sealed ?? [], max_attempts: max,
    attempts_used: max ? new Set(vs.map((v) => v.candidate ?? v.request)).size : null,
    level, level_word: level ? LEVEL_WORDS[level] : null, fail_means: target.startsWith("f_") ? "refuted" : "not_yet",
    verdicts: vs.map((v) => ({ seq: v.seq, result: v.result, judge: v.judge, version: v.version, grade: v.grade, candidate: v.candidate ?? null, request: v.request, evidence: v.evidence })),
  };
}

function factNode(s: State, f: Fact): FactNode {
  const level = levelOf(s, f.id);
  return {
    id: f.id, type: "fact", seq: f.seq, claim_type: f.claim_type, level, level_word: LEVEL_WORDS[level], unstable: false, disputed: false, stale: false,
    title: tag("title", f.title), summary: tag("summary", f.summary ?? ""), premises: f.premises, yielded_by: null, session: f.session ?? null,
    predicate: f.check ? predicate(s, f.id, f.check, level, null) : null, grounds: f.grounds,
  };
}

function intentNode(s: State, i: Intent): IntentNode {
  const level = i.done ? levelOf(s, i.id) : null;
  const d = s.decisions.get(i.id);
  const st = intentState(s, i);
  return {
    id: i.id, type: "intent", seq: i.seq, status: st, risk: i.risk, level, level_word: level ? LEVEL_WORDS[level] : null,
    title: tag("title", i.title), summary: tag("summary", i.summary ?? ""), premises: i.premises, budget: i.budget, session: i.session ?? null,
    needs_scope: i.needs_scope ?? [], gate: st !== "needs_human" && st !== "blocked" && st !== "abandoned",
    approvals: d?.decision === "approve" ? [{ seq: d.seq, by: d.by }] : [],
    attempts: [...s.leases.values()].filter((l) => l.target === i.id && l.kind === "explore").length,
    predicate: i.done ? predicate(s, i.id, i.done, level, i.done.max_attempts) : null,
    decision: d ? { decision: d.decision, by: d.by, seq: d.seq, reason: tag("human_reason", d.reason) } : null,
    expected_gain: i.expected_gain !== undefined ? tag("estimate", i.expected_gain) : null,
  };
}

const hintNode = (h: Hint): HintNode => ({ id: h.id, type: "hint", seq: h.seq, ts: h.ts, author: h.author, closed: h.closed_seq !== undefined, about: h.about ?? null, text: tag("hint", h.text) });
const bySeq = <T extends { seq: number }>(m: Map<string, T>): T[] => [...m.values()].sort((a, b) => a.seq - b.seq);
const zero = (): Budget => ({ usd_milli: 0, tokens: 0, wall_s: 0 });
const closed = (s: State) => s.problem?.closed_seq !== undefined;

function extensionPending(s: State): boolean {
  const m80 = s.marks.find((m) => m.pct === 80);
  const m50 = s.marks.find((m) => m.pct === 50);
  if (!m80 || closed(s) || s.extendedSeq > m80.seq) return false;
  return !s.verdicts.some((v) => v.result === "pass" && v.seq > (m50?.seq ?? 0));
}

/** 四顾清单（图服务 work.closeout_items 同规则）：r0 判定器判定的题为空；人工验收的题另列运行时扩过的权限与在途会话。 */
function closeoutItems(s: State): Record<string, unknown>[] {
  const p = s.problem!;
  if (p.profile.reversibility === "r0" && p.goal.accept === "judge") return [];
  const items: Record<string, unknown>[] = [{ item: "closeout_review", reason: p.profile.reversibility }];
  if (p.goal.accept === "human") {
    const granted = p.scope.filter((x) => "granted" in x && !("revoked" in x)).map((x) => ({ resource: x.resource, pattern: x.pattern, actions: x.actions, risk: x.risk }));
    if (granted.length) items.push({ item: "scope_granted", rules: granted });
    const live = [...s.leases.values()].filter((l) => l.ended_seq === undefined && l.kind !== "judge" && !closed(s)).map((l) => l.id).sort();
    if (live.length) items.push({ item: "leases_active", leases: live });
  }
  return items;
}

/** 人工验收的题：最近一条 Goal 裁决为 pass、且晚于上一次验收记录时，返回它的 seq（与图服务 work.acceptance_ready 同规则）。 */
function acceptanceReady(s: State): number | null {
  const p = s.problem;
  if (!p || p.goal.accept !== "human" || closed(s) || s.accepted) return null;
  const v = s.verdicts.filter((x) => x.target === "goal").at(-1);
  const last = Math.max(0, ...s.acceptLog.map((a) => a.seq));
  return v && v.result === "pass" && v.seq > last ? v.seq : null;
}

function work(s: State, pid: string): WorkItem[] {
  if (!s.problem || closed(s)) return [];
  const items: WorkItem[] = [];
  if (s.leases.size === 0) items.push({ kind: "bootstrap" });
  if (s.problem.goal.accept === "open" && !s.halted && s.leases.size > 0 && ![...s.leases.values()].some((l) => l.ended_seq === undefined)) {
    const last = s.deliveries.at(-1);
    if (!last || (s.followUps.at(-1)?.seq ?? 0) > last.seq) items.push({ kind: "solve" });
  }
  for (const i of bySeq(s.intents)) if (intentState(s, i) === "open") items.push({ kind: "explore", target: i.id });
  for (const r of bySeq(s.requests)) if (r.verdict_seq === undefined) items.push({ kind: "judge", target: r.id });
  for (const i of bySeq(s.intents)) if (intentState(s, i) === "needs_human") items.push({ kind: "human", target: i.id, why: "needs_human" });
  if (extensionPending(s)) items.push({ kind: "human", target: pid, why: "extension" });
  for (const r of bySeq(s.scopeReqs)) if (r.status === "pending" && !r.auto && !r.intent) items.push({ kind: "human", target: r.id, why: "scope_request" });
  if (acceptanceReady(s) !== null) items.push({ kind: "human", target: pid, why: "acceptance" });
  const last = s.deliveries.at(-1);
  if (s.problem.goal.accept === "open" && last && (s.followUps.at(-1)?.seq ?? 0) < last.seq) items.push({ kind: "human", target: pid, why: last.outcome === "blocked" ? "blocked" : "delivered" });
  return items;
}

function terminalOf(s: State): Terminal | null {
  return closed(s) ? s.problem!.terminal ?? "unsolved" : null;
}

/** 判定来源（external-verdict §5.7）：与图服务同一规则，开题时派生。 */
const EXTERNAL_JUDGES = new Set(["ext_receipt"]);
// 假后端只模拟到开放道的题面：goal.check 缺省（open）时判定来源是 self，徽章与判据是空壳（与图服务同形）
const NO_CHECK = { judge_id: "" };
function authorityOf(goal: { accept: string; check?: { judge_id: string } }): Authority {
  if (goal.accept === "open") return "self";
  return goal.accept === "human" ? "human" : EXTERNAL_JUDGES.has((goal.check ?? NO_CHECK).judge_id) ? "external" : "local";
}

function head(s: State, pid: string, now = s.now): ProblemItem {
  const p = s.problem!;
  return {
    authority: authorityOf(p.goal),
    id: pid, title: tag("title", p.title), closed: closed(s), terminal: terminalOf(s), terminal_badge: badge((p.goal.check ?? NO_CHECK).judge_id), profile: p.profile,
    opened_seq: p.opened_seq, opened_ts: p.opened_ts, closed_seq: p.closed_seq ?? null,
    spent_usd_milli: s.costs.reduce((a, c) => a + c.usd_milli, 0), cap_usd_milli: p.budget.usd_milli + s.capAdd,
    closed_ts: p.closed_ts ?? null, goal_level: levelOf(s, "goal"),
    active: closed(s) ? [] : bySeq(new Map([...s.leases].map(([k, l]) => [k, { ...l, seq: l.issued_seq }]))).filter((l) => l.ended_seq === undefined).map((l) => ({ kind: l.kind, ...(l.target !== undefined ? { target: l.target } : {}) })),
    human_todo: work(s, pid).filter((w) => w.kind === "human").length,
    wall: { cap_s: p.budget.wall_s, elapsed_s: Math.max(0, Math.floor(((p.closed_ts ?? s.now) - p.opened_ts) / 1000)) },
    shelf: shelfOf(p, now), pinned: !!p.pinned, trash_until: trashUntil(p),
  };
}

function statusView(s: State, pid: string): Omit<StatusView, "as_of" | "head" | "view_hash"> {
  const p = s.problem!;
  const brief = (id: string) => ({ id, class: s.artifacts.get(id)?.class ?? "exec" });
  const { spent_usd_milli: _s, cap_usd_milli: _c, closed_ts: _t, goal_level: _g, active: _a, human_todo: _h, wall: _w, authority: _au, shelf: _sh, pinned: _pn, trash_until: _tu, ...h } = head(s, pid);
  const leases: LeaseRow[] = bySeq(new Map([...s.leases].map(([k, l]) => [k, { ...l, seq: l.issued_seq }]))).map(({ seq: _q, ...l }) => ({ ...l, active: l.ended_seq === undefined }));
  return {
    problem: { ...h, now_ts: s.now, derived_profile: p.derived_profile, profile_overrides: s.overrides, scope: p.scope, env: p.env, judges: [...p.judges].sort(), origin: p.origin, ...(p.prefs ? { prefs: p.prefs } : {}) },
    goal: {
      statement: tag("statement", p.goal.statement), accept: p.goal.accept, predicate: predicate(s, "goal", p.goal.check ?? NO_CHECK, levelOf(s, "goal"), p.goal.max_attempts ?? null),
      ...(authorityOf(p.goal) !== "local" ? { authority: authorityOf(p.goal) } : {}),
      ...(p.goal.acceptance ? { acceptance: p.goal.acceptance as AcceptanceItem[], acceptance_ready: acceptanceReady(s), accept_log: s.acceptLog } : {}),
      ...(p.goal.accept === "open" ? {
        deliveries: s.deliveries.map((d) => ({
          id: d.id, seq: d.seq, lease: d.lease, outcome: d.outcome, answer: d.answer ?? null,
          // supported：有执行记录或材料；cited：引用了资料。两者分开算（与图服务 views._delivery 同一规则）
          claims: d.claims.map((c) => ({ text: tag("delivery", c.text), refs: c.refs.map(brief), supported: c.refs.some((r) => brief(r).class !== "knowledge"), cited: c.refs.some((r) => brief(r).class === "knowledge") })),
          self_check: d.self_check.map((c) => ({ what: tag("delivery", c.what), result: c.result, refs: c.refs.map(brief), ...(c.item ? { item: c.item } : {}) })),
          unverified: d.unverified.map((x) => tag("delivery", x)), needs: d.needs.map((x) => tag("delivery", x)),
        })),
        follow_ups: s.followUps.map((u) => ({ ...u, text: tag("follow_up", u.text) })),
        ...(s.halted ? { halted: s.halted } : {}), ...(s.feedback ? { feedback: s.feedback } : {}),
        self_checks: (p.goal.self_checks ?? []).map((c, k) => ({ ...c, id: `c${k + 1}` })),
      } : {}),
    },
    facts: bySeq(s.facts).map((f) => factNode(s, f)), intents: bySeq(s.intents).map((i) => intentNode(s, i)), hints: bySeq(s.hints).map(hintNode),
    leases, requests: bySeq(s.requests).map((r) => ({ id: r.id, seq: r.seq, target: r.target, judge_id: r.judge_id, candidate: r.candidate ?? null, verdict_seq: r.verdict_seq ?? null })),
    review: false, closeout: closeoutItems(s),
  };
}

function graphView(s: State, pid: string): Omit<GraphView, "as_of" | "head" | "view_hash"> {
  const nodes = [...bySeq(s.facts).map((f) => factNode(s, f)), ...bySeq(s.intents).map((i) => intentNode(s, i))].sort((a, b) => a.seq - b.seq);
  const live = bySeq(s.intents).filter((i) => !["achieved", "abandoned", "done"].includes(intentState(s, i)));
  const seqOf = (id: string) => Number(id.split("_")[1]);
  return {
    layer: "title", items: nodes.map(({ id, type, seq, level, level_word, title }) => ({ id, type, seq, level, level_word, title })), next_after_seq: null, total: nodes.length,
    frontier: {
      hints: bySeq(s.hints).filter((h) => h.closed_seq === undefined).map((h) => h.id),
      human: work(s, pid).filter((w): w is Extract<WorkItem, { kind: "human" }> => w.kind === "human"),
      disputed: [], intents: live.map((i) => i.id),
      premises: [...new Set(live.flatMap((i) => i.premises))].sort((a, b) => seqOf(a) - seqOf(b)),
      facts: bySeq(s.facts).filter((f) => !["E3", "X"].includes(levelOf(s, f.id))).map((f) => f.id),
    },
  };
}

function budgetView(s: State): Omit<BudgetResponse, "as_of" | "head" | "view_hash"> {
  const p = s.problem!;
  const spent = zero(), verify = zero(), reserved = zero();
  const by: Record<string, Budget> = {};
  const add = (t: Budget, c: { usd_milli: number; tokens?: number; wall_s: number }) => { t.usd_milli += c.usd_milli; t.tokens = (t.tokens ?? 0) + (c.tokens ?? 0); t.wall_s += c.wall_s; };
  for (const c of s.costs) { add(spent, c); add((by[c.kind] ??= zero()), c); if (c.kind === "judge") add(verify, c); }
  for (const l of s.leases.values()) if (l.ended_seq === undefined && !closed(s)) add(reserved, l.reserve);
  const cap = p.budget.usd_milli + s.capAdd;
  return {
    cap: { usd_milli: cap, wall_s: p.budget.wall_s }, spent, reserved, by_kind: by, verify_spent: verify, marks: s.marks.map((m) => m.pct),
    percent: { spent: Math.floor((spent.usd_milli * 100) / cap), committed: Math.floor(((spent.usd_milli + reserved.usd_milli) * 100) / cap) },
    mark_lines: [50, 80], mark_seqs: s.marks.map((m) => m.seq), verify_share: p.budget.verify_share, bootstrap_share: p.budget.bootstrap_share,
    wall: { cap_s: p.budget.wall_s, elapsed_s: Math.max(0, Math.floor((s.now - p.opened_ts) / 1000)) }, review: false,
    by_lease: byLease(s),
  };
}

/** 按会话的花费（地图 Q15，v0.9 §3.2 ③ 草案）：各行之和等于 spent */
function byLease(s: State): NonNullable<BudgetResponse["by_lease"]> {
  const rows = new Map<string, { lease: string; kind: string; usd_milli: number; tokens: number; active: boolean; model?: string }>();
  for (const c of s.costs) {
    const l = s.leases.get(c.lease);
    const r = rows.get(c.lease) ?? { lease: c.lease, kind: l?.kind ?? c.kind, usd_milli: 0, tokens: 0, active: !!l && l.ended_seq === undefined && !closed(s) };
    r.usd_milli += c.usd_milli; r.tokens += c.tokens;
    if (c.model) r.model = c.model;
    rows.set(c.lease, r);
  }
  return [...rows.values()].sort((a, b) => (a.lease < b.lease ? -1 : 1));
}

/** 时间轴的扩权刻度：与真图服务的 /ticks 同形。 */
function scopeTick(b: Record<string, any>): Record<string, unknown> {
  return { decision: b.decision, ...(b.via ? { via: b.via } : {}), ...(b.policy?.version !== undefined ? { policy_version: b.policy.version } : {}) };
}

const activeScope = (scope: ScopeRule[]): ScopeRule[] => scope.filter((x) => !("revoked" in x));

function deriveProfile(scope: ScopeRule[], judgeId: string): Profile {
  const top = scope.reduce<Risk>((a, r) => (RISK_RANK[r.risk] > RISK_RANK[a] ? r.risk : a), "r0");
  const j = JUDGES[judgeId];
  const judge: Profile["judge"] = !j || j.grade === "advisory" ? "none" : j.kind === "deferred" || j.grade === "consistent" ? "deferred" : j.max_cost <= 0.05 ? "hard" : "costly";
  return { reversibility: top, judge, info: scope.some((r) => EXTERNAL_RESOURCES.includes(r.resource)) ? "partial" : "complete" };
}

/** H6 的链级“有证据根”（裁决 005-4），与图服务的 views.evidence_rooted 同义。 */
function rooted(s: State, id: string): boolean {
  const seen = new Set<string>();
  const todo = [id];
  while (todo.length > 0) {
    const cur = todo.pop()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    const f = s.facts.get(cur), i = s.intents.get(cur);
    if (!f && !i) continue;
    if ((f && f.grounds.length > 0) || s.verdicts.some((v) => v.target === cur && v.evidence.length > 0)) return true;
    todo.push(...(f ?? i)!.premises);
  }
  return false;
}

function card(s: State, pid: string, kind: CardKind, id: string): { card: { kind: CardKind; target: string; fields: unknown }; card_hash: string; display: unknown } | "not_found" {
  let fields: unknown;
  let display: unknown;
  if (kind === "approval") {
    const i = s.intents.get(id);
    if (!i) return "not_found";
    const f: ApprovalFields = {
      risk: i.risk, budget: i.budget.usd_milli, done: i.done ? i.done.judge_id : "", tests: [], needs_scope: (i.needs_scope?.length ?? 0) > 0, rollback: i.rollback?.text ?? "",
      premises: i.premises.map((p) => ({ id: p, level: levelOf(s, p), disputed: false, unstable: false, stale: false, controlled: false, waived: false })),
    };
    const d = s.decisions.get(id);
    const disp: ApprovalDisplay = {
      status: intentState(s, i), title: tag("title", i.title), summary: tag("summary", i.summary ?? ""), reserve: i.budget, lease_note: "一次批准只管一次租约",
      rollback: i.rollback ? tag("summary", i.rollback.text) : null,
      predicate: i.done ? predicate(s, id, i.done, levelOf(s, id), i.done.max_attempts) : null,
      premises: i.premises.map((p) => { const n = s.facts.get(p) ?? s.intents.get(p)!; const lv = levelOf(s, p); return { id: p, type: s.facts.has(p) ? "fact" as const : "intent" as const, level: lv, level_word: LEVEL_WORDS[lv], title: tag("title", n.title) }; }),
      disputes: [], needs_scope: i.needs_scope ?? [], scope: s.problem!.scope,
      expected_gain: i.expected_gain !== undefined ? tag("estimate", i.expected_gain) : null,
      rollback_declared: !!i.rollback, approve_enabled: true,
      decision: d ? { decision: d.decision, by: d.by, seq: d.seq, reason: tag("human_reason", d.reason) } : null,
    };
    fields = f; display = disp;
  } else if (kind === "closeout") {
    if (id !== pid) return "not_found";
    const ready = acceptanceReady(s);
    const v = ready === null ? null : s.verdicts.find((x) => x.seq === ready)!;
    fields = {
      items: closeoutItems(s), goal_level: levelOf(s, "goal"), closed: closed(s), terminal: terminalOf(s),
      ...(s.problem!.goal.acceptance ? { acceptance: s.problem!.goal.acceptance, deliverable: v ? { verdict_seq: v.seq, candidate: v.candidate ?? null } : null } : {}),
    };
    display = { steps: ["四顾", "满志", "藏刀"], terminal_if_closed_now: levelOf(s, "goal") === "E3" ? "solved" : "unsolved", terminal_badge: badge((s.problem!.goal.check ?? NO_CHECK).judge_id) };
  } else if (kind === "extension") {
    if (id !== pid) return "not_found";
    const m50 = s.marks.find((m) => m.pct === 50)?.seq ?? 0;
    const f: ExtensionFields = { progress_since_50: s.verdicts.filter((v) => v.result === "pass" && v.seq > m50).map((v) => v.target), spent_usd_milli: s.costs.reduce((a, c) => a + c.usd_milli, 0), cap_usd_milli: s.problem!.budget.usd_milli + s.capAdd };
    fields = f; display = {};
  } else if (kind === "scope") {
    const r = s.scopeReqs.get(id);
    if (!r) return "not_found";
    const now = activeScope(s.problem!.scope);
    const keep = (x: ScopeRule): ScopeRule => ({ resource: x.resource, pattern: x.pattern, actions: x.actions, risk: x.risk });
    const f: ScopeCardFields = { rules: r.rules.map(keep), why: r.why, status: r.status, auto: r.auto, scope: now.map(keep), closed: closed(s) };
    const top = r.rules.reduce<Risk>((a, x) => (RISK_RANK[x.risk] > RISK_RANK[a] ? x.risk : a), "r0");
    const jid = (s.problem!.goal.check ?? NO_CHECK).judge_id;
    const disp: ScopeDisplay = {
      status: r.status, why: tag("summary", r.why), by: r.by, session: r.session ?? null, role: r.role ?? null, intent: r.intent ?? null,
      auto: r.auto, blockers: r.blockers, risk_rows: r.riskRows,
      profile: r.status === "pending" ? { before: deriveProfile(now, jid), after: deriveProfile([...now, ...r.rules], jid), overridden: [] } : null,
      risk_choices: (["r0", "r1", "r2"] as Risk[]).filter((k) => RISK_RANK[k] >= RISK_RANK[top]),
      approve_enabled: r.status === "pending" && !r.intent && !closed(s),
      decision: r.decided ? {
        decision: r.status === "granted" ? "approve" : "deny", by: r.decided.by, seq: r.decided.seq,
        via: r.decided.via ?? null, policy_version: r.decided.policy_version ?? null, reason: tag("human_reason", r.decided.reason ?? ""),
      } : null,
    };
    fields = f; display = disp;
  } else return "not_found";
  const c = { kind, target: id, fields };
  return { card: c, card_hash: sha256(canonical(c)), display };
}

export type MockRequest = { method: string; url: string; headers?: Record<string, string | undefined>; body?: Uint8Array };
export type MockResponse = { status: number; headers: Record<string, string>; body: Uint8Array };
export type Mock = ReturnType<typeof createMock>;
export const MOCK_TOKEN = "mock-human-token";

const enc = new TextEncoder();
const json = (status: number, v: unknown): MockResponse => ({ status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" }, body: enc.encode(JSON.stringify(v)) });
const err = (status: number, code: string, detail = "") => json(status, { ok: false, code, detail });
class Rejected extends Error { constructor(readonly code: string, readonly detail: string, readonly card?: unknown) { super(detail); } }

export function createMock(opts: { autoplayMs?: number } = {}) {
  const log: Event[] = [];
  const blobs = new Map<string, Uint8Array>();
  /** 保密库：只写（PUT /v1/vault）。测试从这里核对答案确实只进了保密库。 */
  const vault = new Map<string, Uint8Array>();
  const idem = new Map<string, ProposalResponse>();
  const subs = new Set<{ pid: string; cb: (e: Event) => void }>();
  // 假服务自己的时钟：固定起点、每个事件 +7 秒，保证两次启动得到逐字节相同的日志。
  let clock = 1_794_000_000_000;

  const headSeq = () => log.length;
  const eventsOf = (pid: string, asOf = Infinity) => log.filter((e) => e.problem_id === pid && e.seq <= asOf);
  const stateOf = (pid: string, asOf = headSeq()) => project(log, pid, asOf);
  const pids = () => [...new Set(log.filter((e) => e.kind === "open_problem").map((e) => e.problem_id))];
  const ownerOf = (id: string) => log[Number(id.split("_")[1]) - 1]?.problem_id;

  function putBlob(data: string | Uint8Array): string {
    const bytes = typeof data === "string" ? enc.encode(data) : data;
    const h = sha256(bytes);
    blobs.set(h, bytes);
    return h;
  }

  function append(pid: string, actor: Event["actor"], kind: string, body: Record<string, unknown>, idemKey?: string): Event {
    const prev = eventsOf(pid).at(-1);
    clock += 7000;
    const seq = log.length + 1;
    const base = { v: 1 as const, seq, problem_id: pid, ts: clock, actor, kind, body, idem_key: idemKey ?? `mock-${seq}`, prev_hash: prev?.hash ?? "0".repeat(64) };
    const ev: Event = { ...base, hash: sha256(canonical(base)) };
    log.push(ev);
    for (const s of subs) if (s.pid === pid) s.cb(ev);
    return ev;
  }

  // ---- 剧本 ----
  const api = { append, putBlob, stateOf: (pid: string) => stateOf(pid), sha256 };
  type Running = { pid: string; steps: Script["steps"]; at: number };
  const running: Running[] = [];
  function stepOne(r: Running): boolean {
    const st = r.steps[r.at];
    if (!st) return false;
    if (st.waitFor && !st.waitFor(stateOf(r.pid))) return false;
    st.run(api);
    r.at += 1;
    return true;
  }
  function load(script: Script, upTo?: number) {
    const r: Running = { pid: script.pid, steps: script.steps, at: 0 };
    running.push(r);
    while (r.at < (upTo ?? r.steps.length) && stepOne(r)) { /* 预先播放 */ }
  }
  /** 推进演示题一步；到头或在等人时返回 false。 */
  const step = (): boolean => running.some((r) => stepOne(r));
  for (const s of staticScripts()) load(s);
  const demo = demoScript();
  load(demo, demo.preload);
  if (opts.autoplayMs) {
    const t = setInterval(step, opts.autoplayMs);
    (t as { unref?: () => void }).unref?.();
  }

  // ---- 写 ----
  const HUMAN: Event["actor"] = { kind: "human", id: "local" };
  const DECISIONS: Record<string, CardKind> = { approve: "approval", extend: "extension", grant_scope: "scope" };

  /** 校验一条人的操作，返回规范化的事件体。 */
  function validate(pid: string, op: string, b: any, pendingArts: Set<string>, closing = false): Record<string, unknown> {
    const s = stateOf(pid);
    if (op === "register_artifact") {
      if (b.class !== "input") throw new Rejected("forbidden_op", "人的令牌只能登记 input 类");
      return { hash: b.hash, size: b.size, media_type: b.media_type, class: "input", parents: [], producer: { actor: HUMAN.id } };
    }
    if (op === "open_problem") {
      if ("profile" in b) throw new Rejected("schema_error", "profile 是派生字段，提交时不接受");
      if (s.problem) throw new Rejected("schema_error", "题目已存在");
      if (!b.title || !Array.isArray(b.scope) || b.scope.length === 0) throw new Rejected("schema_error", "title、scope 必填");
      if (!(b.budget?.usd_milli > 0) || !(b.budget?.wall_s > 0)) throw new Rejected("schema_error", "预算为正");
      // 任务级模型偏好（宪章 03 §3.1）：只能取设置页登记过的档案名
      if (b.prefs && Object.keys(b.prefs).some((k) => k !== "model" && k !== "knowledge")) throw new Rejected("schema_error", "prefs 只有 model 与 knowledge 两项");
      if (b.prefs?.model !== undefined && !settings.models.profiles.some((p) => p.name === b.prefs.model)) throw new Rejected("unknown_ref", `模型档案 ${b.prefs?.model} 未登记`);
      // 知识选项（资料库第二期，K3）：{mode: auto|pick|off, pick?}；pick 只在 mode=pick 时出现
      const kn = b.prefs?.knowledge;
      if (kn !== undefined && (!["auto", "pick", "off"].includes(kn?.mode) || (kn.mode === "pick") !== Array.isArray(kn.pick) || (kn.mode === "pick" && !kn.pick.length))) throw new Rejected("schema_error", "prefs.knowledge 是 {mode, pick?}");
      if (b.goal?.accept === "open") {
        // 开放道（open-lane §8）：不登记判据、不启用判官；假后端只收题面，不模拟求解与交付（第二步的结果页再补）
        if ("check" in b.goal || "max_attempts" in b.goal || (b.judges ?? []).length) throw new Rejected("schema_error", "开放道不登记判据、不启用判官");
        if (b.origin?.draft && b.origin.draft.lane !== "open") throw new Rejected("schema_error", "lane=open 当且仅当 goal.accept=open");
        for (const ref of [b.origin?.statement_ref, ...(b.origin?.materials ?? [])]) if (!pendingArts.has(ref) && !s.artifacts.has(ref)) throw new Rejected("unknown_ref", `材料 ${ref}`);
        return { ...b, goal: { ...b.goal, authority: "self" }, profile: deriveProfile(b.scope, "") };
      }
      if (!JUDGES[b.goal?.check?.judge_id] || (b.judges ?? []).some((j: string) => !JUDGES[j])) throw new Rejected("unknown_ref", "判官未注册");
      if (b.goal.accept !== "judge" && b.goal.accept !== "human") throw new Rejected("schema_error", "accept 取 judge、human 或 open");
      if ((b.goal.accept === "human") !== Array.isArray(b.goal.acceptance) || (b.goal.acceptance && b.goal.acceptance.length === 0)) throw new Rejected("schema_error", "accept=human 必须带非空的验收清单；判定器判定的不带");
      if (b.goal.acceptance) {
        for (const a of b.goal.acceptance) if ("id" in a || !["span", "human"].includes(a.src) || !a.text || a.text.length > 200) throw new Rejected("schema_error", "验收项须为 {text ≤200, src: span|human, needs?}");
        b = { ...b, goal: { ...b.goal, acceptance: b.goal.acceptance.map((a: object, k: number) => ({ ...a, id: `a${k + 1}` })) } };
      }
      for (const ref of [b.origin?.statement_ref, ...(b.origin?.materials ?? [])]) if (!pendingArts.has(ref) && !s.artifacts.has(ref)) throw new Rejected("unknown_ref", `材料 ${ref}`);
      return { ...b, profile: deriveProfile(b.scope, (b.goal.check ?? NO_CHECK).judge_id) };
    }
    if (!s.problem) throw new Rejected("unknown_ref", `题目 ${pid} 未开`);
    if (op === "curate") {
      const extra = Object.keys(b).filter((k) => !["shelf", "title", "pinned"].includes(k));
      if (extra.length || !Object.keys(b).length) throw new Rejected("schema_error", "curate 只改 shelf、title、pinned，至少一项");
      const cur = shelfOf(s.problem, clock + 7000);
      if (cur === "purged") throw new Rejected("forbidden_op", "这个任务在回收站里超过 30 天，工作区已清，不能再整理");
      const out: Record<string, unknown> = {};
      if ("shelf" in b) {
        if (!["active", "archived", "trash"].includes(b.shelf)) throw new Rejected("schema_error", "shelf 取 active、archived、trash");
        if (b.shelf === cur) throw new Rejected("schema_error", `任务已经在 ${cur}`);
        if (b.shelf === "trash" && !closed(s) && !closing) throw new Rejected("forbidden_op", "正在跑的任务要先停（close_problem）再移进回收站");
        out.shelf = b.shelf; out.from = cur;
      }
      if ("title" in b) {
        const t = String(b.title ?? "").trim();
        if (!t || t.length > 200) throw new Rejected("schema_error", "title 须非空、不超过 200 字");
        if (t === s.problem.title) throw new Rejected("schema_error", "新名字与现在的一样");
        out.title = t;
      }
      if ("pinned" in b) { if (typeof b.pinned !== "boolean") throw new Rejected("schema_error", "pinned 取 true 或 false"); out.pinned = b.pinned; }
      return out;
    }
    if (closed(s)) throw new Rejected("schema_error", "题目已关闭");
    const ck = DECISIONS[op];
    if (ck) {
      const c = card(s, pid, ck, op === "approve" ? b.intent : op === "grant_scope" ? b.request : pid);
      if (c === "not_found") throw new Rejected("unknown_ref", `${ck} 卡不存在`);
      // M1 的行为：带了 seen 就校验；M0 的真图服务还不看这个字段
      if (b.seen && b.seen.card_hash !== c.card_hash) throw new Rejected("stale_view", "卡片已变化", c);
    }
    switch (op) {
      case "hint":
        if ("close" in b) { if (!s.hints.has(b.close)) throw new Rejected("unknown_ref", "Hint 不存在"); return { close: b.close }; }
        if (typeof b.text !== "string" || !b.text) throw new Rejected("schema_error", "text 必填");
        if (b.about && !s.facts.has(b.about) && !s.intents.has(b.about) && b.about !== "goal") throw new Rejected("unknown_ref", "about 所指节点不存在");
        return b.about ? { text: b.text, about: b.about } : { text: b.text };
      case "approve": {
        const i = s.intents.get(b.intent);
        if (!i) throw new Rejected("unknown_ref", "Intent 不存在");
        if (b.decision !== "approve" && b.decision !== "deny") throw new Rejected("schema_error", "decision 只取 approve、deny");
        if (intentState(s, i) !== "needs_human") throw new Rejected("schema_error", "只有 needs_human 的 Intent 待审批");
        const reason = String(b.reason ?? "").trim();
        if (b.decision === "deny" && !reason) throw new Rejected("schema_error", "拒绝须写理由");
        return { intent: b.intent, decision: b.decision, ...(reason ? { reason } : {}) };
      }
      case "abandon_intent": if (!s.intents.has(b.intent)) throw new Rejected("unknown_ref", "Intent 不存在"); return { intent: b.intent };
      case "profile_override": {
        if (!["info", "judge", "reversibility"].includes(b.axis)) throw new Rejected("schema_error", "轴非法");
        if (!String(b.reason ?? "").trim()) throw new Rejected("schema_error", "覆盖须写理由");
        return { axis: b.axis, value: b.value, reason: String(b.reason).trim(), derived: s.problem.derived_profile[b.axis as keyof Profile] };
      }
      case "close_problem": {
        if ("terminal" in b) throw new Rejected("schema_error", "terminal 是派生量，由图服务按三值算出");
        const open = s.problem.goal.accept === "open";
        if (b.feedback !== undefined && (!open || !["adopted", "rejected", "none"].includes(b.feedback))) throw new Rejected("schema_error", "feedback 只用于人关开放道的题，取 adopted、rejected、none");
        const terminal = open ? (s.deliveries.some((d) => d.outcome !== "blocked") ? "delivered" : "unsolved") : levelOf(s, "goal") === "E3" ? "solved" : "unsolved";
        return { terminal, by: "human", card_hash: null, ...(b.reason ? { reason: String(b.reason) } : {}), ...(b.feedback ? { feedback: b.feedback } : {}) };
      }
      case "follow_up": {
        // 地图 v0.9 §3.2 ③ 草案：剩余低于收尾保留（这里取上限的一成）而没附追加、或追加后超单题硬顶 → over_budget
        if (s.problem.goal.accept !== "open") throw new Rejected("conflict", "只有开放道的任务可以追问");
        const text = String(b.text ?? "").trim();
        if (!text || text.length > 2000) throw new Rejected("schema_error", "追问须非空、不超过 2000 字");
        const add = b.budget_add_usd_milli;
        if (add !== undefined && !(Number.isInteger(add) && add > 0)) throw new Rejected("schema_error", "追加预算为正整数");
        const cap = s.problem.budget.usd_milli + s.capAdd + (add ?? 0);
        const spent = s.costs.reduce((a, c) => a + c.usd_milli, 0);
        if (cap > settings.caps.open_usd_milli) throw new Rejected("over_budget", `追加后超过单题硬顶 $${(settings.caps.open_usd_milli / 1000).toFixed(2)}`);
        if (cap - spent < Math.ceil(cap / 10)) throw new Rejected("over_budget", "剩余预算不够再跑一轮：追问时请附追加预算");
        return { text, ...(add ? { budget_add_usd_milli: add } : {}), seen: b.seen };
      }
      case "halt":
        if (s.problem.goal.accept !== "open") throw new Rejected("conflict", "叫停只用于开放道的任务");
        if (s.halted) throw new Rejected("conflict", "已经叫停过了");
        return b.reason ? { reason: String(b.reason) } : {};
      case "extend": if (!extensionPending(s)) throw new Rejected("schema_error", "续期门未触发"); return {};
      case "grant_scope": {
        const r = s.scopeReqs.get(b.request);
        if (!r) throw new Rejected("unknown_ref", `扩权申请 ${b.request} 不存在`);
        if (r.status !== "pending") throw new Rejected("schema_error", `扩权申请 ${b.request} 已经${r.status}`);
        if (b.decision !== "approve" && b.decision !== "deny") throw new Rejected("schema_error", "decision 只取 approve、deny");
        const reason = String(b.reason ?? "").trim();
        if (b.decision === "deny") {
          if (!reason) throw new Rejected("schema_error", "拒绝须写理由");
          return { request: r.id, decision: "deny", reason, seen: b.seen };
        }
        const rules = r.rules.map((x, k) => {
          const want = (b.risk as Risk[] | undefined)?.[k] ?? x.risk;
          if (RISK_RANK[want] < RISK_RANK[x.risk]) throw new Rejected("schema_error", `${x.pattern} 的风险只可上调`);
          return { ...x, risk: want };
        });
        const derived = deriveProfile([...activeScope(s.problem.scope), ...rules], (s.problem.goal.check ?? NO_CHECK).judge_id);
        return { request: r.id, decision: "approve", seen: b.seen, rules, derived, ...(reason ? { reason } : {}) };
      }
      case "revoke_scope": {
        const k = b.rule as number;
        const x = s.problem.scope[k];
        if (!x || "revoked" in x) throw new Rejected("unknown_ref", `规则 ${k} 不在有效范围内`);
        if (!String(b.reason ?? "").trim()) throw new Rejected("schema_error", "撤销须写理由");
        const rest = activeScope(s.problem.scope.filter((_y, j) => j !== k));
        if (rest.length === 0) throw new Rejected("schema_error", "授权范围至少留一条规则");
        return { rule: k, reason: String(b.reason).trim(), derived: deriveProfile(rest, (s.problem.goal.check ?? NO_CHECK).judge_id) };
      }
      case "budget_add": if (!(Number.isInteger(b.usd_milli) && b.usd_milli > 0)) throw new Rejected("schema_error", "金额为正"); return { usd_milli: b.usd_milli };
      case "accept": {
        // 与 graph/reducer/close.py 的 _v_accept 同规则（简化：只看本假服务能产生的情形）
        if (s.problem.goal.accept !== "human") throw new Rejected("forbidden_op", "只有人工验收的任务有验收");
        if (b.decision !== "accept" && b.decision !== "reject") throw new Rejected("schema_error", "decision 取 accept 或 reject");
        const c = card(s, pid, "closeout", pid);
        if (c === "not_found" || b.seen?.card_hash !== c.card_hash) throw new Rejected("stale_view", "卡片已变化", c === "not_found" ? undefined : c);
        if (acceptanceReady(s) === null) throw new Rejected("schema_error", "还没有待验收的交付物");
        const items = s.problem.goal.acceptance as AcceptanceItem[];
        const checks = (b.checks ?? []) as AcceptCheck[];
        if (checks.length !== items.length || items.some((a) => !checks.some((x) => x.id === a.id))) throw new Rejected("schema_error", "验收清单里每一条都要判");
        for (const x of checks) {
          const need = items.find((a) => a.id === x.id)!.needs;
          if (x.ref !== undefined) { const a = s.artifacts.get(x.ref); if (!a) throw new Rejected("unknown_ref", `验收项 ${x.id} 的依据 ${x.ref} 不是本题的产物`); if (a.class !== "exec" && a.class !== "input") throw new Rejected("inadmissible_class", "验收依据只接受 exec 类或 input 类"); }
          if (x.verdict === "pass" && need === "artifact" && !x.ref) throw new Rejected("missing_evidence", `验收项 ${x.id} 要附交付物`);
          if (x.verdict === "pass" && need === "note" && !x.note?.trim()) throw new Rejected("missing_evidence", `验收项 ${x.id} 要附说明`);
        }
        const failed = checks.filter((x) => x.verdict === "fail").map((x) => x.id);
        if (b.decision === "accept" && failed.length) throw new Rejected("schema_error", `有不通过的条目（${failed.join("、")}）：只能拒收`);
        const reason = String(b.reason ?? "").trim();
        if (b.decision === "reject" && !reason) throw new Rejected("schema_error", "拒收须写理由");
        const want = closeoutItems(s).map((x) => String(x.item));
        if (b.decision === "accept") {
          const got: string[] = Array.isArray(b.closeout) ? b.closeout : [];
          const missing = want.filter((x) => !got.includes(x));
          if (missing.length) throw new Rejected("schema_error", `四顾清单有未确认项（${missing.join("、")}）：逐条确认之后才能验收`);
        }
        return { decision: b.decision, checks, seen: b.seen, card_hash: b.seen.card_hash, ...(reason ? { reason } : {}), ...(b.decision === "accept" ? { closeout: want } : {}) };
      }
      default: throw new Rejected("schema_error", `未知操作 ${op}`);
    }
  }

  function submit(pid: string, body: any): ProposalResponse {
    const key = `${pid}:${body.idem_key}`;
    const cached = idem.get(key);
    if (cached) return cached;
    const ops = body.ops as { op: string; body?: Record<string, unknown> }[];
    const results: OpResult[] = [];
    const staged: { op: string; body: Record<string, unknown> }[] = [];
    const base = headSeq();
    const subst = (v: unknown): unknown =>
      typeof v === "string" && /^\$\d+$/.test(v) ? `a_${base + Number(v.slice(1)) + 1}` : Array.isArray(v) ? v.map(subst) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, subst(x)])) : v;
    let out: ProposalResponse;
    try {
      const pending = new Set<string>();
      ops.forEach((o, n) => {
        const b = subst(o.body ?? {}) as Record<string, unknown>;
        try {
          staged.push({ op: o.op, body: validate(pid, o.op, b, pending, staged.some((x) => x.op === "close_problem")) });
          if (o.op === "register_artifact") pending.add(`a_${base + n + 1}`);
        } catch (e) {
          if (!(e instanceof Rejected)) throw e;
          results.push({ ok: false, code: e.code, detail: e.detail, ...(e.card ? { card: e.card } : {}) });
          for (let k = n + 1; k < ops.length; k++) results.push({ ok: false, code: "batch_aborted", detail: `第 ${n} 条被拒` });
          throw e;
        }
        results.push({ ok: true, id: null, seq: 0 });
      });
      out = {
        ok: true,
        results: staged.map((o, n) => {
          const ev = append(pid, HUMAN, o.op, o.body, `${body.idem_key}#${n}`);
          const prefix = o.op === "register_artifact" ? "a" : o.op === "hint" && !("close" in o.body) ? "h" : null;
          return { ok: true, id: prefix ? `${prefix}_${ev.seq}` : null, seq: ev.seq };
        }),
      };
      // 图服务的后续：全部通过的验收之后自动关题，终态 accepted（work.followups）
      if (staged.some((o) => o.op === "accept" && o.body.decision === "accept")) append(pid, { kind: "graph", id: "graph" }, "close_problem", { terminal: "accepted", card_hash: null, by: "accept" });
    } catch (e) {
      if (!(e instanceof Rejected)) throw e;
      out = { ok: false, results: results.filter((r) => !r.ok) };
    }
    idem.set(key, out);
    return out;
  }

  // ---- 设置层（宪章 03 §7）：与 scripts/settings_hub.py 同形；摘要用规范化 JSON 的 sha256 ----
  let settings = {
    caps: { global_usd_milli: 500_000, open_usd_milli: 20_000, open_wall_s: 14_400, practice_usd_milli: 500, practice_wall_s: 1_800 },
    risk: [{ resource: "workspace", pattern: "*", actions: ["read", "write"], risk: "r0" }],
    models: {
      profiles: [
        { name: "default", endpoint: "", model: "main-1", family: "", tier: "strong", key_slot: "default" },
        { name: "light", endpoint: "", model: "light-1", family: "", tier: "light", key_slot: "default" },
      ],
      routes: { draft: "default", bootstrap: "default", reason: "default", explore: "default", verify: "default" },
    },
    grants: { runtime: true, auto: { practice: true } },
  };
  let settingsVersion = 1;
  const settingsLog: { version: number; from: string | null; to: string; keys: string[]; by: string; ts: number }[] = [
    { version: 1, from: null, to: sha256(canonical(settings)), keys: ["*"], by: "init", ts: 1_763_500_000_000 },
  ];
  const keySlots = new Map<string, { fingerprint: string; set_at: number; source: string }>([["default", { fingerprint: "1f2e3d4c…k3y0", set_at: 1_763_500_000_000, source: "env" }]]);
  const KEY_NOTE = "密钥重启后失效，可用环境变量持久注入";
  const slotView = (slot: string) => {
    const k = keySlots.get(slot);
    return { slot, set: !!k, fingerprint: k?.fingerprint ?? null, set_at: k?.set_at ?? null, source: k?.source ?? null, env: slot === "default" ? "ANTHROPIC_API_KEY" : "" };
  };
  const keysView = () => {
    const slots = new Set([...keySlots.keys(), ...settings.models.profiles.map((p) => p.key_slot)]);
    return { slots: [...slots].sort().map(slotView), note: KEY_NOTE };
  };
  function settingsRoute(method: string, path: string, auth: string, parse: () => any): MockResponse {
    const settingsDoc = () => ({ version: settingsVersion, digest: sha256(canonical(settings)), settings });
    if (method === "GET" && path === "/v1/settings") return json(200, settingsDoc());
    if (method === "GET" && path === "/v1/settings/log") return json(200, { items: settingsLog });
    if (method === "GET" && path === "/v1/settings/sources") {
      // 抄 qicao 的 kaiti.d/practice.yaml 与 priors.placeholder.yaml；练习上限取设置层（与组装根 practice_doc 同一种合成）
      const envelope = {
        version: 1,
        allow: { resources: ["net", "workspace"], net_patterns: ["q*:*", "127.0.0.1:*", "localhost:*", "10.*:*", "192.168.*:*"], max_risk: "r0" },
        judge: { ids: ["exact_match"], require_sealed: true },
        budget: { usd_milli_max: settings.caps.practice_usd_milli, wall_s_max: settings.caps.practice_wall_s },
        goal: { max_attempts_max: 5 },
      };
      return json(200, {
        envelope: { ...envelope, digest: sha256(canonical(envelope)), zero_confirm: false },
        priors: {
          version: "placeholder:placeholder-0", placeholder: true,
          tiers: {
            easy: { usd_milli: 500, wall_s: 600, bootstrap_share: null, note: "" },
            medium: { usd_milli: 2000, wall_s: 1800, bootstrap_share: null, note: "" },
            hard: { usd_milli: 6000, wall_s: 3600, bootstrap_share: null, note: "" },
          },
        },
      });
    }
    if (!auth.startsWith("Bearer ") || !auth.slice(7).trim()) return err(401, "forbidden_op", "写操作须带 Authorization: Bearer <令牌>");
    if (auth.slice(7).trim() !== MOCK_TOKEN) return err(403, "forbidden_op", "未知令牌");
    if (method === "PUT" && path === "/v1/settings") {
      const b = parse();
      const cur = sha256(canonical(settings));
      if (!b || typeof b.base_digest !== "string" || !b.settings) return err(400, "schema_error", "请求体是 {base_digest, settings}");
      if (b.base_digest !== cur) return json(409, { ok: false, code: "stale_view", detail: "设置在你读过之后被改过：重读再改", current: cur });
      const c = b.settings.caps;
      if (c.open_usd_milli > c.global_usd_milli) return err(400, "schema_error", "单任务硬顶超过全局硬顶");
      if (c.practice_usd_milli > c.open_usd_milli) return err(400, "schema_error", "练习上限超过单任务硬顶");
      settings = b.settings;
      settingsVersion += 1;
      settingsLog.push({ version: settingsVersion, from: cur, to: sha256(canonical(settings)), keys: ["*"], by: "human", ts: 1_763_500_000_000 + settingsVersion * 7_000 });
      return json(200, settingsDoc());
    }
    if (method === "GET" && path === "/v1/keys") return json(200, keysView());
    if (method === "POST" && path === "/v1/models/test") {
      // 与 settings_hub.probe 同形；假上游：模型 ID 里带 bad 的回 404，其余按名字给一个稳定的延迟
      const p = parse()?.profile;
      if (!p || typeof p !== "object") return err(400, "schema_error", "请求体是 {profile: {endpoint, model, key_slot, format?}}");
      const fmt = p.format ?? "anthropic";
      if (fmt !== "anthropic" && fmt !== "openai") return json(200, { ok: false, code: "bad_format", message: "格式取 anthropic 或 openai" });
      if (fmt === "openai" && !p.endpoint) return json(200, { ok: false, code: "bad_endpoint", message: "OpenAI 格式要写接口地址（例如 https://…/v1），缺省上游是 Anthropic 格式" });
      if (!p.model) return json(200, { ok: false, code: "no_model", message: "没写模型 ID：填上再测（不写时用命令行的缺省模型，没法单独测）" });
      if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(p.key_slot ?? "")) return json(200, { ok: false, code: "bad_slot", message: "密钥槽名不对" });
      if (!keySlots.has(p.key_slot)) return json(200, { ok: false, code: "key_not_set", message: `密钥槽 ${p.key_slot} 还没有密钥：先填密钥再测` });
      if (p.endpoint && !/^https?:\/\/./.test(p.endpoint)) return json(200, { ok: false, code: "bad_endpoint", message: "接口地址要以 http:// 或 https:// 开头" });
      const ms = 180 + (parseInt(sha256(enc.encode(String(p.model))).slice(0, 4), 16) % 460);
      if (String(p.model).includes("bad")) return json(200, { ok: false, latency_ms: ms, status: 404, code: "not_found", message: "接口地址或模型 ID 不对（上游回 404）：model not found" });
      return json(200, { ok: true, latency_ms: ms, status: 200 });
    }
    if (method === "DELETE" && path === "/v1/keys") { keySlots.clear(); return json(200, keysView()); }
    const km = path.match(/^\/v1\/keys\/([^/]+)$/);
    if (km) {
      const slot = decodeURIComponent(km[1]);
      if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(slot)) return err(400, "schema_error", "槽名取小写字母、数字、- 与 _，至多 32 字符");
      if (method === "DELETE") { keySlots.delete(slot); return json(200, { ...slotView(slot), note: KEY_NOTE }); }
      if (method === "PUT") {
        const key = parse()?.key;
        if (typeof key !== "string" || !key.trim() || /\s/.test(key.trim())) return err(400, "schema_error", "密钥须为非空、不含空白的串");
        keySlots.set(slot, { fingerprint: `${sha256(enc.encode(key)).slice(0, 8)}…${key.trim().slice(-4)}`, set_at: 1_763_500_000_000, source: "page" });
        return json(200, { ...slotView(slot), note: KEY_NOTE });
      }
    }
    return err(405, "schema_error", `${path} 不支持 ${method}`);
  }

  // ---- 记忆（通鉴；与 scripts/memory_hub.py 同形）：条目由关题封存派生，人只能钉住或遗忘 ----
  type MemRec = { seq: number; problem: string; verdict: string; on_chain: boolean; derived?: boolean };
  const memItems: Record<string, Record<string, unknown>> = {
    "m-env-1": { id: "m-env-1", kind: "env_fact", title: "q1:8080 的登录页把答案串放在 /flag 的响应头里", scope: { env_key: "e-q1" }, source: { case: "c-demo-3", problem: "demo-3", node: "f_12" }, cases: ["demo-3"] },
    "m-ex-1": { id: "m-ex-1", kind: "excluded", title: "直接猜默认口令：三次都被锁，走不通", scope: { env_key: "e-q1" }, source: { case: "c-demo-3", problem: "demo-3", node: "i_5" }, cases: ["demo-3"] },
    "m-sp-1": { id: "m-sp-1", kind: "spend_profile", title: "花费画像：示例题：取得登录后显示的答案", scope: { sig_key: "s-1" }, source: { case: "c-demo-3", problem: "demo-3" }, cases: ["demo-3"], body: { usd_milli: 420 } },
    "m-env-2": { id: "m-env-2", kind: "env_fact", title: "构建缓存目录在 /mnt/cache/pip", scope: { env_key: "e-ci" }, source: { case: "c-old", problem: "demo-1" }, cases: ["demo-1"] },
  };
  let memSeq = 40;
  const memRecalls: Record<string, MemRec[]> = {
    "m-env-1": [{ seq: 12, problem: "demo-3", verdict: "pass", on_chain: true, derived: true }],
    "m-env-2": [{ seq: 20, problem: "demo-2", verdict: "pass", on_chain: false }, { seq: 31, problem: "demo-4", verdict: "fail", on_chain: false }],
  };
  const memPins: Record<string, boolean> = {};
  const memForgotten: Record<string, boolean> = {};
  const memState = (id: string) => {
    if (memForgotten[id]) return "retired";
    const judged = (memRecalls[id] ?? []).filter((h) => ["pass", "fail", "flaky"].includes(h.verdict));
    if (judged.length >= 2 && judged.slice(-2).every((h) => h.verdict !== "pass")) return "retired";
    if (judged.length && judged.at(-1)!.verdict !== "pass") return "stale";
    return "active";
  };
  const memCard = (id: string) => ({ item: memItems[id], state: memState(id), pinned: !!memPins[id], recalls: memRecalls[id] ?? [] });
  const memSeen = (id: string) => ({ seq: memSeq, card_hash: sha256(canonical(memCard(id))) });
  function memoryRoute(method: string, path: string, auth: string, parse: () => any): MockResponse {
    if (method === "GET" && path === "/v1/memory") {
      return json(200, { items: Object.keys(memItems).sort().map((id) => ({ ...memItems[id], state: memState(id), pinned: !!memPins[id], recalls: memRecalls[id] ?? [] })), as_of: memSeq });
    }
    const m = path.match(/^\/v1\/memory\/items\/([^/]+)(?:\/(pin|forget))?$/);
    if (!m) return err(404, "unknown_ref", `没有端点 ${path}`);
    const id = decodeURIComponent(m[1]);
    if (!memItems[id]) return err(404, "unknown_ref", "记忆条目不存在");
    if (method === "GET" && !m[2]) return json(200, { ...memCard(id), seen: memSeen(id) });
    if (method !== "POST" || !m[2]) return err(405, "schema_error", `${path} 不支持 ${method}`);
    if (!auth.startsWith("Bearer ")) return err(401, "forbidden_op", "须带人的令牌");
    if (auth.slice(7).trim() !== MOCK_TOKEN) return err(403, "forbidden_op", "只接受人的令牌");
    const b = parse();
    if (!b || typeof b.reason !== "string" || typeof b.seen !== "object") return err(400, "schema_error", "请求体是 {reason, seen: {seq, card_hash}}");
    if (!b.reason.trim()) return err(400, "schema_error", "须写理由");
    if (b.seen?.card_hash !== memSeen(id).card_hash) return err(409, "stale_view", "所见的卡片已变，先看最新的");
    if (memForgotten[id]) return err(400, "schema_error", "条目已遗忘");
    if (m[2] === "pin" && ["stale", "retired"].includes(memState(id))) return err(400, "schema_error", "钉不住已过期的事实");
    memSeq += 1;
    if (m[2] === "pin") memPins[id] = true; else memForgotten[id] = true;
    return json(200, { ok: true, results: [{ ok: true, seq: memSeq }], card: { ...memCard(id), seen: memSeen(id) } });
  }

  // ---- 资料（书库；与 scripts/knowledge_hub.py 同形）：每读一次作业列表，在导入的版本推进一步 ----
  type KnRev = { n: number; file: { hash: string; size: number; media_type: string; name: string }; stage: string; failed: { stage: string; reason: string; seq: number; code?: string; count?: number } | null; chunks: number; ts: number; text: string; mask?: boolean };
  type KnSrc = { id: string; name: string; origin: string; scope: string; disabled: boolean; deleted_at: number | null; created: number; revs: KnRev[] };
  const T0 = Date.now();
  const DAY = 86_400_000;
  let knSeq = 10;
  const knFile = (name: string, size: number, media = "") => ({ hash: sha256(enc.encode(name)), size, media_type: media, name });
  const knRev = (name: string, size: number, stage: string, ts: number, text: string, chunks = 0, failed: KnRev["failed"] = null): KnRev =>
    ({ n: 1, file: knFile(name, size), stage, failed, chunks, ts, text });
  const knSources: KnSrc[] = [
    { id: "s_team01", name: "团队约定.md", origin: "file", scope: "all", disabled: false, deleted_at: null, created: T0 - 9 * DAY,
      revs: [knRev("团队约定.md", 28_672, "ready", T0 - 8 * DAY, "上线前先在 staging 跑全量测试。回滚用上一个标签重新发布，数据库迁移必须能反向执行。\n\n值班交接要写清楚未关的告警和正在做的变更。", 46)] },
    { id: "s_schema1", name: "数据库表结构导出.sql", origin: "file", scope: "all", disabled: false, deleted_at: null, created: T0 - 10 * DAY,
      revs: [knRev("数据库表结构导出.sql", 655_360, "ready", T0 - 9 * DAY, "CREATE TABLE orders (id bigint primary key, status text, created_at timestamptz);\n订单表按 created_at 分区，超时订单由 sweeper 每分钟扫一次。", 312)] },
    { id: "s_olddep1", name: "旧版部署说明.md", origin: "file", scope: "all", disabled: true, deleted_at: null, created: T0 - 95 * DAY,
      revs: [knRev("旧版部署说明.md", 1_258_291, "ready", T0 - 90 * DAY, "旧流程：手工 ssh 到每台机器拉代码重启。", 88)] },
    { id: "s_runbk01", name: "运维手册 2026.md", origin: "file", scope: "all", disabled: false, deleted_at: null, created: T0 - 60_000,
      revs: [knRev("运维手册 2026.md", 190_000, "chunk", T0 - 60_000, "订单服务超时先看 sweeper 的延迟，再看数据库连接池是否耗尽。", 0)] },
    { id: "s_scan01", name: "2025-08 支付超时复盘.pdf", origin: "file", scope: "all", disabled: false, deleted_at: null, created: T0 - 120_000,
      revs: [knRev("2025-08 支付超时复盘.pdf", 2_400_000, "parse", T0 - 120_000, "", 0, { stage: "parse", reason: "pdf 要到资料库第三期才能解析；现在可以把文字另存为 txt 或 md 再导入", code: "unsupported", seq: 9 })] },
  ];
  const knLive = (s: KnSrc) => (s.disabled || s.deleted_at !== null ? null : [...s.revs].reverse().find((r) => r.stage === "ready")?.n ?? null);
  const knView = (s: KnSrc) => {
    const last = s.revs.at(-1)!;
    const live = knLive(s);
    const cur = s.revs.find((r) => r.n === live) ?? null;
    return { id: s.id, name: s.name, origin: s.origin, scope: s.scope, disabled: s.disabled, deleted_at: s.deleted_at, created: s.created, revisions: s.revs.length,
      live_revision: live, chunks: cur?.chunks ?? 0, size: (cur ?? last).file.size, updated: (cur ?? last).ts, importing: ["parse", "chunk", "index"].includes(last.stage), failed: last.failed };
  };
  const knJobs = () => knSources.flatMap((s) => s.revs.filter((r) => ["parse", "chunk", "index"].includes(r.stage)).map((r) => ({
    source: s.id, name: s.name, revision: r.n, file: r.file, stage: r.stage, failed: r.failed, warnings: [], chunks: r.stage === "index" ? r.chunks : null, started: r.ts })));
  const knStep = () => {
    for (const s of knSources) for (const r of s.revs) {
      if (r.failed) continue;
      if (r.stage === "parse") {
        const hits = r.text.match(/(?<![A-Za-z0-9])(?:sk-|ghp_|AKIA)[A-Za-z0-9_-]{8,}/g) ?? [];
        if (/\.(pdf|docx)$/i.test(r.file.name)) r.failed = { stage: "parse", reason: "pdf / docx 要到资料库第三期才能解析", code: "unsupported", seq: ++knSeq };
        else if (hits.length && !r.mask) r.failed = { stage: "parse", reason: `发现 ${hits.length} 处像密钥或口令的串。可以遮盖后导入，或取消这次导入`, code: "secrets", count: hits.length, seq: ++knSeq };
        else { if (hits.length) for (const h of hits) r.text = r.text.split(h).join("‹资料里的凭据，已遮盖›"); r.stage = "chunk"; }
      }
      else if (r.stage === "chunk") { r.stage = "index"; r.chunks = Math.max(1, Math.ceil(r.text.length / 500)); }
      else if (r.stage === "index") { r.stage = "ready"; r.ts = Date.now(); }
    }
  };
  const knChunkId = (sid: string, i: number) => `k_${sha256(enc.encode(`${sid}:${i}`)).slice(0, 16)}`;
  const knSourcesView = () => ({ sources: [...knSources].sort((a, b) => b.created - a.created).map(knView), embedder: "hash-512-v1", note: "", as_of: knSeq });
  const knTerms = (t: string) => { const l = t.toLowerCase(); const out: string[] = [...(l.match(/[a-z0-9_]{2,}/g) ?? [])]; for (const run of l.match(/[\u3400-\u9fff]+/g) ?? []) for (let i = 0; i < Math.max(1, run.length - 1); i++) out.push(run.slice(i, i + 2)); return out; };
  function knowledgeRoute(method: string, path: string, auth: string, parse: () => any): MockResponse {
    if (method === "GET" && path === "/v1/knowledge/sources") return json(200, knSourcesView());
    if (method === "GET" && path === "/v1/knowledge/jobs") { const out = json(200, { jobs: knJobs(), as_of: knSeq }); knStep(); return out; }
    const cm = method === "GET" ? path.match(/^\/v1\/knowledge\/chunks\/(k_[0-9a-f]{16})$/) : null;
    if (cm) {
      for (const s of knSources) for (const r of s.revs) for (const [i, para] of r.text.split(/\n\n+/).entries()) {
        if (knChunkId(s.id, i) !== cm[1]) continue;
        const latest = s.revs.at(-1)!;
        return json(200, { id: cm[1], source: s.id, source_name: s.name, revision: r.n, doc: r.file.name, heading: r.file.name, start: 0, end: para.length, text: para, newer_revision: latest.n > r.n && latest.stage === "ready" });
      }
      return err(404, "unknown_ref", "没有这一段（资料可能已清掉，或索引在重建）");
    }
    if (method !== "POST") return err(405, "schema_error", `${path} 不支持 ${method}`);
    const b = parse() ?? {};
    if (path === "/v1/knowledge/search") {
      if (typeof b.q !== "string") return err(400, "schema_error", "请求体是 {q, k?, pick?}");
      const qt = new Set(knTerms(b.q));
      const k = Math.max(1, Math.min(20, Number(b.k ?? 8)));
      const hits = knSources.filter((s) => knLive(s) !== null && s.scope === "all").flatMap((s) => {
        const r = s.revs.find((x) => x.n === knLive(s))!;
        return r.text.split(/\n\n+/).map((para, i) => ({ s, r, para, i, score: knTerms(para).filter((t) => qt.has(t)).length }));
      }).filter((h) => h.score > 0).sort((a, b2) => b2.score - a.score).slice(0, k);
      return json(200, { hits: hits.map((h, n) => ({ id: knChunkId(h.s.id, h.i), source: h.s.id, source_name: h.s.name, revision: h.r.n, doc: h.r.file.name, heading: h.r.file.name, start: 0, end: h.para.length, text: h.para, score: Math.round((1 / (61 + n)) * 61 * 1000) / 1000, via: ["lex", "vec"] })),
        via: "lexical+vector", embedder: "hash-512-v1", note: "" });
    }
    if (!auth.startsWith("Bearer ")) return err(401, "forbidden_op", "须带人的令牌");
    if (auth.slice(7).trim() !== MOCK_TOKEN) return err(403, "forbidden_op", "只接受人的令牌");
    if (path === "/v1/knowledge/sources") {
      if ("path" in b || "dir" in b || "folder" in b) return err(400, "forbidden_op", "资料库不读本机目录：请在网页上选文件上传，或粘贴文字");
      if (typeof b.name !== "string" || !b.name.trim()) return err(400, "schema_error", "资料要有名字");
      let file: KnRev["file"]; let text = "";
      if (typeof b.text === "string") { if (!b.text.trim()) return err(400, "schema_error", "text 不能是空的"); const bytes = enc.encode(b.text); file = { hash: putBlob(bytes), size: bytes.length, media_type: "text/plain", name: b.file_name ?? "pasted.txt" }; text = b.text; }
      else if (b.file && typeof b.file.hash === "string") { const bytes = blobs.get(b.file.hash); if (!bytes) return err(404, "unknown_ref", "Blob 不在：先 PUT /v1/blobs 再导入"); file = { ...b.file }; text = new TextDecoder().decode(bytes); }
      else return err(400, "schema_error", "给 text，或 file: {hash, size, media_type, name}");
      const id = `s_${sha256(enc.encode(`${b.name}:${++knSeq}`)).slice(0, 12)}`;
      knSources.push({ id, name: b.name.trim(), origin: typeof b.text === "string" ? "text" : "file", scope: b.scope === "pick" ? "pick" : "all", disabled: false, deleted_at: null, created: Date.now(), revs: [{ n: 1, file, stage: "parse", failed: null, chunks: 0, ts: Date.now(), text }] });
      return json(200, { source: id, revision: 1, sources: knSourcesView().sources, jobs: knJobs() });
    }
    let m = path.match(/^\/v1\/knowledge\/sources\/([^/]+)\/(disable|enable|delete|restore)$/);
    if (m) {
      const s = knSources.find((x) => x.id === m![1]);
      if (!s) return err(404, "unknown_ref", "资料不存在");
      if (m[2] === "delete" || m[2] === "restore") {
        if ((m[2] === "delete") === (s.deleted_at !== null)) return err(409, "conflict", m[2] === "delete" ? "已经在回收站里" : "不在回收站里");
        s.deleted_at = m[2] === "delete" ? Date.now() : null;
      } else s.disabled = m[2] === "disable";
      knSeq += 1;
      return json(200, { ok: true, sources: knSourcesView().sources });
    }
    m = path.match(/^\/v1\/knowledge\/jobs\/([^/]+)\/(\d+)\/(retry|cancel)$/);
    if (m) {
      const r = knSources.find((x) => x.id === m![1])?.revs.find((x) => x.n === Number(m![2]));
      if (!r) return err(404, "unknown_ref", "没有这个版本");
      if (m[3] === "retry") {
        if (!r.failed) return err(409, "conflict", "这一步没有失败");
        if (b.mask !== undefined && typeof b.mask !== "boolean") return err(400, "schema_error", "mask 取 true 或 false");
        if (b.mask && r.failed.code !== "secrets") return err(409, "conflict", "这一步不是因为凭据停下的");
        if (b.mask) r.mask = true;
        r.failed = null;
      }
      else { if (!["parse", "chunk", "index"].includes(r.stage)) return err(409, "conflict", "这个版本已经导入完或取消了"); r.stage = "cancelled"; r.failed = null; }
      knSeq += 1;
      return json(200, { ok: true, jobs: knJobs() });
    }
    return err(404, "unknown_ref", `没有端点 ${path}`);
  }

  // ---- 路由 ----
  function handle(req: MockRequest): MockResponse {
    const u = new URL(req.url, "http://mock");
    const path = u.pathname.replace(/\/$/, "") || "/";
    const q = u.searchParams;
    const parse = () => { try { return JSON.parse(new TextDecoder().decode(req.body ?? new Uint8Array())); } catch { return null; } };
    const notFound = (d = `没有端点 ${path}`) => err(404, "unknown_ref", d);
    let m: RegExpMatchArray | null;

    if (path === "/v1/settings" || path === "/v1/settings/log" || path === "/v1/settings/sources" || path.startsWith("/v1/keys") || path === "/v1/models/test") return settingsRoute(req.method, path, req.headers?.authorization ?? "", parse);
    if (path === "/v1/memory" || path.startsWith("/v1/memory/items/")) return memoryRoute(req.method, path, req.headers?.authorization ?? "", parse);
    if (path.startsWith("/v1/knowledge/")) return knowledgeRoute(req.method, path, req.headers?.authorization ?? "", parse);
    if (path.startsWith("/v1/connectors")) {
      const auth = req.headers?.authorization ?? "";
      if (auth.slice(7).trim() !== MOCK_TOKEN) return err(401, "forbidden_op", "须带人的令牌");
      const r = platformRoute(req.method, path, parse);
      return r ? json(r.code, r.body) : notFound();
    }

    if (req.method !== "GET") {
      const auth = req.headers?.authorization ?? "";
      if (!auth.startsWith("Bearer ") || !auth.slice(7).trim()) return err(401, "forbidden_op", "写操作须带 Authorization: Bearer <令牌>");
      if (auth.slice(7).trim() !== MOCK_TOKEN) return err(403, "forbidden_op", "未知令牌");
      if (req.method === "PUT" && path === "/v1/blobs") { const b = req.body ?? new Uint8Array(); return json(201, { hash: putBlob(b), size: b.length, by: "human" }); }
      if (req.method === "PUT" && path === "/v1/vault") {
        const b = req.body ?? new Uint8Array();
        if (b.length === 0 || b.length > 64 * 1024) return err(413, "schema_error", "保密库条目须为 1 到 65536 字节");
        const key = `kt-mock-${vault.size + 1}`;
        vault.set(key, b);
        return json(201, { vault: key, digest: sha256(new Uint8Array([...new TextEncoder().encode(`salt-${key}`), ...b])) });
      }
      if (req.method !== "POST") return err(405, "schema_error", `${path} 不支持 ${req.method}`);
      const body = parse();
      if (!body || typeof body !== "object") return err(400, "schema_error", "请求体须为 JSON 对象");
      if (path === "/v1/profile/preview") return preview(body);
      if (path === "/v1/drafts/extract") return typeof body.text === "string" ? json(200, kaitiExtract(body.text)) : err(400, "schema_error", "text 须是字符串");
      if (path === "/v1/drafts") {
        if (typeof body.text !== "string") return err(400, "schema_error", "text 须是字符串");
        const want = body.profile;
        if (want !== undefined && !settings.models.profiles.some((p) => p.name === want)) return err(400, "schema_error", `没有登记名为 ${JSON.stringify(want)} 的模型档案`);
        const out = kaitiDraft(body);
        if (out instanceof Error) return err(400, "schema_error", out.message);
        if (want === undefined) return json(200, out);
        // 假服务不调模型：只把起草档案换成人选的那个，出处记“人”（与 qicao 的起草服务同一种写法）
        const derivation = out.derivation.map((r) => (r.field === "draft.model" ? { ...r, value: want, source: "human" as const, note: "你选的起草档案" } : r));
        return json(200, { ...out, model: want, derivation });
      }
      const isOpen = path === "/v1/problems";
      m = path.match(/^\/v1\/problems\/([^/]+)\/proposals$/);
      if (!isOpen && !m) return notFound();
      if (!Array.isArray(body.ops) || body.ops.length === 0 || !body.ops.every((o: any) => o && typeof o.op === "string")) return err(400, "schema_error", "ops 须为非空数组，每条带 op");
      if (typeof body.idem_key !== "string" || !body.idem_key) return err(400, "schema_error", "写操作须带 idem_key");
      for (const o of body.ops) if (o.op === "register_artifact" && !blobs.has(o.body?.hash)) return err(404, "unknown_ref", "Blob 不存在，先 PUT /v1/blobs");
      if (isOpen) {
        if (typeof body.id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(body.id)) return err(400, "schema_error", "id 须为 1–64 位的字母、数字、点、横线、下划线");
        if (body.ops.at(-1).op !== "open_problem" || body.ops.slice(0, -1).some((o: any) => o.op !== "register_artifact")) return err(400, "schema_error", "ops 只能是若干条 input 类 register_artifact 加最后一条 open_problem");
        const out = submit(body.id, body);
        return json(out.ok ? 201 : 200, { ...out, id: body.id });
      }
      return json(200, submit(decodeURIComponent(m![1]), body));
    }

    if (path === "/v1/health") return json(200, { ok: true, head: headSeq(), api: "v1" });
    if (path === "/v1/judges") return json(200, { items: Object.keys(JUDGES).sort().map((k) => ({ judge_id: k, ...JUDGES[k] })), external_resources: EXTERNAL_RESOURCES });
    if (path === "/v1/templates") return json(200, TEMPLATES);
    if (path === "/v1/renderers") return json(200, { items: [] });
    if ((m = path.match(/^\/v1\/blobs\/([^/]+)$/))) {
      if (!/^[0-9a-f]{64}$/.test(m[1])) return err(400, "schema_error", "hash 须为 sha256");
      const bytes = blobs.get(m[1]);
      if (!bytes) return notFound("没有这个 Blob");
      return { status: 200, headers: { "content-type": "application/octet-stream", "content-disposition": `attachment; filename="${m[1].slice(0, 16)}.bin"`, "x-content-type-options": "nosniff" }, body: bytes };
    }
    if ((m = path.match(/^\/v1\/leases\/([^/]+)\/activity$/))) {
      // 会话活动（scripts/stack.py 的同名端点）：假后端不跑 CLI，给固定的流水；耗时与花费取本题的 cost 事件
      const lid = decodeURIComponent(m[1]);
      for (const pid of pids()) {
        const s = stateOf(pid, Infinity);
        const l = s.leases.get(lid);
        if (!l) continue;
        const active = l.ended_seq === undefined && !closed(s);
        const all = l.kind === "solve" ? activityDemo(active, pid) : [];
        const after = Number(q.get("after") ?? 0);
        const items = all.filter((x) => Number(x.n) > after);
        const done = new Set(all.filter((x) => x.kind === "result").map((x) => x.id));
        const calls = all.filter((x) => x.kind === "call");
        const pending = calls.filter((x) => !done.has(x.id)).at(-1);
        const mine = s.costs.filter((c) => c.lease === lid);
        return json(200, {
          lease: lid, problem_id: pid, kind: l.kind, active, live: active, status: active ? "running" : all.length ? "released" : "none",
          rounds: 1, model: "model-a", elapsed_s: mine.reduce((a, c) => a + c.wall_s, 0), spent_usd_milli: mine.reduce((a, c) => a + c.usd_milli, 0), closing: false,
          items, next_after: items.length ? Number(items.at(-1)!.n) : after, total: all.length, calls: calls.length,
          now: active ? pending ?? null : null, last_say: all.filter((x) => x.kind === "say").at(-1) ?? null,
        });
      }
      return notFound(`没有会话 ${lid}`);
    }
    if ((m = path.match(/^\/v1\/problems\/([^/]+)\/events$/))) {
      const pid = decodeURIComponent(m[1]);
      if (!pids().includes(pid)) return notFound(`题目 ${pid} 不存在`);
      const after = Number(q.get("after") ?? 0);
      const evs = eventsOf(pid, q.has("as_of") ? Number(q.get("as_of")) : Infinity).filter((e) => e.seq > after).slice(0, Number(q.get("limit") ?? 1000));
      return json(200, { events: evs, head: headSeq(), next_after: evs.at(-1)?.seq ?? after });
    }

    // 视图端点：统一外壳 {as_of, head, view_hash, …视图}
    const asOfRaw = q.get("as_of");
    const asOf = asOfRaw === null ? headSeq() : Number(asOfRaw);
    if (!Number.isInteger(asOf) || asOf < 0) return err(400, "schema_error", "as_of 须为整数");
    if (asOf > headSeq()) return err(400, "schema_error", `as_of=${asOf} 超过链头 ${headSeq()}`);
    const wrap = (doc: object, pid?: string) => json(200, {
      as_of: asOf, head: headSeq(), view_hash: sha256(canonical(doc)), ...doc,
      ...(q.get("state_hash") === "1" && pid ? { state_hash: sha256(canonical(log.filter((e) => e.seq <= asOf).map((e) => e.hash))) } : {}),
    });

    if (path === "/v1/problems") {
      const items = pids().map((pid) => ({ pid, s: stateOf(pid, asOf) })).filter((x) => x.s.problem).map((x) => head(x.s, x.pid, clock));
      // solved 与每解成本只数本地判定；外部判定与人工验收各自一行（external-verdict §5.7）
      const tally = (a: Authority) => {
        const xs = items.filter((i) => i.authority === a);
        const n = (t: Terminal) => xs.filter((i) => i.closed && i.terminal === t).length;
        return { problems: xs.length, solved: n("solved"), accepted: n("accepted"), unsolved: n("unsolved"), open: xs.filter((i) => !i.closed).length };
      };
      const by_authority = { local: tally("local"), external: tally("external"), human: tally("human") };
      const solved = by_authority.local.solved;
      const spent = items.reduce((a, i) => a + i.spent_usd_milli, 0);
      return wrap({ items, totals: { problems: items.length, solved, spent_usd_milli: spent, cost_per_solve_usd_milli: solved ? Math.floor(spent / solved) : null, by_authority } });
    }
    if ((m = path.match(/^\/v1\/artifacts\/([^/]+)$/))) {
      const pid = ownerOf(m[1]);
      const a = pid && stateOf(pid, asOf).artifacts.get(m[1]);
      if (!a) return notFound(`没有 Artifact ${m[1]}`);
      const src = `artifact:${a.class}`;
      const doc: Omit<ArtifactView, "as_of" | "head" | "view_hash"> = { id: a.id, problem_id: a.problem_id, hash: a.hash, size: a.size, media_type: a.media_type, class: a.class, parents: a.parents, producer: a.producer, seq: Number(a.id.split("_")[1]), src, register: REGISTER[src], exec: a.exec ?? null, ...(a.knowledge ? { knowledge: a.knowledge } : {}) };
      return wrap(doc);
    }
    if ((m = path.match(/^\/v1\/nodes\/([^/]+)$/))) {
      const pid = ownerOf(m[1]);
      const s = pid ? stateOf(pid, asOf) : null;
      const f = s?.facts.get(m[1]), i = s?.intents.get(m[1]), h = s?.hints.get(m[1]);
      if (!s || (!f && !i && !h)) return notFound(`没有节点 ${m[1]}`);
      if (f) {
        const n = factNode(s, f);
        const grounds = f.grounds.map((g) => { const a = s.artifacts.get(g)!; const src = `artifact:${a.class}`; return { id: g, class: a.class, src, register: REGISTER[src], hash: a.hash, size: a.size }; });
        return wrap({ problem_id: pid, ...n, grounds, no_evidence_root: !rooted(s, f.id), body_ref: null });
      }
      if (i) return wrap({ problem_id: pid, ...intentNode(s, i), leases: [...s.leases.values()].filter((l) => l.target === i.id).map((l) => l.id), no_evidence_root: !rooted(s, i.id) });
      return wrap({ problem_id: pid, ...hintNode(h!) });
    }
    if ((m = path.match(/^\/v1\/hints\/([^/]+)\/trace$/))) {
      const pid = ownerOf(m[1]);
      const s = pid ? stateOf(pid, asOf) : null;
      const h = s?.hints.get(m[1]);
      if (!s || !h) return notFound(`没有 Hint ${m[1]}`);
      const abandons = eventsOf(pid!, asOf).filter((e) => e.kind === "abandon_intent" || (e.kind === "approve" && e.body.decision === "deny")).map((e) => ({ seq: e.seq, intent: e.body.intent as string, session: e.actor.session }));
      const sessions = [...s.leases.values()].filter((l) => l.kind === "reason" && l.issued_seq > h.seq && (h.closed_seq === undefined || l.issued_seq < h.closed_seq)).sort((a, b) => a.issued_seq - b.issued_seq);
      const ids = new Set(sessions.map((l) => l.id));
      const doc: Omit<HintTrace, "as_of" | "head" | "view_hash"> = {
        hint: hintNode(h), closed_seq: h.closed_seq ?? null, note: "关联，不是因果",
        temporal: { added: bySeq(s.intents).filter((i) => i.seq > h.seq).map((i) => i.id), abandoned: abandons.filter((a) => a.seq > h.seq).map((a) => a.intent) },
        exposure: { sessions: sessions.map((l) => l.id), added: bySeq(s.intents).filter((i) => i.session && ids.has(i.session)).map((i) => i.id), abandoned: abandons.filter((a) => a.session && ids.has(a.session)).map((a) => a.intent) },
      };
      return wrap(doc);
    }
    if ((m = path.match(/^\/v1\/problems\/([^/]+)\/ticks$/))) {
      const pid = decodeURIComponent(m[1]);
      if (!stateOf(pid, asOf).problem) return notFound(`题目 ${pid} 不存在（或在该序号时尚未开题）`);
      const evs = eventsOf(pid, asOf);
      const ticks = evs.map((e) => ({ seq: e.seq, ts: e.ts, kind: e.kind,
        ...(e.kind === "judge_verdict" ? { result: e.body.result } : {}), ...(e.kind === "budget_mark" ? { mark: e.body.mark } : {}),
        ...(e.kind === "grant_scope" ? scopeTick(e.body) : {}) }));
      return json(200, { as_of: asOf, head: headSeq(), ticks, last_seq: evs.at(-1)?.seq ?? 0, head_hash: evs.at(-1)?.hash ?? null });
    }
    if ((m = path.match(/^\/v1\/problems\/([^/]+)\/(.+)$/))) {
      const pid = decodeURIComponent(m[1]);
      const s = stateOf(pid, asOf);
      if (!s.problem) return notFound(`题目 ${pid} 不存在（或在该序号时尚未开题）`);
      if (m[2] === "snapshot") {
        const sh = { state_hash: sha256(canonical(log.filter((e) => e.seq <= asOf).map((e) => e.hash))) };
        const docs = { status: statusView(s, pid), view: graphView(s, pid), budget: budgetView(s), work: { items: work(s, pid) } };
        const parts_hash = Object.fromEntries(Object.entries(docs).map(([k, d]) => [k, sha256(canonical(d))])) as Record<keyof typeof docs, string>;
        const want = (q.get("parts") ?? "status,view,budget,work").split(",").filter(Boolean);
        if (want.length === 0 || want.some((k) => !(k in docs))) return err(400, "schema_error", "parts 只取 status,view,budget,work");
        const out: Record<string, unknown> = { as_of: asOf, head: headSeq(), view_hash: sha256(canonical(parts_hash)), parts_hash };
        for (const k of Object.keys(docs) as (keyof typeof docs)[]) {
          if (want.includes(k)) out[k] = { as_of: asOf, head: headSeq(), view_hash: parts_hash[k], ...docs[k], ...(k === "status" && q.get("state_hash") === "1" ? sh : {}) };
        }
        return json(200, out);
      }
      switch (m[2]) {
        case "status": return wrap(statusView(s, pid), pid);
        case "view": return wrap(graphView(s, pid));
        case "budget": return wrap(budgetView(s));
        case "work": return wrap({ items: work(s, pid) });
        case "invalidations": return wrap({ node: q.get("node"), invalidated: [] });
      }
      const cm = m[2].match(/^cards\/([^/]+)\/([^/]+)$/);
      if (cm) {
        if (cm[1] === "dispute") return err(404, "not_enabled", "dispute 卡随 M1 落地");
        const c = card(s, pid, cm[1] as CardKind, decodeURIComponent(cm[2]));
        return c === "not_found" ? notFound(`没有卡片 ${cm[1]}/${cm[2]}`) : wrap(c);
      }
    }
    return notFound();
  }

  function preview(body: any): MockResponse {
    if ("profile" in body) return err(400, "schema_error", "profile 是派生字段，提交时不接受");
    if (!Array.isArray(body.scope) || body.scope.length === 0) return err(400, "schema_error", "scope 必填且非空");
    const jid = body.goal?.check?.judge_id;
    const j = JUDGES[jid];
    if (!j) return err(404, "unknown_ref", `判官 ${jid} 未注册`);
    const scope: ScopeRule[] = body.scope.map((r: any) => ({ resource: String(r.resource), pattern: String(r.pattern ?? ""), actions: r.actions ?? [], risk: r.risk ?? "r2" }));
    const profile = deriveProfile(scope, jid);
    const top = scope.findIndex((r) => r.risk === profile.reversibility);
    const ext = scope.map((r, i) => (EXTERNAL_RESOURCES.includes(r.resource) ? i : -1)).filter((i) => i >= 0);
    const why = j.kind === "deferred" ? { rule: "kind=deferred", field: "kind", value: j.kind } : j.grade === "consistent" ? { rule: "grade=consistent", field: "grade", value: j.grade } : { rule: "max_cost 与廉价判官阈值比较", field: "max_cost", value: j.max_cost, threshold: 0.05 };
    return json(200, { profile, basis: {
      reversibility: { rule: "scope 中的最高风险", scope_index: top, risk: scope[top].risk, defaulted: !("risk" in body.scope[top]) },
      judge: { judge_id: jid, version: j.version, ...why },
      info: { rule: "scope 中有外部资源即 partial", scope_indexes: ext, resources: [...new Set(ext.map((i) => scope[i].resource))].sort() },
    } });
  }

  /** 某序号上四份投影的 view_hash（事件流的 view 帧用）。题在该序号时还没开就是 null。 */
  function partsHash(pid: string, seq: number): Record<string, string> | null {
    const r = handle({ method: "GET", url: `/v1/problems/${encodeURIComponent(pid)}/snapshot?as_of=${seq}&parts=work` });
    if (r.status !== 200) return null;
    return (JSON.parse(new TextDecoder().decode(r.body as Uint8Array)) as { parts_hash: Record<string, string> }).parts_hash;
  }

  /** 事件流：先补发 after 之后的，再推新的。返回取消函数。 */
  function subscribe(pid: string, after: number, cb: (e: Event) => void): () => void {
    for (const e of eventsOf(pid)) if (e.seq > after) cb(e);
    const sub = { pid, cb };
    subs.add(sub);
    return () => subs.delete(sub);
  }

  return { handle, subscribe, partsHash, step, append, putBlob, vault, eventsOf, pids, head: (pid: string) => eventsOf(pid).at(-1)?.seq ?? 0, globalHead: headSeq, demoPid: demo.pid };
}
