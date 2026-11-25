// 方案分析（界面一期，docs/design/engine-ui）的线格式：组装根 scripts/analysis_hub.py 读引擎工作区给出。
// 引擎产物的形状照 docs/design/fenjue/10-schemas.md；界面只用到的栏写出类型，其余原样透传。

export type AnStep = "S0" | "S1" | "S2" | "S3" | "G1" | "S4" | "G2" | "S5" | "G3" | "S6" | "done" | "paused_budget" | "halted" | "failed";
export type AnGate = "G1" | "G2" | "G3";
export type AnUnitState = "todo" | "doing" | "done" | "failed" | "budget_cut" | "void";

export type AnLicense = { status: string; spdx?: string; detected?: string; reuse?: "may_consult_code" | "idea_only" | string };
export type AnSource = { no: number; form: string; via: string; artifact?: string; url?: string; ref?: string; text?: string };
export type AnWaiting = { gate: AnGate; deliver_seq: number; submitted: boolean };

export type AnalysisRow = {
  run: string;
  mode: "formal" | "dry_run" | string;
  step: AnStep | null;
  statement: string;
  sources: AnSource[];
  requested_by: string;
  date: string;
  updated_at: string;
  waiting: AnWaiting | null;
  spent_usd_milli: number;
  budget_usd_milli: number;
  candidates: number;
  license: AnLicense | null;
};
export type AnalysesView = { items: AnalysisRow[]; stage_share: Record<string, number> };

export type AnUnit = { id: string; step: string; state: AnUnitState; output?: string; summary?: string; attempts?: number };
export type AnSpent = { usd_milli: number; by_step: Record<string, number>; tokens: Record<string, [number, number]> };
export type AnDecision = {
  v: 1;
  gate: AnGate;
  pick?: string[];
  exclude?: { candidate: string; why?: string }[];
  edit?: { pointer: string; value: string }[];
  note?: string;
  /** 第 2 次确认：确认、退回重做、放弃。 */
  confirm?: string[];
  back?: (string | { candidate: string; why?: string })[];
  drop?: (string | { candidate: string; why?: string })[];
  /** 第 3 次确认：交实现线、搁置、排除、存入资料库。 */
  to_implementation?: string[];
  hold?: { candidate: string; why?: string }[];
  library_import?: boolean;
  [k: string]: unknown;
};
export type AnGateRow = { gate: AnGate; deliver_seq: number; follow_up_seq?: number; decision?: AnDecision };
export type AnArtifact = { name: string; sha256: string; /** 交付末尾对照表里的 id（E-U5）。 */ artifact_id?: string; kind: "material" | "exec" | "analysis"; bytes: number };

export type AnEvidence = { snapshot: string; path?: string; lines?: [number, number]; sha256?: string; url?: string };
export type AnObservation = {
  id: string;
  slot: string;
  kind: string;
  form: string;
  statement: string;
  dims: string[];
  primitives: string[];
  level_hint?: number;
  evidence: AnEvidence[];
  suspected_injection: boolean;
  injection_note?: string;
  reader?: { tier: string; attempt: number };
};

