// 通鉴（记忆）的应答形状：scripts/memory_hub.py 挂在图服务 HTTP 上的 /v1/memory/…。
// 这些端点挂在组装根上，不在图服务的线格式 schema 里，所以不放进生成物 types.ts。
// 条目是关题封存后派生出来的，人只能钉住或遗忘，不能手写（tongjian/reducer.py）。

export type MemKind = "env_fact" | "excluded" | "spend_profile";
/** 派生状态：retired 遗忘或连续两次复核不过；stale 最近一次复核不过；dormant 久被召回却不在解题链上；其余 active。 */
export type MemState = "active" | "dormant" | "stale" | "retired";
export type MemRecall = { seq: number; problem: string; verdict: "pass" | "fail" | "flaky" | string; on_chain: boolean; derived?: boolean };
export type MemItem = {
  id: string;
  kind: MemKind | string;
  title: string;
  scope: Record<string, unknown>;
  source: { case?: string; problem?: string; node?: string; seal_head?: string };
  cases?: string[];
  body?: Record<string, unknown>;
  model_epoch?: string;
};
export type MemRow = MemItem & { state: MemState; pinned: boolean; recalls: MemRecall[] };
export type MemSeen = { seq: number; card_hash: string };
/** 人钉住或遗忘之前看的那张卡；seen 随决定一起交回，卡变了服务端回 409 stale_view。 */
export type MemCard = { item: MemItem; state: MemState; pinned: boolean; recalls: MemRecall[]; seen: MemSeen };
export type MemDecision = { ok: boolean; results: { ok: boolean; seq: number }[]; card: MemCard };
