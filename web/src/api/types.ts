// 线格式类型：图服务 HTTP 绑定的应答与请求（graph/SPEC.md「HTTP 绑定」，HMI 设计 §11.2）。
//
// 这份是手写的，对着真图服务录下的应答核过（tests/fixtures/real/，契约测试 tests/contract.test.ts）。
// HMI §14 要求类型由 Python 一侧导出的 JSON Schema 生成；导出就绪后本文件整体替换为生成物
// （docs/m0/dissent-web-f1.md 第 1 条）。

// ---------- 规格已定（§3.1.2、§3.2.2、§3.5.2） ----------

export type ArtifactId = string;
export type Risk = "r0" | "r1" | "r2";
export type Level = "E0" | "E1" | "E2" | "E3d" | "E3" | "X";
export type Terminal = "solved" | "accepted" | "unsolved";
export type Grade = "decisive" | "consistent" | "advisory";
export type ActorKind = "human" | "sinan" | "adapter" | "judge" | "executor" | "watchdog" | "graph";
export type Actor = { kind: ActorKind; id: string; session?: string; role?: string };

export type Event = {
  v: 1;
  seq: number;
  problem_id: string;
  ts: number;
  actor: Actor;
  kind: string;
  body: Record<string, unknown>;
  idem_key: string;
  prev_hash: string;
  hash: string;
};

export type Profile = {
  info: "complete" | "partial";
  judge: "hard" | "costly" | "deferred" | "none";
  reversibility: Risk;
};
export type Budget = { usd_milli: number; tokens?: number; wall_s: number };
export type VaultRef = { vault: string; digest: string };
export type Check = { judge_id: string; spec_ref?: ArtifactId; expect?: Record<string, unknown>; sealed?: VaultRef[] };
export type ScopeRule = { resource: string; pattern: string; actions: string[]; risk: Risk };

/** open_problem 的事件体。没有 profile 字段：画像是派生量，提交时不接受（HMI §3.2 强制点）。题目 id 在批次外层。 */
export type ProblemInput = {
  title: string;
  origin: { statement_ref: ArtifactId; materials: ArtifactId[] };
  goal: { statement: string; check: Check; max_attempts: number; accept: "judge" | "human" };
  scope: ScopeRule[];
  budget: Budget & { verify_share: number; bootstrap_share: number };
  env: { base: string; baseline_ref: string };
  judges: string[];
};

export type ArtifactClass = "exec" | "judge" | "input" | "authored";
export type ExecRecord = {
  sandbox_id: string;
  base: string;
  baseline_ref: string;
  tool: string;
  command: string;
  cwd: string;
  exit_code: number | null;
  touched: string[];
  started_at: number;
  ended_at: number;
  truncated: boolean;
};

// ---------- 读端点 ----------

export type RegisterName = "证据" | "叙述" | "人" | "估";
/** 凡文字内容都是这个形状。语域由服务端按出处类别查表给出；渲染只认 register，不看内容。 */
export type Tagged<T = string> = { src: string; register: RegisterName; value: T };

/** 视图端点的统一外壳。as_of 是这份投影对应的序号（全局 seq）；view_hash = sha256(JCS(视图))。 */
export type Envelope = { as_of: number; head: number; view_hash: string; state_hash?: string };

export type Badge = { judge_id: string; version: string | null; grade: Grade | null; kind: string | null; label: string };
export type VerdictRow = {
  seq: number;
  result: "pass" | "fail" | "inconclusive";
  judge: string;
  version: string;
  grade: Grade | null;
  candidate: ArtifactId | null;
  request: string;
  evidence: ArtifactId[];
};
/** 判据卡：Goal、带判据的 Intent、观察类论断同形。 */
export type Predicate = Badge & {
  target: string;
  spec_ref: ArtifactId | null;
  spec_hash: string | null;
  expect: Record<string, unknown>;
  sealed: VaultRef[];
  max_attempts: number | null;
  attempts_used: number | null;
  level: Level | null;
  level_word: string | null;
  fail_means: "refuted" | "not_yet";
  verdicts: VerdictRow[];
};

export type IntentState = "open" | "blocked" | "leased" | "done" | "achieved" | "needs_human" | "abandoned";
export type Decision = { decision: "approve" | "deny"; by: string; seq: number; reason: Tagged };

