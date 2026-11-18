// 人的操作的事件体构造（HMI 设计 §11.3；事件体的字段以图服务的 reducer 为准）。
// 网页与 pd 发出的事件体逐字段相同（HT-17）：两端都只是把这些字段交给同一个 validate。
// 写操作集合是规格操作表 human 一行的子集（HT-12）。
import type { HumanOpKind, Op, Profile, Seen } from "./types";

export const HUMAN_OPS: ReadonlySet<HumanOpKind> = new Set<HumanOpKind>([
  "open_problem", "register_artifact", "hint", "approve", "profile_override", "abandon_intent", "close_problem",
  "add_intent", "extend", "budget_add", "pause", "resume", "rule", "accept", "judge_revoke", "intent_done",
]);

export const ops = {
  registerInput: (hash: string, size: number, media_type: string): Op => ({ op: "register_artifact", body: { class: "input", hash, size, media_type } }),
  hintAdd: (text: string, about?: string): Op => ({ op: "hint", body: about ? { text, about } : { text } }),
  hintClose: (id: string): Op => ({ op: "hint", body: { close: id } }),
  /** seen 绑定所见卡片（H2）。M0 的图服务还不校验它，M1 起不等即 stale_view；两种情况下发出的字段相同。 */
  approve: (intent: string, seen: Seen): Op => ({ op: "approve", body: { intent, decision: "approve", seen } }),
  deny: (intent: string, reason: string, seen: Seen): Op => ({ op: "approve", body: { intent, decision: "deny", reason, seen } }),
  abandonIntent: (intent: string): Op => ({ op: "abandon_intent", body: { intent } }),
  profileOverride: (axis: keyof Profile, value: string, reason: string): Op => ({ op: "profile_override", body: { axis, value, reason } }),
  /** 人关题：终态是派生量，由图服务按三值算出，这里不带 terminal。 */
  closeProblem: (reason: string): Op => ({ op: "close_problem", body: { reason } }),
  // —— M1 ——
  extend: (seen: Seen): Op => ({ op: "extend", body: { seen } }),
  budgetAdd: (usd_milli: number): Op => ({ op: "budget_add", body: { usd_milli } }),
} as const;
