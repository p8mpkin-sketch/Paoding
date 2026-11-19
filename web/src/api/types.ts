// 线格式类型：图服务 HTTP 绑定的应答与请求（graph/SPEC.md「HTTP 绑定」，HMI 设计 §11.2、§14）。
//
// 本文件是生成物，不要手改：改 graph/src/paoding_graph/wire_schema.py，再跑
//   uv run python scripts/gen-types.py
// CI 用 --check 比对；图服务的测试用同一份 schema 严格校验真应答。

// ---------- 规格已定（§3.1.2、§3.2.2、§3.5.2） ----------

export type ArtifactId = string;
export type Risk = "r0" | "r1" | "r2";
export type Level = "E0" | "E1" | "E2" | "E3d" | "E3" | "X";
/** delivered 只来自开放道的交付（docs/design/open-lane/ §5.1）：未经判定，永不计入 solved。 */
export type Terminal = "solved" | "accepted" | "delivered" | "unsolved";
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
export type Profile = { info: "complete" | "partial"; judge: "hard" | "costly" | "deferred" | "none"; reversibility: Risk };
export type ProfileAxis = "info" | "judge" | "reversibility";
export type Budget = { usd_milli: number; wall_s: number; tokens?: number };
export type VaultRef = { vault: string; digest: string };
/** 对照判据（§3.3.3）：同规格、异输入，只用于观察类论断。 */
export type Control = { inputs: ArtifactId[] };
export type Check = {
  judge_id: string;
  spec_ref?: ArtifactId;
  expect?: Record<string, unknown>;
  sealed?: VaultRef[];
  control?: Control;
};
/** 运行时扩权追加的规则带 granted（谁在哪个序号按哪条申请批的）；撤销的规则留在原位、带 revoked 序号。 */
export type ScopeRule = {
  resource: string;
  pattern: string;
  actions: string[];
  risk: Risk;
  granted?: { seq: number; by: string; request: string };
  revoked?: number;
};
/** 一句话开题的出处账引用与道别（增量 13）；policy 只在练习道，由图服务从信封抄入。 */
export type DraftRef = { record: ArtifactId; lane: "practice" | "confirm" | "open"; policy?: { version: number; digest: string } };
export type Origin = { statement_ref: ArtifactId; materials: ArtifactId[]; draft?: DraftRef };
export type Env = { base: string; baseline_ref: string };
/** 验收清单的一条（宪章 D3、02 §3.3）：只许原文区间或人写；编号由图服务分配，提交时不接受。 */
export type AcceptanceInput = { text: string; src: "span" | "human"; needs?: "artifact" | "note" };
export type AcceptanceItem = AcceptanceInput & { id: string };
export type Authority = "local" | "external" | "human" | "self";
/** 按判定来源分列的计数（external-verdict §5.7、宪章裁决附加 1）：accepted 只出现在 human 一行，delivered 只出现在 self 一行（开放道，open-lane §5.2）。 */
export type AuthorityTally = { problems: number; solved: number; accepted: number; delivered: number; unsolved: number; open: number };
export type AcceptCheck = { id: string; verdict: "pass" | "fail"; ref?: ArtifactId; note?: string };
export type AcceptRecord = { seq: number; decision: "accept" | "reject"; checks: AcceptCheck[]; reason?: string };
/** 任务级偏好（宪章 03 §3.1）：model 为设置页已登记的模型档案名。 */
export type TaskPrefs = { model?: string };
/** 开放道的必做自检项（open-lane §4.2）：原文里的检查命令；会话交付前自己跑、如实报告，判官不重放。 */
export type SelfCheckInput = { text: string; src: "span" | "human" };
export type SelfCheckItem = SelfCheckInput & { id: string };
/** open_problem 的事件体。没有 profile 字段：画像是派生量，提交时不接受（HMI §3.2 强制点）。题目 id 在批次外层。 */
export type ProblemInput = {
  title: string;
  origin: Origin;
  goal: {
    statement: string;
    accept: "judge" | "human" | "open";
    /** 判定道必填；开放道（accept=open）没有 */
    check?: Check;
    /** 判定道必填；开放道没有 */
    max_attempts?: number;
    acceptance?: AcceptanceInput[];
    self_checks?: SelfCheckInput[];
  };
  scope: ScopeRule[];
  budget: Budget & { verify_share: number; bootstrap_share: number };
  env: Env;
  judges: string[];
  prefs?: TaskPrefs;
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
  killed?: string | null;
  stdout_ref?: string | null;
  stderr_ref?: string | null;
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
/** 论断的公共部分；grounds 的形状随层而变。 */
export type FactBase = {
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
};
export type FactNode = FactBase & { grounds: ArtifactId[] };
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
export type HintNode = {
  id: string;
  type: "hint";
  seq: number;
  /** Hint 事件的 ts（裁决 005-7） */
  ts: number | null;
  author: string;
  closed: boolean;
  about: string | null;
  text: Tagged;
};
export type GraphNode = FactNode | IntentNode;
export type GroundRef = { id: ArtifactId; class: ArtifactClass; src: string; register: RegisterName; hash: string; size: number };
export type FactEvidence = FactBase & {
  problem_id: string;
  grounds: GroundRef[];
  /** 整条前提链上的“无证据根”（H6，裁决 005-4），由图服务算。 */
  no_evidence_root: boolean;
  body_ref: ArtifactId | null;
};
export type IntentEvidence = IntentNode & {
  problem_id: string;
  leases: string[];
  /** 整条前提链上的“无证据根”（H6，裁决 005-4），由图服务算。 */
  no_evidence_root: boolean;
};
export type HintEvidence = HintNode & { problem_id: string };
export type NodeEvidence = Envelope & (FactEvidence | IntentEvidence | HintEvidence);
export type LeaseRow = {
  id: string;
  kind: string;
  holder: string;
  reserve: Budget;
  issued_seq: number;
  expires_at: number;
  active: boolean;
  target?: string;
  outcome?: string;
  ended_seq?: number;
  transcript_ref?: string | null;
  reflect?: boolean;
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
export type ProfileOverride = { axis: ProfileAxis; value: string; derived: string | null; by: string; seq: number; reason: Tagged };
export type JudgeRequestRow = {
  id: string;
  seq: number;
  target: string;
  judge_id: string;
  candidate: ArtifactId | null;
  verdict_seq: number | null;
};
export type StatusView = Envelope & {
  problem: ProblemHead & {
    now_ts: number;
    derived_profile: Profile;
    profile_overrides: ProfileOverride[];
    scope: ScopeRule[];
    env: Env;
    judges: string[];
    origin: Origin;
    prefs?: TaskPrefs;
  };
  goal: {
    statement: Tagged;
    accept: "judge" | "human" | "open";
    /** 开放道的判据卡是空的：没有判官、等级与裁决 */
    predicate: Predicate;
    /** 判定来源；缺省即 local */
    authority?: Authority;
    acceptance?: AcceptanceItem[];
    acceptance_ready?: number | null;
    accept_log?: AcceptRecord[];
    self_checks?: SelfCheckItem[];
    deliveries?: Delivery[];
    feedback?: "adopted" | "rejected" | "none";
  };
  facts: FactNode[];
  intents: IntentNode[];
  hints: HintNode[];
  leases: LeaseRow[];
  requests: JudgeRequestRow[];
  review: boolean;
  closeout: unknown[];
};
export type GroundBrief = { id: ArtifactId; class: ArtifactClass };
/** 开放道的一次交付（open-lane §3.4）。内核只校验依据真实存在、类别可采信，不校验结论对不对；supported=false 即这条主张没有任何留档支撑。 */
export type Delivery = {
  id: string;
  seq: number;
  lease: string;
  outcome: "answered" | "partial" | "blocked";
  answer: ArtifactId | null;
  claims: { text: Tagged; refs: GroundBrief[]; supported: boolean }[];
  self_check: { what: Tagged; result: "pass" | "fail" | "skipped"; refs: GroundBrief[]; item?: string }[];
  unverified: Tagged[];
  needs: Tagged[];
};
/** why：needs_human（待审批的 Intent）、stalled（停滞，target 为题目 id）；开放道另有 delivered、blocked（交付了，等人看）；M1 起还有续期门等。 */
export type HumanWorkItem = { kind: "human"; target: string; why: string };
export type WorkItem =
  | { kind: "bootstrap" | "recall" | "solve" }
  | { kind: "reason"; reflect?: boolean }
  | { kind: "explore" | "judge"; target: string }
  | { kind: "rejudge"; target: string; judge: string; version: string; candidate: ArtifactId | null }
  | HumanWorkItem;
export type WorkView = Envelope & { items: WorkItem[] };
export type Frontier = {
  hints: string[];
  human: HumanWorkItem[];
  disputed: string[];
  intents: string[];
  premises: string[];
  facts: string[];
};
export type GraphView = Envelope & { layer: string; items: unknown[]; next_after_seq: number | null; total: number; frontier: Frontier };
/** 题预算上限；没设的轴不出现。 */
export type BudgetCap = { usd_milli?: number; tokens?: number; wall_s?: number };
export type BudgetResponse = Envelope & {
  cap: BudgetCap;
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
export type CardKind = "approval" | "closeout" | "extension" | "dispute" | "scope";
export type CardResponse<F = Record<string, unknown>, D = Record<string, unknown>> = Envelope & {
  /** 进 card_hash 的部分：只含与这一个决定有关的字段（参考模型的投影）。 */
  card: { kind: CardKind; target: string; fields: F };
  card_hash: string;
  /** 排版用的附带信息，不进 card_hash；估值只在这里（I8）。 */
  display: D;
};
export type ApprovalPremise = {
  id: string;
  level: Level;
  disputed: boolean;
  unstable: boolean;
  stale: boolean;
  controlled: boolean;
  waived: boolean;
};
export type ApprovalFields = {
  risk: Risk;
  budget: unknown;
  done: unknown;
  tests: string[];
  needs_scope: unknown;
  rollback: unknown;
  premises: ApprovalPremise[];
};
export type DisplayPremise = { id: string; type: "fact" | "intent"; level: Level | null; level_word: string | null; title: Tagged };
export type ApprovalDisplay = {
  status: IntentState;
  title: Tagged;
  summary: Tagged;
  reserve: Budget;
  lease_note: string;
  rollback: Tagged | null;
  predicate: Predicate | null;
  premises: DisplayPremise[];
  disputes: unknown[];
  needs_scope: ScopeRule[];
  scope: ScopeRule[];
  expected_gain: Tagged<number> | null;
  rollback_declared: boolean;
  approve_enabled: boolean;
  decision: Decision | null;
};
/** 扩权卡进 card_hash 的部分（runtime-grants §7.1）：申请的规则（风险已查表）、理由、现有有效范围。 */
export type ScopeCardFields = {
  rules: ScopeRule[];
  why: string;
  status: "pending" | "granted" | "denied";
  auto: boolean;
  scope: ScopeRule[];
  closed: boolean;
};
export type ScopeDecision = {
  decision: "approve" | "deny";
  by: string | null;
  seq: number | null;
  via: ("auto" | "approval") | null;
  policy_version: number | null;
  reason: Tagged;
};
export type ScopeDisplay = {
  status: "pending" | "granted" | "denied";
  why: Tagged;
  by: string;
  session: string | null;
  role: string | null;
  intent: string | null;
  auto: boolean;
  blockers: string[];
  /** 逐条：风险表命中的行号（从 1 起），null 即未命中、按缺省 r2；旧事件整项为 null。 */
  risk_rows: (number | null)[] | null;
  /** 批准前后的画像（与开题同一个推导函数）；已决定的申请为 null。 */
  profile: { before: Profile; after: Profile; overridden: string[] } | null;
  risk_choices: Risk[];
  approve_enabled: boolean;
  decision: ScopeDecision | null;
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
  basis: { info: Record<string, unknown>; judge: Record<string, unknown>; reversibility: Record<string, unknown> };
};
export type JudgeEntry = { judge_id: string; version: string; grade: Grade; kind: string; max_cost: number };
export type JudgesResponse = { items: JudgeEntry[]; external_resources: string[] };
export type CatalogItem = { name: string; hash: string; size: number; signature: string | null; data: unknown; text: string };
export type Catalog = { items: CatalogItem[] };
export type ProblemItem = ProblemHead & {
  spent_usd_milli: number;
  cap_usd_milli: number | null;
  closed_ts: number | null;
  goal_level: Level | null;
  active: { kind: string; target?: string }[];
  human_todo: number;
  wall: { cap_s: number; elapsed_s: number };
  authority: Authority;
};
export type ProblemsView = Envelope & {
  items: ProblemItem[];
  totals: {
    problems: number;
    /** 只数本地判定的 solved；外部判定与人工验收见 by_authority */
    solved: number;
    spent_usd_milli: number;
    /** 全部花费 ÷ 本地判定的 solved */
    cost_per_solve_usd_milli: number | null;
    by_authority: { local: AuthorityTally; external: AuthorityTally; human: AuthorityTally; self: AuthorityTally };
  };
};
export type EventsResponse = { events: Event[]; head: number; next_after: number };
export type HealthResponse = { ok: boolean; head: number; api: string };

// ---------- 合并读与刻度（P2-1） ----------

export type SnapshotPart = "status" | "view" | "budget" | "work";
/** 四份投影各自的 view_hash。事件流的 view 帧与 snapshot 应答都带它。 */
export type PartsHash = { status: string; view: string; budget: string; work: string };
/** GET /v1/problems/{pid}/snapshot：四份投影与单独的端点同形；`parts=` 只要其中几份。 */
export type SnapshotResponse = {
  as_of: number;
  head: number;
  view_hash: string;
  parts_hash: PartsHash;
  status?: StatusView;
  view?: GraphView;
  budget?: BudgetResponse;
  work?: WorkView;
};
/** 时间轴的一格：每条事件只有 seq、ts、种类；判官裁决另带 result，预算标记另带 mark；扩权的批准与拒绝（grant_scope）另带 decision，图服务批准时带 via，自动批准带信封版本 policy_version。 */
export type WireTick = {
  seq: number;
  ts: number;
  kind: string;
  result?: "pass" | "fail" | "inconclusive";
  mark?: number;
  decision?: string;
  via?: string;
  policy_version?: number;
};
export type TicksResponse = { as_of: number; head: number; ticks: WireTick[]; last_seq: number; head_hash: string | null };
/** 事件流里一批事件之后的具名帧。 */
export type ViewFrame = { as_of: number; parts_hash: PartsHash };

// ---------- 写 ----------

/** add_intent 之后的几种随后续里程碑启用（规格 3.1.9）；M0 的图服务以 schema_error 拒绝。 */
export type HumanOpKind =
  | "open_problem"
  | "register_artifact"
  | "hint"
  | "approve"
  | "profile_override"
  | "abandon_intent"
  | "close_problem"
  | "add_intent"
  | "extend"
  | "budget_add"
  | "pause"
  | "resume"
  | "rule"
  | "accept"
  | "judge_revoke"
  | "intent_done"
  | "grant_scope"
  | "revoke_scope";
export type Op = { op: HumanOpKind; body: Record<string, unknown> };
export type Seen = { seq: number; card_hash: string };
export type OpResult = { ok: true; id: string | null; seq: number } | { ok: false; code: string; detail?: string; card?: unknown; as_of?: number };
export type ProposalResponse = { ok: boolean; results: OpResult[]; id?: string };
export type ErrorBody = { ok: false; code: string; detail?: string };