export type FactNode = {
  id: string;
  type: "fact";
  seq: number;
  claim_type: "observation" | "inference";
  level: Level;
  level_word: string;
  unstable: boolean;
  disputed: boolean;
  stale: boolean;
  title: Tagged;
  summary: Tagged;
  premises: string[];
  yielded_by: string | null;
  session: string | null;
  predicate: Predicate | null;
  grounds: ArtifactId[];
};
export type IntentNode = {
  id: string;
  type: "intent";
  seq: number;
  status: IntentState;
  risk: Risk;
  level: Level | null;
  level_word: string | null;
  title: Tagged;
  summary: Tagged;
  premises: string[];
  budget: Budget;
  session: string | null;
  needs_scope: ScopeRule[];
  gate: boolean;
  approvals: unknown[];
  attempts: number;
  predicate: Predicate | null;
  decision: Decision | null;
  expected_gain: Tagged<number> | null;
  leases?: string[];
};
export type HintNode = { id: string; type: "hint"; seq: number; ts: number | null; author: string; closed: boolean; about: string | null; text: Tagged };
export type GraphNode = FactNode | IntentNode;

export type GroundRef = { id: ArtifactId; class: ArtifactClass; src: string; register: RegisterName; hash: string; size: number };
export type FactEvidence = Omit<FactNode, "grounds"> & { problem_id: string; grounds: GroundRef[]; no_evidence_root: boolean; body_ref: ArtifactId | null };
/** no_evidence_root 是整条前提链上的“无证据根”（H6，裁决 005-4），由图服务算。 */
export type IntentEvidence = IntentNode & { problem_id: string; leases: string[]; no_evidence_root: boolean };
export type NodeEvidence = Envelope & (FactEvidence | IntentEvidence | (HintNode & { problem_id: string }));

export type LeaseRow = {
  id: string;
  kind: string;
  target?: string;
  holder: string;
  reserve: Budget;
  issued_seq: number;
  expires_at: number;
  active: boolean;
  outcome?: string;
  ended_seq?: number;
};

export type ProblemHead = {
  id: string;
  title: Tagged;
  closed: boolean;
  terminal: Terminal | null;
  terminal_badge: Badge;
  opened_seq: number;
  opened_ts: number;
  closed_seq: number | null;
  profile: Profile;
};
export type ProfileOverride = { axis: keyof Profile; value: string; derived: string | null; by: string; seq: number; reason: Tagged };
export type StatusView = Envelope & {
  problem: ProblemHead & {
    now_ts: number;
    derived_profile: Profile;
    profile_overrides: ProfileOverride[];
    scope: ScopeRule[];
    env: { base: string; baseline_ref: string };
    judges: string[];
    origin: { statement_ref: ArtifactId; materials: ArtifactId[] };
  };
  goal: { statement: Tagged; accept: "judge" | "human"; predicate: Predicate };
  facts: FactNode[];
  intents: IntentNode[];
  hints: HintNode[];
  leases: LeaseRow[];
  requests: { id: string; seq: number; target: string; judge_id: string; candidate: ArtifactId | null; verdict_seq: number | null }[];
  review: boolean;
  closeout: unknown[];
};

export type WorkItem =
  | { kind: "bootstrap" }
  | { kind: "reason"; reflect?: boolean }
  | { kind: "explore" | "judge"; target: string }
  | { kind: "rejudge"; target: string; judge: string; version: string; candidate: ArtifactId | null }
  /** why：needs_human（待审批的 Intent）、stalled（停滞，target 为题目 id）；M1 起还有续期门等。 */
  | { kind: "human"; target: string; why: string };
export type WorkView = Envelope & { items: WorkItem[] };

export type Frontier = {
  hints: string[];
  human: Extract<WorkItem, { kind: "human" }>[];
  disputed: string[];
  intents: string[];
  premises: string[];
  facts: string[];
};
export type GraphView = Envelope & { layer: string; items: unknown[]; next_after_seq: number | null; total: number; frontier: Frontier };

export type BudgetResponse = Envelope & {
  cap: Partial<Budget>;
  spent: Budget;
  reserved: Budget;
  by_kind: Record<string, Budget>;
  verify_spent: Budget;
  marks: number[];
  percent: { spent: number; committed: number };
  mark_lines: number[];
  mark_seqs: number[];
  verify_share: number;
  bootstrap_share: number;
  wall: { cap_s: number; elapsed_s: number };
  review: boolean;
};

export type ArtifactView = Envelope & {
  id: ArtifactId;
  problem_id: string;
  hash: string;
  size: number;
  media_type: string;
  class: ArtifactClass;
  parents: ArtifactId[];
  producer: { actor: string; session?: string };
  seq: number;
  src: string;
  register: RegisterName;
  exec: ExecRecord | null;
};

