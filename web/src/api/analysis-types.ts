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
  [k: string]: unknown;
};
export type AnGateRow = { gate: AnGate; deliver_seq: number; follow_up_seq?: number; decision?: AnDecision };
export type AnArtifact = { name: string; sha256: string; kind: "material" | "exec" | "analysis"; bytes: number };

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
  reports: { gate: AnGate; deliver_seq: number | null; text: string }[];
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
