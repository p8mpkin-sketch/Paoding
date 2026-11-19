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
    role: NotRequired[str]  # bootstrap | reason | explore | verify | idler


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


class ScopeRule(TypedDict):
    resource: str
    pattern: str
    actions: list[str]
    risk: str  # r0 | r1 | r2


class VaultRef(TypedDict):
    vault: str
    digest: str


class Control(TypedDict):
    """对照判据（§3.3.3，N1）：同一份规格换这组输入再跑一次，结果必须相反。只用于观察类论断。"""

    inputs: list[str]  # ArtifactId；对照运行时按序写到 /workspace/inputs/1、2、…


class Check(TypedDict):
    """判据（I4 判据先行）：创建时登记，判官只能是这一个。"""

    judge_id: str
    spec_ref: NotRequired[str]
    expect: NotRequired[Any]
    sealed: NotRequired[list[VaultRef]]
    control: NotRequired[Control]


class Done(Check):
    """Intent 的完成判据：判据加候选次数上限。"""

    max_attempts: int


class Goal(TypedDict):
    statement: NotRequired[str]
    check: Check
    max_attempts: int
    accept: str  # M0 只有 judge


class Origin(TypedDict):
    statement_ref: str
    materials: list[str]


class Profile(TypedDict):
    info: str  # complete | partial
    judge: str  # hard | costly | deferred | none
    reversibility: str  # r0 | r1 | r2


class JudgeEntry(TypedDict):
    version: str
    grade: str  # decisive | consistent | advisory
    kind: str  # builtin | container | deferred
    max_cost: float


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
    terminal: NotRequired[str]  # solved | accepted | unsolved，关题时写入
    closed_seq: NotRequired[int]
    accepted: NotRequired[bool]  # 人的验收（M4 的 accept）；M0 没有写入方
    marks: NotRequired[list[int]]
    mark_seqs: NotRequired[list[int]]
    derived_profile: NotRequired[Profile]
    profile_overrides: NotRequired[list[ProfileOverride]]


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
        "class": str,  # exec | judge | input | authored
        "parents": list[str],
        "producer": Producer,
        "exec": NotRequired[Body],  # exec 与 judge 类的出处字段
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
    kind: str  # bootstrap | reason | explore | judge
    holder: str
    reserve: Amount
    ttl_s: int
    attempt: int
    issued_seq: int
    active: bool
    expires_at: int
    target: NotRequired[str]
    reflect: NotRequired[bool]
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