export type CardKind = "approval" | "closeout" | "extension" | "dispute";
export type CardResponse<F = Record<string, unknown>, D = Record<string, unknown>> = Envelope & {
  /** 进 card_hash 的部分：只含与这一个决定有关的字段（参考模型的投影）。 */
  card: { kind: CardKind; target: string; fields: F };
  card_hash: string;
  /** 排版用的附带信息，不进 card_hash；估值只在这里（I8）。 */
  display: D;
};
export type ApprovalFields = {
  risk: Risk;
  budget: unknown;
  done: unknown;
  tests: string[];
  needs_scope: unknown;
  rollback: unknown;
  premises: { id: string; level: Level; disputed: boolean; unstable: boolean; stale: boolean; controlled: boolean; waived: boolean }[];
};
export type ApprovalDisplay = {
  status: IntentState;
  title: Tagged;
  summary: Tagged;
  reserve: Budget;
  lease_note: string;
  rollback: Tagged | null;
  predicate: Predicate | null;
  premises: { id: string; type: "fact" | "intent"; level: Level | null; level_word: string | null; title: Tagged }[];
  disputes: unknown[];
  needs_scope: ScopeRule[];
  scope: ScopeRule[];
  expected_gain: Tagged<number> | null;
  rollback_declared: boolean;
  approve_enabled: boolean;
  decision: Decision | null;
};
/** 续期卡随 M1 落地（真图服务现在返回 not_enabled）；字段形状是 F1 的暂行约定。 */
export type ExtensionFields = { progress_since_50: string[]; spent_usd_milli: number; cap_usd_milli: number };

export type HintTrace = Envelope & {
  hint: HintNode;
  closed_seq: number | null;
  note: string;
  temporal: { added: string[]; abandoned: string[] };
  exposure: { sessions: string[]; added: string[]; abandoned: string[] } | null;
};

export type ProfilePreview = {
  profile: Profile;
  /** 每轴的推导依据：rule 加若干指针字段（scope_index、judge_id…），按键值原样列出。 */
  basis: Record<keyof Profile, Record<string, unknown>>;
};

export type JudgeEntry = { judge_id: string; version: string; grade: Grade; kind: string; max_cost: number };
export type CatalogItem = { name: string; hash: string; size: number; signature: string | null; data: unknown; text: string };
export type Catalog = { items: CatalogItem[] };

export type ProblemItem = ProblemHead & { spent_usd_milli: number; cap_usd_milli: number | null };
export type ProblemsView = Envelope & {
  items: ProblemItem[];
  totals: { problems: number; solved: number; spent_usd_milli: number; cost_per_solve_usd_milli: number | null };
};
export type EventsResponse = { events: Event[]; head: number; next_after: number };

// ---------- 合并读与刻度（P2-1） ----------

export type SnapshotPart = "status" | "view" | "budget" | "work";
/** 四份投影各自的 view_hash。事件流的 view 帧与 snapshot 应答都带它。 */
export type PartsHash = Record<SnapshotPart, string>;
/** GET /v1/problems/{pid}/snapshot：四份投影与单独的端点同形；`parts=` 只要其中几份。 */
export type SnapshotResponse = {
  as_of: number; head: number; view_hash: string; parts_hash: PartsHash;
  status?: StatusView; view?: GraphView; budget?: BudgetResponse; work?: WorkView;
};
/** 时间轴的一格：每条事件只有 seq、ts、种类；判官裁决另带 result，预算标记另带 mark。 */
export type WireTick = { seq: number; ts: number; kind: string; result?: "pass" | "fail" | "inconclusive"; mark?: number };
export type TicksResponse = { as_of: number; head: number; ticks: WireTick[]; last_seq: number; head_hash: string | null };
/** 事件流里一批事件之后的具名帧。 */
export type ViewFrame = { as_of: number; parts_hash: PartsHash };

// ---------- 写 ----------

export type HumanOpKind =
  | "open_problem"
  | "register_artifact"
  | "hint"
  | "approve"
  | "profile_override"
  | "abandon_intent"
  | "close_problem"
  // 以下随后续里程碑启用（规格 3.1.9）；M0 的图服务以 schema_error 拒绝
  | "add_intent"
  | "extend"
  | "budget_add"
  | "pause"
  | "resume"
  | "rule"
  | "accept"
  | "judge_revoke"
  | "intent_done";

export type Op = { op: HumanOpKind; body: Record<string, unknown> };
export type Seen = { seq: number; card_hash: string };
export type OpResult = { ok: true; id: string | null; seq: number } | { ok: false; code: string; detail?: string; card?: unknown };
export type ProposalResponse = { ok: boolean; results: OpResult[] };
export type ErrorBody = { ok: false; code: string; detail?: string };