export type AnGap = {
  dim: string;
  ours: number;
  theirs: number;
  gap: number;
  type: "missing" | "weaker" | "new_dim" | string;
  ours_by?: string;
  weight: number;
  pain: number;
  pain_basis: string;
  observations: string[];
};
export type AnCandidate = {
  id: string;
  name: string;
  title: string;
  slot: string;
  also_slots?: string[];
  gaps: AnGap[];
  value: number;
  confidence: number;
  confidence_parts?: Record<string, number>;
  difficulty: number;
  difficulty_basis?: string;
  difficulty_parts?: Record<string, number>;
  risk: string;
  priority: number;
  flags?: string[];
  seed: { name: string; title: string; shihuo: { source: string; phenomenon: string; gap: string; is_fire: string } };
  provenance: { observations: string[]; source_label?: string };
  recommend: { level: "recommend" | "optional" | "not_recommended" | string; why: string };
  dedupe?: { bang: string; note?: string };
};
export type AnCheck = { id: string; ok: boolean; detail?: string; advisory?: boolean; override?: boolean };
export type AnCoverage = { slot: string; excerpts: number; tokens_in: number; stop: string; max_score?: number; modules?: string[] };
export type AnCandidatesDoc = {
  v: 1;
  mode: string;
  run: string;
  basis: { gongfa_jie: number; gongfa_digest: string; profile_sha256: string; snapshots: { id: string; form: string; size_tier?: string; license: AnLicense; identity?: Record<string, string> }[] };
  candidates: AnCandidate[];
  already_have: { dim: string; ours: number; theirs: number; by?: string; observations: string[] }[];
  not_fire: { what: string; why: string }[];
  unseen_slots: string[];
  coverage: AnCoverage[];
  checks: AnCheck[];
  plain_summary: string;
};
export type AnEssence = {
  candidate: string;
  plain_summary?: string;
  masked: { statement: string; fusion: { emergent: { dim: string; measure: string; gate: number | string }[]; [k: string]: unknown }; [k: string]: unknown };
  checks: AnCheck[];
  validators: AnCheck[];
  drafts: { agreement?: number; n?: number; chosen?: string; disagreements?: string[] };
};
/** 映射（第 3 次确认交付的每个候选一份，10 §placement）：界面只读到的栏。 */
export type AnModule = { id: string; ver?: number; slot: string; also_touches?: string[] };
export type AnReading = { dim: string; kind: string; dir: "up" | "down" | string; gate?: number | string; test?: string; run?: string; mandatory?: boolean };
export type AnPlacement = {
  candidate: string;
  plain_summary?: string;
  fire: AnModule;
  group: AnModule[];
  replaces: string | null;
  arms?: Record<string, string>;
  readings?: AnReading[];
  conflicts: {
    fires: { fire: string; resolution: string; note?: string }[];
    kernel: { kernel: string; resolution: string; note?: string }[];
    candidates: { other: string; relation: string; note?: string }[];
    slot_locks: { slot: string; dossier: string }[];
  };
  steps?: { n: number; do: string; slot: string; where: string[]; accept: string }[];
  kernel_forecast: string[];
  difficulty: { value: number };
  checks: AnCheck[];
  /** 确定性检查没过的条目（引擎 placement_problems）。 */
  problems: string[];
};
export type AnOrder = {
  order: { candidate: string; position: number; P: number; why: string; waits_for?: string[] }[];
  held: { candidate: string; why: string; note?: string }[];
};
export type AnHandoff = {
  decided_by?: string;
  date?: string;
  items: { candidate: string; title: string; module: string; slot: string; plain_summary: string }[];
  held: { candidate: string; why: string; note?: string }[];
  bang_updates: { op: string; id?: string; status?: string }[];
  profile_proposals: number;
  library_import: boolean;
  validator: AnCheck[];
};
export type AnDryRun = {
  auto_picked: string[];
  plain_summary: string;
  estimate: { tokens: Record<string, { in: number; out: number }>; minutes: number; budget_usd_milli?: number } | null;
  items: { candidate: string; statement: string; slot: string; replaces: string | null; kernel_forecast: string[]; difficulty?: number; likely_outcome: string; why: string; conflicts: string[]; /** 没过的检验连同原因；都过是空串（旧后端没有这一项）。 */ unpassed?: string }[];
  /** 自动取了但没有进入映射的做法（提炼不出）：empty 一栏都没有，incomplete 有内容但缺栏。旧产物没有这一栏。 */
  not_placed?: { candidate: string; kind: "empty" | "incomplete" | string; why: string }[];
  validators: AnCheck[];
};
export type AnReportKind = "G1" | "G2" | "G3" | "handoff" | "dry_run";
/** 引擎枚举的人读说法（服务端从引擎写报告的同一张表给出）。 */
export type AnWords = Record<"reading_kind" | "arm" | "resolution" | "relation" | "held" | "outcome", Record<string, string>>;

export type AnSubmitted = {
  run: string;
  gate: AnGate;
  deliver_seq: number;
  block: string;
  block_sha256: string;
  decision: AnDecision;
  budget_add_usd_milli: number;
  by: string;
  at: string;
  forwarded: boolean;
};

export type AnalysisDetail = AnalysisRow & {
  intake: { statement: string; sources: AnSource[]; max_candidates?: number; mode?: string; [k: string]: unknown } | null;
  engine: { fire?: string; gongfa_digest?: string };
  units: AnUnit[];
  spent: AnSpent;
  gates: AnGateRow[];
  relays: number;
  picked: string[];
  stage_share: Record<string, number>;
  needs: string[];
  candidates_doc: AnCandidatesDoc | null;
  essences: AnEssence[];
  placements: AnPlacement[];
  order: AnOrder | null;
  g3: { to_implementation: string[]; hold: Record<string, string>; exclude: Record<string, string>; library_import: boolean } | null;
  handoff: AnHandoff | null;
  dry_run: AnDryRun | null;
  words: AnWords;
  reports: { kind: AnReportKind; gate: AnGate | null; deliver_seq: number | null; text: string }[];
  observations: AnObservation[];
  artifacts: AnArtifact[];
  submitted: AnSubmitted[];
  history: AnSubmitted[];
};

export type AnArtifactView = { name: string; sha256: string; kind: AnArtifact["kind"]; content: unknown };
export type AnDecideBody = { block: string; deliver_seq: number; budget_add_usd_milli?: number };

export type BangStatus = "identified" | "dry_run" | "selected" | "handed_off" | "absorbed" | "rejected" | "excluded" | "superseded" | "reverted";
export type BangEntry = {
  id: string;
  title: string;
  essence?: string;
  fusion?: string;
  slot: string;
  also_slots?: string[];
  dims?: string[];
  source_kind?: string;
  license?: AnLicense;
  status: BangStatus | string;
  kernel_lines_expected?: number;
  priority?: number;
  dossier?: string;
  jie?: number;
  lessons?: string[];
  excluded_why?: string;
  analyses?: { run: string; date?: string; outcome?: string }[];
  history: { date: string; status: string; by?: string; note?: string }[];
};
export type BangView = { v: 1; entries: BangEntry[]; source: string | null };
