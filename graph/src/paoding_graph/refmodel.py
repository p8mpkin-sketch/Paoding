"""庖丁基座规格 v1.3 的可执行参考模型。

只覆盖内核里"由日志派生"的语义：裁决序列与翻转迟滞、等级函数与最小不动点重算、
消费门、Intent 的资格状态、失效集合、引用的可采信检查；v1.2 起加上判官资产的两级可见性、
终态三值、难点标记 knot 与关节度；v1.3 起加上对照判据进消费门、封存校验、预测账的校准投影、
常设留出的互斥分配、"估值不进等级"所需的估值类记录，以及人的决策与所见的绑定（审批卡的投影哈希、
stale_view）和 r2 的回退声明。
它不是 M0 的代码库：没有事件日志、存储、租约生命周期、预算、容器。全部是纯函数，只用标准库。
每个函数注明它对应规格的哪一节；规格与本文件不一致时，以规格为准并修正本文件。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional, Sequence

LEVELS = ("E0", "E1", "E2", "E3d", "E3")          # 全序；X 单列
RANK = {name: i for i, name in enumerate(LEVELS)}
X = "X"
INF = len(LEVELS)                                 # 没有前提的支持，strength 记为 ∞

ADMISSIBLE = frozenset({"exec", "judge", "input"})             # 可作证据的出处类别（3.2.2）
REGISTRAR = {"exec": "executor", "judge": "judge", "input": "human", "authored": "adapter"}
VAULT = "vault:"                                               # 含密级判官资产的引用前缀（3.3.2）
OUTCOME_FAIL = frozenset({"failed", "nothing"})                # 算作"这一刀没下去"的租约结束方式（3.1.7）


# ---------- 记录 ----------

@dataclass(frozen=True)
class Artifact:
    id: str
    cls: str                               # exec | judge | input | authored
    problem: str = "p1"
    touched: tuple = ()                    # 访问摘要；判官解引用过的保密库键也记在这里


@dataclass(frozen=True)
class Fact:
    id: str
    claim_type: str = "observation"        # observation | inference
    premises: tuple = ()                   # Fact id，或带判据的 Intent 的 id
    session: str = ""                      # 提出者的会话，即租约 id
    body_ref: Optional[str] = None         # 第三层正文
    control: bool = False                  # 判据带对照（3.3.3）：同规格、异输入，判官要求对照不通过


@dataclass(frozen=True)
class Intent:
    id: str
    risk: str = "r0"                       # r0 | r1 | r2
    premises: tuple = ()
    done: Optional[str] = None             # 带判据的 Intent：判据所用判官的 id
    tests: tuple = ()                      # done.tests：这条判据所检验的推断类前提
    needs_scope: bool = False
    budget: int = 0                        # usd_milli；模型里只用来校验观察 Intent 的预算上限
    follows: Optional[tuple] = None        # (Intent id, "observe"|"reroute")：承接另一个 Intent（3.1.7）
    expected_gain: Optional[float] = None  # 估值，只供司南排序，不进等级与消费门（I8）
    rollback: Optional[str] = None         # 回退方法（3.1.9）：r2 必须声明；模型里只记有没有


@dataclass(frozen=True)
class Verdict:
    """一条 judge_verdict。pass 与 fail 同时就是一条判官支持记录。"""
    seq: int
    target: str                            # Fact id、带判据的 Intent id 或 "goal"
    judge: str
    version: str
    grade: str                             # decisive | consistent
    result: str                            # pass | fail | flaky；其它无结论的裁决不进序列，不建模
    candidate: Optional[str] = None        # 目标类对象按候选分别计
    expires_at: Optional[int] = None       # 由 ttl_s 算出；None 即长期有效
    dismissed: bool = False                # 被人的裁决驳回


@dataclass(frozen=True)
class Opinion:
    """完整版的另外两种支持记录：review 与 human。"""
    seq: int
    target: str
    polarity: str                          # support | contradict
    method: str = "review"                 # review | human
    session: str = ""
    family: str = ""
    premises: tuple = ()
    context: frozenset = frozenset()       # context_manifest：该会话实际读到的正文与 Artifact
    exec_evidence: frozenset = frozenset()
    has_evidence: bool = True              # 证据非空、已登记且类别可采信
    dismissed: bool = False


@dataclass(frozen=True)
class Valuation:
    """估值类事件（2.2 的 I8）：预测、报价、行情、Hint、存活计数、席位的权重与资本变动。
    它们只影响先做什么，不得被 compute()、gate() 与 intent_state() 读取。"""
    seq: int
    kind: str                              # forecast | quote | price | hint | attack_survived | weight | stake | payout | forfeit
    target: str = ""                       # 所指节点或合约，可空
    value: float = 0.0                     # 概率、金额或计数
    family: str = ""
    role: str = ""


@dataclass(frozen=True)
class Seal:
    """封存（2.4）：一道题的日志在某一点上的可校验摘要。"""
    problem: str
    head_seq: int
    head_hash: str
    state_hash: str
    reducer: str
    terminal: Optional[str] = None         # solved | accepted | unsolved；未关题为 None


@dataclass
class State:
    facts: dict = field(default_factory=dict)        # id → Fact
    intents: dict = field(default_factory=dict)      # id → Intent
    verdicts: list = field(default_factory=list)
    opinions: list = field(default_factory=list)
    revoked: set = field(default_factory=set)        # {(judge, version)}
    approvals: dict = field(default_factory=dict)    # intent id → [seq]
    waivers: dict = field(default_factory=dict)      # intent id → {fact id}
    leases: dict = field(default_factory=dict)       # intent id → [seq]
    abandoned: set = field(default_factory=set)      # 被 Reason 或人放弃的 Intent
    now: int = 0                                     # reducer 唯一的时钟：最后一条事件的 ts
    outcomes: dict = field(default_factory=dict)     # intent id → [(seq, 结束方式)]：租约释放或过期的结果
    premise_lost: set = field(default_factory=set)   # 在途租约带 premise_lost 的 Intent
    escalations: dict = field(default_factory=dict)  # intent id → [seq]：escalate_intent（同一切口，升档重做）
    valuations: list = field(default_factory=list)   # 估值类事件，见 Valuation
    closed: bool = False                             # 已有 close_problem


@dataclass(frozen=True)
class Result:
    levels: dict                           # 论断、带判据的 Intent 与 "goal" 的等级
    disputed: frozenset
    unstable: frozenset
    stale: frozenset


# ---------- 裁决序列与迟滞（3.1.2） ----------

def sequence(st: State, target: str, judge: str, version: str, candidate: Optional[str] = None,
             verdicts: Optional[list] = None) -> list:
    """裁决序列(t,j)：按 seq 排列。过期的与被驳回的裁决不计入（3.1.3）。"""
    return sorted(
        (v for v in (st.verdicts if verdicts is None else verdicts)
         if (v.target, v.judge, v.version, v.candidate) == (target, judge, version, candidate)
         and not v.dismissed and (v.expires_at is None or v.expires_at > st.now)),
        key=lambda v: v.seq)


def effective(seq: list) -> Optional[str]:
    """有效裁决：只有一条时取该条；否则最近两条一致才取其值。None 表示无结论。"""
    vals = [v.result if v.result in ("pass", "fail") else None for v in seq]
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    return vals[-1] if vals[-1] == vals[-2] else None


def _by_target(st: State) -> dict:
    out: dict = {}
    for v in st.verdicts:
        out.setdefault(v.target, []).append(v)
    return out


def _keys(verdicts: list) -> list:
    return sorted({(v.judge, v.version, v.candidate, v.grade) for v in verdicts},
                  key=lambda k: tuple("" if x is None else x for x in k))


def _judged(st: State, target: str, verdicts: Optional[list] = None) -> list:
    """目标上每个未撤销的（判官版本、候选）及其有效裁决。verdicts：该目标的全部裁决。"""
    if verdicts is None:
        verdicts = [v for v in st.verdicts if v.target == target]
    out = []
    for judge, version, candidate, grade in _keys(verdicts):
        if (judge, version) in st.revoked:
            continue
        seq = sequence(st, target, judge, version, candidate, verdicts)
        out.append((judge, grade, candidate, len(seq), effective(seq)))
    return out


def is_unstable(judged: list) -> bool:
    """unstable(t)：存在某个判官版本，裁决不止一条且有效裁决为无结论。"""
    return any(n > 1 and eff is None for _, _, _, n, eff in judged)


def is_stale(st: State, verdicts: list) -> bool:
    """stale：目标上有裁决因有效期届满而退出序列。过期不是证伪。"""
    return any(v.expires_at is not None and v.expires_at <= st.now for v in verdicts)


def rejudge_wanted(st: State) -> list:
    """/work 里由 unstable 派生的复判：该（目标、判官版本）的裁决不足 4 次。"""
    out = []
    for target, verdicts in sorted(_by_target(st).items()):
        for judge, version, candidate, _ in _keys(verdicts):
            if (judge, version) in st.revoked:
                continue
            seq = sequence(st, target, judge, version, candidate, verdicts)
            if 1 < len(seq) < 4 and effective(seq) is None:
                out.append((target, judge, version, candidate))
    return out


# ---------- 等级（3.1.2 的 M0 函数是 3.1.3 在"只有判官支持"时的特例） ----------

def _target_level(judged: list, judge: Optional[str] = None) -> str:
    """level(g)：某个候选有一条有效的判定性 pass 即 E3，否则 E0。目标没有 X。"""
    for j, grade, _, _, eff in judged:
        if grade == "decisive" and eff == "pass" and (judge is None or j == judge):
            return "E3"
    return "E0"


def _is_approved(st: State, intent: Intent) -> bool:
    """已有 approve(i)。r2 的批准只管一次租约：必须晚于它的上一次租约。"""
    seqs = st.approvals.get(intent.id, [])
    if not seqs:
        return False
    if intent.risk == "r2":
        return max(seqs) > max(st.leases.get(intent.id, [0]), default=0)
    return True


def _derived(st: State, judged: dict) -> dict:
    """done.tests（3.1.3）：Intent 获批后，达成给被检验的推断一条相符性支持；
    判定给出失败而 Intent 未达成，给一条相符性判官的反证。返回 fact id → {"pass", "fail"}。"""
    out: dict = {}
    for intent in st.intents.values():
        if not (intent.done and intent.tests and st.approvals.get(intent.id)):
            continue
        mine = judged.get(intent.id, [])
        if _target_level(mine, intent.done) == "E3":
            outcome = "pass"
        elif any(j == intent.done and eff == "fail" for j, _, _, _, eff in mine):
            outcome = "fail"
        else:
            continue
        for fact_id in intent.tests:
            out.setdefault(fact_id, set()).add(outcome)
    return out


def compute(st: State, order: Optional[Iterable[str]] = None) -> Result:
    """重算全部等级。X 的集合不依赖任何等级，先一次算定；判官给的等级同样不依赖其它等级；
    其余由复审支持从 E0 起反复应用，只升不降，直到不变（最小不动点）。
    order 只影响迭代顺序，不影响结果，测试用它检验这一点。"""
    grouped = _by_target(st)
    judged_all = {t: _judged(st, t, vs) for t, vs in grouped.items()}
    derived = _derived(st, judged_all)
    levels: dict = {"goal": _target_level(judged_all.get("goal", []))}
    for intent in st.intents.values():
        if intent.done:
            levels[intent.id] = _target_level(judged_all.get(intent.id, []), intent.done)

    soft_contra: set = set()                         # 有相符性判官的有效反证
    refuted = {o.target for o in st.opinions
               if o.method == "human" and o.polarity == "contradict" and not o.dismissed}
    for fid in st.facts:
        judged = judged_all.get(fid, [])
        if fid in refuted or any(g == "decisive" and eff == "fail" for _, g, _, _, eff in judged):
            levels[fid] = X
        elif any(g == "decisive" and eff == "pass" for _, g, _, _, eff in judged):
            levels[fid] = "E3"
        elif "pass" in derived.get(fid, ()) or any(g == "consistent" and eff == "pass" for _, g, _, _, eff in judged):
            levels[fid] = "E3d"
        else:
            levels[fid] = "E0"
        if "fail" in derived.get(fid, ()) or any(g == "consistent" and eff == "fail" for _, g, _, _, eff in judged):
            soft_contra.add(fid)

    reviews: dict = {}
    for o in st.opinions:
        if o.method == "review" and o.target in st.facts:
            reviews.setdefault(o.target, []).append(o)

    def premises_of(o: Opinion) -> tuple:           # 前提(s)：复审再并上目标论断自己的 premises
        return tuple(o.premises) + tuple(st.facts[o.target].premises)

    def valid(o: Opinion) -> bool:                  # 有效(s)
        return o.has_evidence and not o.dismissed and all(levels.get(p) != X for p in premises_of(o))

    def strength(o: Opinion) -> int:                # 信任不超过前提
        return min((RANK[levels[p]] for p in premises_of(o)), default=INF)

    def independent(o: Opinion) -> bool:
        fact = st.facts[o.target]
        return o.session != fact.session and (fact.body_ref is None or fact.body_ref not in o.context)

    def heterogeneous(s1: Opinion, s2: Opinion) -> bool:
        return s1.family != s2.family or not (s2.exec_evidence <= s1.exec_evidence)

    def review_level(fid: str) -> str:
        sup = sorted((o for o in reviews.get(fid, ()) if o.polarity == "support" and valid(o) and independent(o)),
                     key=lambda o: o.seq)
        strong = [o for o in sup if strength(o) >= RANK["E2"]]
        for i, s1 in enumerate(strong):
            for s2 in strong[i + 1:]:
                if s1.session != s2.session and heterogeneous(s1, s2):
                    return "E2"
        if any(strength(o) >= RANK["E1"] for o in sup):
            return "E1"
        return "E0"

    todo = [f for f in (order if order is not None else st.facts) if levels[f] != X]   # 缺省按创建顺序
    changed = True
    while changed:
        changed = False
        for fid in todo:
            new = review_level(fid)
            if RANK[new] > RANK[levels[fid]]:
                levels[fid] = new
                changed = True

    disputed = frozenset(
        fid for fid in st.facts
        if levels[fid] not in (X, "E3") and (
            fid in soft_contra
            or any(o.polarity == "contradict" and valid(o) for o in reviews.get(fid, ()))))
    return Result(levels=levels, disputed=disputed,
                  unstable=frozenset(t for t, j in judged_all.items() if is_unstable(j)),
                  stale=frozenset(t for t, vs in grouped.items() if is_stale(st, vs)))


# ---------- 消费门与 Intent 状态（3.1.2、3.1.3） ----------

def premises_ok(st: State, res: Result, intent: Intent) -> bool:
    """消费门的前提部分。前提是带判据的 Intent 时，三档都要求它已达成。
    r2 的观察类前提另须带对照（N1）；不带对照的 E3 观察与 E2 的推断一样，要人对它签署豁免。"""
    for p in intent.premises:
        if p in st.intents:
            if res.levels.get(p) != "E3":
                return False
            continue
        level = res.levels[p]
        if level == X:
            return False
        if intent.risk == "r1" and (RANK[level] < RANK["E1"] or p in res.disputed):
            return False
        if intent.risk == "r2":
            fact = st.facts[p]
            proven = level == "E3" and (fact.claim_type != "observation" or fact.control)
            if not proven and not (
                    RANK[level] >= RANK["E2"] and p in st.waivers.get(intent.id, ())):
                return False
    return True


def gate(st: State, res: Result, intent: Intent) -> bool:
    """gate(i)：前提达标，且（不是 r2 也不申请扩大范围，或已有批准）。"""
    return premises_ok(st, res, intent) and (
        (intent.risk != "r2" and not intent.needs_scope) or _is_approved(st, intent))


def gate_m0(st: State, res: Result, intent: Intent) -> bool:
    """3.1.2 的 M0 消费门，照规格逐字写出，用来与完整版对照。"""
    prem = all(res.levels[p] != X and (res.levels[p] == "E3" or (intent.risk == "r0" and p in st.facts))
               for p in intent.premises)
    return prem and ((intent.risk != "r2" and not intent.needs_scope) or _is_approved(st, intent))


def intent_state(st: State, res: Result, intent: Intent) -> str:
    """Intent 的资格状态：achieved、abandoned、needs_human、blocked、open。
    leased 与 done 取决于租约生命周期，不在本模型内。"""
    if intent.done and res.levels[intent.id] == "E3":
        return "achieved"
    if intent.id in st.abandoned:
        return "abandoned"
    for p in intent.premises:
        if p in st.facts and res.levels[p] == X:
            return "abandoned"
        if p in st.intents and intent_state(st, res, st.intents[p]) == "abandoned":
            return "abandoned"
    if intent.needs_scope and not _is_approved(st, intent):
        return "needs_human"
    if premises_ok(st, res, intent):
        return "open" if intent.risk != "r2" or _is_approved(st, intent) else "needs_human"
    if intent.risk == "r2" and all(
            (res.levels.get(p) == "E3") if p in st.intents else RANK.get(res.levels[p], -1) >= RANK["E2"]
            for p in intent.premises):
        return "needs_human"                        # 只差人的批准或对前提的豁免
    return "blocked"


# ---------- 失效集合（3.1.2 的 /invalidations） ----------

def invalidations(st: State, node: str) -> set:
    """某节点被证伪后，因它失去支持的节点集：把该节点的证伪去掉重算，等级因此变高的其它节点。"""
    without = replace(
        st,
        verdicts=[v for v in st.verdicts if not (v.target == node and v.result == "fail")],
        opinions=[o for o in st.opinions
                  if not (o.target == node and o.method == "human" and o.polarity == "contradict")])
    now, then = compute(st).levels, compute(without).levels
    rank = lambda level: -1 if level == X else RANK[level]
    return {f for f in st.facts if f != node and rank(then[f]) > rank(now[f])}


# ---------- 引用的可采信检查（3.1.2 操作表、3.2.4、3.4.4） ----------

def validate_register(actor_kind: str, cls: str) -> str:
    """出处类别由登记方的组件令牌决定；任务令牌不能登记任何类别。"""
    return "ok" if REGISTRAR.get(cls) == actor_kind else "forbidden_op"


def validate_add_fact(artifacts: dict, levels: dict, problem: str, claim_type: str,
                      has_check: bool, premises: tuple, grounds: tuple) -> str:
    """add_fact 的确定性校验，按拒绝码的先后给出第一条不满足的。"""
    for ref in grounds:
        if ref not in artifacts:
            return "unknown_ref"
    for p in premises:
        if p not in levels:
            return "unknown_ref"
    for ref in grounds:
        if artifacts[ref].problem != problem:
            return "scope_mismatch"
    for ref in grounds:
        if artifacts[ref].cls not in ADMISSIBLE:
            return "inadmissible_class"
    if claim_type == "observation":
        if not has_check or not any(artifacts[r].cls in ("exec", "input") for r in grounds):
            return "missing_evidence"
    elif not grounds and not premises:
        return "missing_evidence"
    if any(levels[p] == X for p in premises):
        return "stale_premise"
    return "ok"


# ---------- 终态三值（3.1.2） ----------

def terminal(st: State, res: Result, accept: str = "judge", accepted: bool = False) -> Optional[str]:
    """题目的终态。未关题为 None。solved 只来自判官确认；人验收是 accepted，不写作 solved。"""
    if not st.closed:
        return None
    if accept == "judge" and res.levels["goal"] == "E3":
        return "solved"
    return "accepted" if accepted else "unsolved"


# ---------- 难点标记 knot、换缝与升档、关节度（3.1.7） ----------

def achieved_at(st: State, intent: Intent) -> Optional[int]:
    """带判据的 Intent 达成的时刻：使某个候选的有效裁决成为 pass 的那条裁决的 seq。未达成为 None。"""
    best = None
    verdicts = [v for v in st.verdicts if v.target == intent.id]
    for judge, version, candidate, grade in _keys(verdicts):
        if judge != intent.done or grade != "decisive" or (judge, version) in st.revoked:
            continue
        seq = sequence(st, intent.id, judge, version, candidate, verdicts)
        if effective(seq) == "pass":
            best = seq[-1].seq if best is None else min(best, seq[-1].seq)
    return best


def _last_failure(st: State, intent: Intent) -> Optional[int]:
    """上次租约以 failed 或 nothing 结束时的 seq。上次结束不是这两种（含过期），返回 None。"""
    history = st.outcomes.get(intent.id, [])
    if not history:
        return None
    seq, outcome = max(history)
    return seq if outcome in OUTCOME_FAIL else None


def failed_last(st: State, intent: Intent) -> bool:
    """failed_last(i)：上一刀没下去，且此后既没有承接它的观察 Intent 达成，也没有显式升档。"""
    at = _last_failure(st, intent)
    if at is None:
        return False
    if any(seq > at for seq in st.escalations.get(intent.id, ())):
        return False
    for other in st.intents.values():
        if other.follows == (intent.id, "observe") and other.done:
            got = achieved_at(st, other)
            if got is not None and got > at:
                return False
    return True


def reroutes(st: State, intent: Intent) -> int:
    """换缝次数：沿 follows{as: reroute} 回溯的链长。"""
    count, current, seen = 0, intent, set()
    while current.follows and current.follows[1] == "reroute" and current.id not in seen:
        seen.add(current.id)
        previous = st.intents.get(current.follows[0])
        if previous is None:
            break
        count, current = count + 1, previous
    return count


def must_escalate(st: State, intent: Intent) -> bool:
    """护栏：两次换缝未解必须升档。此时不再等 Reason，下一次尝试直接用强档。"""
    return failed_last(st, intent) and reroutes(st, intent) >= 2


def knot(st: State, res: Result, intent: Intent) -> bool:
    """knot(i)：难点标记，是已有信号的析取。它只供司南读取，不进 level() 与 gate()。"""
    if intent_state(st, res, intent) in ("achieved", "abandoned"):
        return False
    if failed_last(st, intent) and not must_escalate(st, intent):
        return True
    if any(p in res.disputed or p in res.unstable for p in intent.premises):
        return True
    return intent.id in st.premise_lost


def escalated(st: State, intent: Intent) -> bool:
    """下一次尝试是否用强档：上次失败之后 Reason 或人显式升档，或护栏触发。"""
    at = _last_failure(st, intent)
    if at is None:
        return False
    return any(seq > at for seq in st.escalations.get(intent.id, ())) or must_escalate(st, intent)


def claimable(st: State, res: Result, intent: Intent) -> bool:
    """司南的认领规则（4.1）：open 且不带 knot。带 knot 的 Intent 先由 Reason 处理：看清、换缝或升档。"""
    return intent_state(st, res, intent) == "open" and not knot(st, res, intent)


def validate_follow(st: State, new: Intent) -> str:
    """add_intent 对 follows 的校验：所指 Intent 存在；观察 Intent 必须是 r0、带判据，预算不超过原 Intent 的一半。"""
    if new.follows is None:
        return "ok"
    target_id, how = new.follows
    target = st.intents.get(target_id)
    if target is None:
        return "unknown_ref"
    if how == "reroute":
        return "ok"
    if how != "observe" or new.risk != "r0" or not new.done or new.budget * 2 > target.budget:
        return "schema_error"
    return "ok"


def unlocks(st: State, res: Result, intent: Intent) -> int:
    """unlocks(i)：以 i 为前提（直接或经带判据的 Intent 传递）、当前为 blocked 的 Intent 数。只用于排序。"""
    reached, frontier = set(), [intent.id]
    while frontier:
        current = frontier.pop()
        for other in st.intents.values():
            if current in other.premises and other.id not in reached:
                reached.add(other.id)
                frontier.append(other.id)
    return sum(1 for k in reached if intent_state(st, res, st.intents[k]) == "blocked")


def counts_as_progress(st: State, res: Result, target: str) -> bool:
    """续期门的进展（3.5.2）：带判据的 Intent 达成，或带对照的观察到 E3。恒真的谓词过不了对照。"""
    if target in st.intents:
        return bool(st.intents[target].done) and res.levels.get(target) == "E3"
    fact = st.facts.get(target)
    return (fact is not None and fact.claim_type == "observation" and fact.control
            and res.levels[target] == "E3")


# ---------- 判官资产的两级可见性（3.3.2） ----------

def is_sealed(ref: str) -> bool:
    """含密级资产以保密库引用登记，不是 Artifact。"""
    return ref.startswith(VAULT)


def mountable(container: str, ref: str) -> bool:
    """判官资产能否挂进某种容器。结构级在三种容器里都可只读挂载；含密级只进判官容器。"""
    if is_sealed(ref):
        return container == "judge"
    return container in ("model", "exec", "judge")


def can_deref(actor_kind: str, ref: str) -> bool:
    """谁能读到一份判官资产的内容。含密级只有判官运行器的令牌能解引用。"""
    return actor_kind == "judge" if is_sealed(ref) else True


def show_body(actor_kind: str, artifact: Artifact) -> bool:
    """show 能否返回 Artifact 的正文。访问摘要里有保密库引用的判官输出，对任务令牌只给裁决与原因类别。"""
    return actor_kind in ("judge", "human") or not any(is_sealed(t) for t in artifact.touched)


# ---------- 题界与封存（2.4） ----------

def validate_register_excerpt(actor_kind: str, seal: Seal, replayed_state_hash: str) -> str:
    """register_artifact 的摘录规则：只有接收题的图服务能登记，先把来源日志重放到 head_seq 并比对状态哈希。
    通过后摘录是接收题里的一个 input 类 Artifact；摘录里的等级接收题不认（I7），模型里也没有读它的路径。"""
    if actor_kind != "graph":
        return "forbidden_op"
    return "ok" if replayed_state_hash == seal.state_hash else "bad_seal"


def seal_check(seal: Seal, replayed_state_hash: str, child_goal_check: str, registered_check: str) -> str:
    """内建判官 seal_check（判定性）：封存可重放、终态为 solved、子题 Goal 判据的哈希等于父题 Intent 登记的判据。
    它检验的是日志，不是内容。accepted 与 unsolved 的子题不能让父题的 Intent 达成。"""
    if replayed_state_hash != seal.state_hash:
        return "fail"
    return "pass" if seal.terminal == "solved" and child_goal_check == registered_check else "fail"


# ---------- 预测账的校准投影（3.5.3） ----------

def calibration(st: State, res: Result) -> dict:
    """按（家族、角色）汇总已结算预测的条数与 Brier 分。只有带判据的对象参与结算：
    达成或到 E3 记 1；被放弃、被证伪，或关题时仍未达成记 0；其余未结算。预测读等级，等级不读预测（I8）。"""
    acc: dict = {}
    for v in st.valuations:
        if v.kind != "forecast":
            continue
        if v.target in st.intents and st.intents[v.target].done:
            state = intent_state(st, res, st.intents[v.target])
            outcome = 1.0 if state == "achieved" else 0.0 if state == "abandoned" or st.closed else None
        elif v.target == "goal" or (v.target in st.facts and st.facts[v.target].claim_type == "observation"):
            level = res.levels[v.target]
            outcome = 1.0 if level == "E3" else 0.0 if level == X or st.closed else None
        else:
            continue
        if outcome is None:
            continue
        n, total = acc.get((v.family, v.role), (0, 0.0))
        acc[(v.family, v.role)] = (n + 1, total + (v.value - outcome) ** 2)
    return {key: (n, total / n) for key, (n, total) in acc.items()}


# ---------- 常设留出的互斥分配（8.6） ----------

def holdout(problem_id: str, roster: Sequence[str], eps: float = 0.1, epoch: str = "") -> Optional[str]:
    """本题留出哪一项，至多一项。roster 只列感知官与本题匹配的锦囊；守门官与量具不在表内，含 r2 规则的题不调用。
    把 [0,1) 按 eps 分格，前 len(roster) 格各对应一项，题目 id 的哈希落在哪一格就留出哪一项。"""
    names = sorted(set(roster))
    if not names:
        return None
    step = min(eps, 1.0 / len(names))
    digest = hashlib.sha256(f"{epoch}\x00{problem_id}".encode("utf-8")).digest()
    u = int.from_bytes(digest[:8], "big") / 2 ** 64
    k = int(u / step)
    return names[k] if k < len(names) else None


# ---------- 人的决策与所见绑定、回退声明（3.1.9） ----------

def approval_card(st: State, res: Result, intent: Intent) -> dict:
    """审批卡：状态的纯函数，只含与这一个决定有关的字段。估值类字段（expected_gain、预测、行情）
    不在卡片里，所以估值事件不会让一次批准过期（I8）；别的 Intent 上发生的事同样不会。"""
    premises = []
    for p in intent.premises:
        fact = st.facts.get(p)
        premises.append({"id": p, "level": res.levels.get(p, "E0"), "disputed": p in res.disputed,
                         "unstable": p in res.unstable, "stale": p in res.stale,
                         "controlled": bool(fact and fact.control),
                         "waived": p in st.waivers.get(intent.id, ())})
    return {"kind": "approval", "target": intent.id,
            "fields": {"risk": intent.risk, "budget": intent.budget, "done": intent.done or "",
                       "tests": list(intent.tests), "needs_scope": intent.needs_scope,
                       "rollback": intent.rollback or "", "premises": premises}}


def card_hash(card: dict) -> str:
    """投影哈希按卡片范围计算：规范化序列化之后取 sha256。pd 的文本卡与网页卡片是同一个对象，哈希相同。"""
    blob = json.dumps(card, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def validate_decision(seen_hash: str, card: dict) -> str:
    """人的决策操作（approve、extend、rule、accept）带所见卡片的哈希；链头重算后不等即拒绝。"""
    return "ok" if seen_hash == card_hash(card) else "stale_view"


def validate_rollback(intent: Intent) -> str:
    """add_intent 的回退校验（M4）：r2 的 Intent 必须声明回退；r1 可以不带。"""
    return "schema_error" if intent.risk == "r2" and not intent.rollback else "ok"

