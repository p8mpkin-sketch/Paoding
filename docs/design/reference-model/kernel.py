"""庖丁基座规格 v1.1 第 3.1 节的可执行参考模型。

只覆盖内核里"由日志派生"的语义：裁决序列与翻转迟滞、等级函数与最小不动点重算、
消费门、Intent 的资格状态、失效集合，以及引用的可采信检查。
它不是 M0 的代码库：没有事件日志、存储、租约、预算、容器。全部是纯函数，只用标准库。
每个函数注明它对应规格的哪一节；规格与本文件不一致时，以规格为准并修正本文件。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

LEVELS = ("E0", "E1", "E2", "E3d", "E3")          # 全序；X 单列
RANK = {name: i for i, name in enumerate(LEVELS)}
X = "X"
INF = len(LEVELS)                                 # 没有前提的支持，strength 记为 ∞

ADMISSIBLE = frozenset({"exec", "judge", "input"})             # 可作证据的出处类别（3.2.2）
REGISTRAR = {"exec": "executor", "judge": "judge", "input": "human", "authored": "adapter"}


# ---------- 记录 ----------

@dataclass(frozen=True)
class Artifact:
    id: str
    cls: str                               # exec | judge | input | authored
    problem: str = "p1"


@dataclass(frozen=True)
class Fact:
    id: str
    claim_type: str = "observation"        # observation | inference
    premises: tuple = ()                   # Fact id，或带判据的 Intent 的 id
    session: str = ""                      # 提出者的会话，即租约 id
    body_ref: Optional[str] = None         # 第三层正文


@dataclass(frozen=True)
class Intent:
    id: str
    risk: str = "r0"                       # r0 | r1 | r2
    premises: tuple = ()
    done: Optional[str] = None             # 带判据的 Intent：判据所用判官的 id
    tests: tuple = ()                      # done.tests：这条判据所检验的推断类前提
    needs_scope: bool = False


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
    """消费门的前提部分。前提是带判据的 Intent 时，三档都要求它已达成。"""
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
        if intent.risk == "r2" and level != "E3" and not (
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
