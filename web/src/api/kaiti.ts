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
export type KaitiOverrides = { risk?: Record<string, Risk>; usd_milli?: number; wall_s?: number; ack_command?: boolean };
/** 外部判定（external-verdict §5.8）：判定权在已登记的平台；批次由“从平台导入”领题时生成。 */
export type KaitiExternal = { connector: string; judge_id: string; task: string };
/** 拒绝页的降级路：补判定终点、人工验收、高级模式、去设置页登记这个平台。 */
export type KaitiWay = "endpoint" | "human" | "advanced" | "register_platform";
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
  /** 外部判定：ops 为空，创建时调导入领题拿批次。 */
  external?: KaitiExternal | null;
  /** "command"：命令有外发的形状，人勾“只检查、不提交”之前没有批次。 */
  needs_ack?: "command" | null;
  ways?: KaitiWay[];
};

/** 已登记的外部平台（GET /v1/connectors）：只读，凭据只说设没设。 */
export type PlatformEntry = { id: string; version: string; digest: string; judges: string[]; hosts: string[]; deliver: "judge" | "worker"; slot: string; slot_set: boolean };
export type PlatformTask = { task: string; title: string; time_limit_s?: number; max_submissions?: number };
