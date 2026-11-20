"""reducer 状态与事件的类型（规格 §3.1.2 的对象模型在 M0 的落地形状）。

这里只有类型，没有逻辑。状态必须是 JSON 值（状态哈希 = sha256(JCS(state))），所以全部用 TypedDict：
运行时仍是普通 dict，重放、哈希、序列化都不变；类型只给 mypy 看。

- 进状态的记录（Problem、Fact、Lease…）字段固定，这里逐个写明；可缺的字段用 NotRequired。
- 提议方交来的 body 是未经校验的 JSON，类型是 `Body`（dict[str, Any]）；validate 负责把它变成规范化的事件体。
- 规格里的 Support（支持记录）在 M0 只有一种来源：判官裁决。所以 `Support` 就是 `Verdict`；
  复审与反证带来的其它支持记录随 M1 加进来。
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

Body = dict[str, Any]  # 未经校验的提议体，或规范化后的事件体
Level = str  # E0 | E1 | E2 | E3 | E3d | X（等级不存储，每次读时重算，I3）


class Actor(TypedDict):
    kind: str  # human | sinan | adapter | judge | executor | watchdog | graph
    id: str
    session: NotRequired[str]  # 任务令牌才有：会话即租约 id
    role: NotRequired[str]  # bootstrap | reason | explore | solve | verify | idler


class Event(TypedDict):
    v: int
    seq: int
    problem_id: str
    ts: int
    actor: Actor
    kind: str
    body: Body
    idem_key: str
    prev_hash: str
    hash: str


class Amount(TypedDict):
    """预算的三条轨：金额（毫美元）、token、墙钟秒。"""

    usd_milli: int
    wall_s: int
    tokens: NotRequired[int]


class ProblemBudget(TypedDict):
    usd_milli: int
    wall_s: int
    verify_share: float
    bootstrap_share: float
    tokens: NotRequired[int]


class Granted(TypedDict):
    """运行时扩权批下来的规则的出处（设计 runtime-grants §4.2）：哪条事件、谁批的、批的哪条申请。"""

    seq: int
    by: str  # 人的 id，或 graph（练习道白名单、随 Intent 审批）
    request: str


class ScopeRule(TypedDict):
    resource: str
    pattern: str
    actions: list[str]
    risk: str  # r0 | r1 | r2
    granted: NotRequired[Granted]  # 开题时写下的规则没有
    revoked: NotRequired[int]  # 撤销事件的 seq；编译跳过，下标不变（touches 按下标引用）


class ScopeRequest(TypedDict):
    """扩权申请（runtime-grants §4.1）：申请不是授权，批准只来自人或确定性的练习道白名单。"""

    id: str
    problem_id: str
    rules: list[ScopeRule]  # risk 由图服务查风险表填，不信自报
    why: str  # 申请方写的理由；模型语域，不作证据
    auto: bool  # 写入时的练习道白名单判定
    blockers: NotRequired[list[str]]  # 不能自动批准的原因（卡上照写）
    status: str  # pending | granted | denied
    by: str
    session: str | None
    role: NotRequired[str]  # 申请方会话的角色（bootstrap | reason | explore）
    seq: int
    risk_from: NotRequired[list[int | None]]  # 逐条：风险表命中的行号（从 0 起），null 即未命中、按缺省 r2
    intent: NotRequired[str]  # 随 needs_scope 而来的申请
    decided_seq: NotRequired[int]
    decided_by: NotRequired[str]
    via: NotRequired[str]  # 图服务批准时：auto（练习道白名单）| readonly（只读白名单）| approval（随 Intent 的审批）
    policy: NotRequired[dict[str, Any]]  # via=auto 时的信封戳 {version, digest}
    readonly: NotRequired[dict[str, Any]]  # 写入时命中只读白名单（地图 Q36）：白名单戳 {version, digest}
    reason: NotRequired[str]


class VaultRef(TypedDict):
    vault: str
    digest: str


class Control(TypedDict):
    """对照判据（§3.3.3，N1）：同一份规格换这组输入再跑一次，结果必须相反。只用于观察类论断。"""

    inputs: list[str]  # ArtifactId；对照运行时按序写到 /workspace/inputs/1、2、…


class Binding(TypedDict):
    """外部裁决的绑定单（定源登记）：判定程序随开题登记、之后不可改；值（回执）运行时经连接器交付。"""

    connector: str  # 连接器档案 id，须与判官快照里的连接器相同
    task: str  # 平台任务号（不透明的串，内核不解释）
    max_submissions: int  # 平台的提交额度；goal.max_attempts 不得超过它


class Check(TypedDict):
    """判据（I4 判据先行）：创建时登记，判官只能是这一个。"""

    judge_id: str
    spec_ref: NotRequired[str]
    expect: NotRequired[Any]
    sealed: NotRequired[list[VaultRef]]
    control: NotRequired[Control]
    binding: NotRequired[Binding]  # 外部裁决（external-verdict §5.2）：只在 Goal 判官的 authority 为 external 时


class Done(Check):
    """Intent 的完成判据：判据加候选次数上限。"""

    max_attempts: int


class Goal(TypedDict):
    statement: NotRequired[str]
    check: NotRequired[Check]  # 开放道（accept=open）没有：Goal 不设判官（docs/design/open-lane/ §8）
    max_attempts: NotRequired[int]  # 同上：开放道没有判官，也就没有候选次数
    accept: str  # judge | human | open
    authority: NotRequired[str]  # 派生，不接受提交：external、human 时写入；缺省即 local（external-verdict §4.2）
    acceptance: NotRequired[list[Body]]  # accept=human 的验收清单（设计 02 §3.3）：开题时登记，之后不可改
    self_checks: NotRequired[list[Body]]  # 开放道的必做自检项 {id, text, src}：原文里的检查命令（open-lane §4.2）


class DraftRef(TypedDict):
    record: str  # 出处账（input 类 Artifact）
    lane: str  # practice | confirm | open
    policy: NotRequired[dict[str, Any]]  # 练习道：图服务抄入的信封 {version, digest}


class Origin(TypedDict):
    statement_ref: str
    materials: list[str]
    draft: NotRequired[DraftRef]


class Profile(TypedDict):
    info: str  # complete | partial
    judge: str  # hard | costly | deferred | none
    reversibility: str  # r0 | r1 | r2


class JudgeEntry(TypedDict):
    version: str
    grade: str  # decisive | consistent | advisory
    kind: str  # builtin | container | deferred
    max_cost: float
    authority: NotRequired[str]  # external 时写入；缺省 local（external-verdict §5.1）
    connector: NotRequired[dict[str, str]]  # authority=external：连接器档案 {id, version, digest}，开题时抄入


class ProfileOverride(TypedDict):
    axis: str
    value: str
    reason: str
    derived: str
    seq: int
    by: str


class Problem(TypedDict):
    id: str
    title: str
    origin: Origin
    goal: Goal
    scope: list[ScopeRule]
    budget: ProblemBudget
    env: Body
    judges: list[str]
    judge_snapshot: dict[str, JudgeEntry]
    profile: Profile
    closed: bool
    opened_seq: int
    opened_ts: int
    terminal: NotRequired[str]  # solved | accepted | delivered | unsolved，关题时写入
    closed_seq: NotRequired[int]
    accepted: NotRequired[bool]  # 人的验收（accept 操作，宪章 D3）：只在 goal.accept = human 的题上写入
    accept_log: NotRequired[
        list[Body]
    ]  # 每次 accept 操作（验收或拒收）：{seq, decision, checks, reason?}；拒收之后要等新的 Goal 通过
    deliveries: NotRequired[list[Body]]  # 开放道的交付（deliver 操作，open-lane §3.4），按 seq 递增
    follow_ups: NotRequired[list[Body]]  # 开放道的追问（follow_up，地图 Q31）：{id, seq, ts, text, after_delivery}
    halted: NotRequired[Body]  # 开放道的叫停（halt，地图 Q20）：{seq, ts, reason?}；之后的追问解除它
    idle_close_s: NotRequired[int]  # 开放道交付后闲置多久自动关（地图 Q33），开题时由设置抄进事件体
    feedback: NotRequired[str]  # 开放道关题时人的反馈 adopted | rejected | none；不是终态（裁决 §12 第 6 条）
    marks: NotRequired[list[int]]
    mark_seqs: NotRequired[list[int]]
    derived_profile: NotRequired[Profile]
    profile_overrides: NotRequired[list[ProfileOverride]]
    deadline: NotRequired[Body]  # external-verdict §5.6：{source: local|external, at?, bound_by?}；at 只绑定一次
    wall_mode: NotRequired[str]  # elapsed | spend，开题时由图服务按设置抄入；缺省 elapsed（旧行为）
    life_s: NotRequired[int]  # wall_mode=spend：题的最长存活（全局设置，开题时抄入）
    prefs: NotRequired[Body]  # 任务级偏好 {model?}（宪章 03 §3.1、地图 Q12）：不进等级、消费门与画像
    labels: NotRequired[Body]  # v1.5 增量 10：{tags, env?}，env 即通鉴的环境键；不进等级与画像
    recall: NotRequired[Body]  # v1.5 增量 9：召回清单 {items, excluded_by_human, match_digest, mode?, notes?}
    shelf: NotRequired[Body]  # curate（v5 第三期）：{state: active|archived|trash, seq, ts}；软删，不动账
    renamed: NotRequired[list[Body]]  # curate 改名：[{seq, from}]，title 是现在的显示名
    pinned: NotRequired[bool]  # curate 置顶
    settings: NotRequired[Body]  # 宪章 D5：{version, digest}，开题时的设置快照；不进等级、消费门与画像
    gongfa: NotRequired[Body]  # 焚决 F3：{jie, digest}，开题时的功法；同 settings，只记不解释


class Producer(TypedDict):
    actor: str
    session: NotRequired[str]


Artifact = TypedDict(
    "Artifact",
    {  # "class" 是关键字，只能用函数式写法
        "id": str,
        "problem_id": str,
        "hash": str,
        "size": int,
        "media_type": str,
        "class": str,  # exec | judge | input | authored | knowledge
        "parents": list[str],
        "producer": Producer,
        "exec": NotRequired[Body],  # exec 与 judge 类的出处字段
        "knowledge": NotRequired[Body],  # knowledge 类：{source, revision, chunk, locator}（资料库第二期）
    },
)


class Fact(TypedDict):
    id: str
    problem_id: str
    title: str
    summary: str
    claim_type: str  # observation | inference
    premises: list[str]
    grounds: list[str]
    session: str | None
    check: NotRequired[Check]
    body_ref: NotRequired[str]
    yielded_by: NotRequired[str]  # 由租约推出，不由提议方填写


class Rollback(TypedDict):
    text: str
    done: NotRequired[Check]


class Touch(TypedDict):
    """资源占用（v1.5，增量 11）：Problem.scope 的下标与读写模式。"""

    rule: int
    mode: str  # read | write


class Intent(TypedDict):
    id: str
    problem_id: str
    title: str
    summary: str
    premises: list[str]
    risk: str
    budget: Amount
    session: str | None
    done: NotRequired[Done]
    needs_scope: NotRequired[list[ScopeRule]]
    expected_gain: NotRequired[float]  # 估值，只供司南排序（I8）
    touches: NotRequired[list[Touch]]  # M2：只许收窄能力；缺省按 work.holds 保守展开
    rollback: NotRequired[Rollback]  # M4；M0 的内核不接受


class Request(TypedDict):
    """判官请求。"""

    id: str
    problem_id: str
    target: str
    judge_id: str
    candidate: str | None
    verdict_seq: NotRequired[int]
    inconclusive: NotRequired[str]
    recheck_at: NotRequired[int]  # inconclusive(pending)：延迟判官下次读回执的时刻（毫秒）
    control_end: NotRequired[str]


class Verdict(TypedDict):
    """进裁决序列的判官裁决（无结论的不进）。等级只由它重算。"""

    seq: int
    problem_id: str
    target: str
    judge: str
    version: str
    grade: str
    result: str  # pass | fail | flaky
    candidate: str | None
    request: str
    evidence: list[str]
    controlled: NotRequired[bool]  # 判据带对照且主运行通过、对照不通过
    control_end: NotRequired[str]  # 对照运行的结束类别，供 §8.5 的对照质量抽样


Support = Verdict  # M0 的支持记录只有判官裁决一种


class Lease(TypedDict):
    id: str
    problem_id: str
    kind: str  # bootstrap | reason | explore | judge | recall（v1.5）
    holder: str
    reserve: Amount
    ttl_s: int
    attempt: int
    issued_seq: int
    active: bool
    expires_at: int
    target: NotRequired[str]
    reflect: NotRequired[bool]
    form: NotRequired[str]  # 焚决 F3：会话形态 "id@ver"，领租约时由图服务抄入；旧租约没有，读端按席位推
    outcome: NotRequired[str]
    ended_seq: NotRequired[int]
    transcript_ref: NotRequired[str]


class Hint(TypedDict):
    id: str
    problem_id: str
    seq: int
    ts: int
    author: str
    closed: bool
    text: str
    about: NotRequired[str]


class Cost(TypedDict):
    problem_id: str
    seq: int
    task_id: str
    lease_kind: str
    source: str  # proxy | judge | cli_reported
    tokens_in: int
    tokens_cached: int
    tokens_out: int
    usd_milli: int
    wall_s: int
    price_table: str
    model: NotRequired[str]
    tokens_cached_unknown: NotRequired[bool]


class DecisionReason(TypedDict):
    decision: str
    reason: str
    by: str
    seq: int


class State(TypedDict):
    problems: dict[str, Problem]
    artifacts: dict[str, Artifact]
    facts: dict[str, Fact]
    intents: dict[str, Intent]
    requests: dict[str, Request]
    verdicts: list[Verdict]
    content_keys: dict[str, dict[str, str]]  # 题 → 内容键 → 论断 id
    revoked: list[list[str]]  # 被撤销的 (判官, 版本)；M0 没有写入方
    approvals: dict[str, list[int]]  # Intent → 批准事件的 seq
    lease_seqs: dict[str, list[int]]  # Intent → explore 租约签发的 seq
    abandoned: list[str]
    leases: dict[str, Lease]
    hints: dict[str, Hint]
    costs: list[Cost]
    now: int  # 最后一条事件的 ts
    seq: int
    decision_reasons: NotRequired[dict[str, DecisionReason]]
    scope_requests: NotRequired[dict[str, ScopeRequest]]  # 第一条扩权申请时才出现，旧日志的状态哈希不变
