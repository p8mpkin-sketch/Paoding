// 一句话开题（起草服务 /v1/drafts）的线格式。不在 types.ts 里：那份由 scripts/gen-types.py 从图服务的 schema 生成，
// 起草服务不是图服务的一部分（设计 docs/design/kaiti §6）。
import type { Op, ProblemInput, Risk } from "./types";


/** 原文里的一个区间。start/end 是 UTF-16 下标（前端字符串直接切）。 */
export type KaitiSpan = { id: string; kind: "code" | "url" | "addr" | "host" | "money" | "duration" | "file" | "sentence"; start: number; end: number; text: string };
export type KaitiExtract = { text: string; spans: KaitiSpan[]; answers: number };
/** 出处：span 摘自原文、table 查表、prior 预算先验（估）、model 起草模型、human 人改。 */
export type KaitiSource = "span" | "table" | "prior" | "model" | "human";
export type KaitiRow = { field: string; value: unknown; source: KaitiSource; spans?: string[]; note?: string };
export type KaitiNote = { code: string; field: string; text: string; lane: "confirm" | "refuse" };
export type KaitiBlob = { name: string; media_type: string; text: string; hash: string; size: number };
export type KaitiOverrides = { risk?: Record<string, Risk>; usd_milli?: number; wall_s?: number };
export type KaitiVetted = {
  lane: "practice" | "confirm" | "refuse";
  eligible: boolean;
  notes: KaitiNote[];
  derivation: KaitiRow[];
  input: ProblemInput | null;
  priors: string;
  pid: string;
  nonce: string;
  text: string;
  spans: KaitiSpan[];
  has_answer: boolean;
  /** 起草结果的草案形态：改风险或预算后原样交回重新校验，不再调模型。 */
  draft: Record<string, unknown> | null;
  model: string;
  zero_confirm: boolean;
  caps: { open_usd_milli: number; open_wall_s: number };
  blobs: KaitiBlob[];
  /** 开题批次：若干条 input 类登记加 open_problem；有答案时 sealed 里是 "$answer"，写完保密库再换。 */
  ops: Op[] | null;
  /** 答案来自原文答案行时回传一次，只用来写保密库。 */
  secret?: string;
};
