// GET /v1/evolution（焚决 04 §7，读端 paoding_fenjue.evolution）：能力配置的版本史、集成记录与结局统计、Holdout 对照。
// 只读；读数不驱动任何默认值。线格式手写（不在 wire_schema 里：它是组装根的端点，不是内核的）。

export type EvoOutcome = "huolian" | "helian" | "buji" | "binghuo" | "fanshi";
export type EvoStatus = "identified" | "distilled" | "placed" | "design_approved" | "trialed" | "readings_ready" | "adopted" | "rejected" | "reverted";

/** 一组任务的读数：做成 = 判定通过、人工验收、开放道交付；比率与平均只看已结束的。 */
export type EvoStats = {
  tasks: number;
  open: number;
  closed: number;
  done: number;
  done_rate: number | null;
  spent_usd_milli: number;
  avg_spent_usd_milli: number | null;
  avg_wall_s: number | null;
};

export type EvoHistory = { jie: number; change: string; dossier?: string; replaces?: string; reverts?: string };
export type EvoRevision = { fire: string; from: string | null; change: string };
export type EvoVersion = EvoStats & { jie: number; digest: string | null; current: boolean; repinned?: boolean };

export type EvoReading = { dim: string; kind: string; dir?: string; B?: number; A1?: number; F?: number; gate?: number; verdict?: string };
export type EvoDossier = {
  dossier: string;
  name: string;
  title: string;
  status: EvoStatus;
  identified: string;
  fire: string | null;
  slot: string | null;
  replaces: string[];
  kernel_lines_changed: number | null;
  outcome_proposed: EvoOutcome | null;
  jie_proposed: number | null;
  verdict: { by: string; date: string; outcome: EvoOutcome; jie?: number; conditions?: string[]; basis?: string } | null;
  reverts: { by?: string; date?: string; why?: string; back_to?: string }[];
  readings: EvoReading[];
};

export type EvoHoldout = {
  slot: string;
  holdout: string;
  active: string;
  dossier: string | null;
  live: boolean;
  retire_signal: string | null;
  control_arm: string | null;
  main: EvoStats;
  held: EvoStats;
};

export type Evolution = {
  current: { jie: number; digest: string; holdout_permille: number; fires: Record<string, string[]> };
  history: EvoHistory[];
  /** 功法存档里的每一版（体质修炼 003：改钉只许改到这里有的版本）。 */
  archive?: { jie: number; digest: string; current: boolean }[];
  revisions: EvoRevision[];
  versions: EvoVersion[];
  dossiers: EvoDossier[];
  outcomes: Record<EvoOutcome, number> & { decided: number; pending: number; reverted: number };
  holdout: EvoHoldout[];
  as_of: number;
};
