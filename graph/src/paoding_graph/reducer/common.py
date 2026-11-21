"""reducer 各事件族共用的部分：结果类型、配置、空状态，以及提议体里反复出现的几种形状的解析。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import cards
from .. import refmodel as rm
from ..parse import BadBody, Obj
from ..practice import PracticePolicy
from ..resources import external_resources
from ..state import Actor, Amount, Body, Check, Event, Fact, Intent, JudgeEntry, ScopeRule, State

RISKS = ("r0", "r1", "r2")


RISK_RANK = {r: i for i, r in enumerate(RISKS)}
WALL_MODES = ("elapsed", "spend")
RiskRow = dict[str, Any]  # 设置层风险表的一行 {resource, pattern, actions, risk}


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReadonlyAllow:
    """人维护的只读白名单（地图 Q36，设置 grants.readonly_allow）：开放道的扩权申请命中即由图服务自动批。
    rows 是 (resource, pattern)，pattern 按 fnmatch 匹配；版本取设置存储的版本，摘要是白名单本身的。"""

    rows: tuple[tuple[str, str], ...]
    version: int
    digest: str

    def stamp(self) -> dict[str, Any]:
        return {"version": self.version, "digest": self.digest}


@dataclass(frozen=True)
class Ok:
    body: Body


@dataclass(frozen=True)
class Reject:
    code: str
    detail: str = ""
    card: tuple[str, str] | None = None  # stale_view 时所指的卡 (kind, target)；服务层据此附上链头的最新卡片


@dataclass(frozen=True)
class Config:
    judges: dict[str, JudgeEntry] = field(default_factory=dict)  # judge_id → {version, grade, kind, max_cost}
    external_resources: frozenset[str] = field(default_factory=external_resources)  # 取自 resources.py 登记表
    cheap_judge_max_cost: float = 0.05  # "廉价判官"阈值（美元），配置项
    fact_quota: int = 20  # 每个任务（会话）的写入配额
    intent_quota: int = 8
    intent_budget_usd_milli: tuple[int, int] = (1, 10_000_000)  # add_intent 预算区间
    # 单题硬顶（宪章 03 §5、一句话开题内核增量 14）：所有开题的预算上限，None 即不设。由设置存储给出，
    # 组装根在设置变更时整体替换 Config；校验结果连同设置摘要写进事件体，重放不读设置
    open_cap_usd_milli: int | None = None
    open_cap_wall_s: int | None = None
    settings: tuple[int, str] | None = None  # 设置存储当时的 (版本, 摘要)，开题时抄进事件体（宪章 D5）
    # 焚决 F3（FJ5，体质修炼）：此刻生效的功法 (品阶, 摘要)，开题时抄进事件体；席位 → 会话形态 "id@ver"，
    # 领租约时抄进事件体。都由组装根从功法清单（paoding_fenjue）取来；内核不认识任何一团火，只抄不解释
    gongfa: tuple[int, str] | None = None
    forms: tuple[tuple[str, str], ...] = ()
    # 体质修炼 003（T4-3、T4-4）：功法存档里每一版的 (摘要, 品阶, 席位 → 形态表)。领租约时按题生效的那一版抄形态；
    # 人改钉（repin）只许改到表里有的版本。空即 F3 原样（形态照抄 forms，不收 repin）
    gongfa_archive: tuple[tuple[str, int, tuple[tuple[str, str], ...]], ...] = ()
    # 练习道信封（一句话开题增量 13、15）：None 即本部署不接受 lane=practice 的开题。版本与摘要开题时抄进事件体
    practice: PracticePolicy | None = None
    # 运行时扩权（runtime-grants §4、§10.3）：设置层 grants 节与风险表，由组装根在设置变更时整体替换 Config。
    # runtime 关时只接受随 needs_scope 而来的申请（图服务自己追加）；风险表未命中按 r2
    grants_runtime: bool = False
    grants_auto_practice: bool = True
    risk_table: tuple[RiskRow, ...] = ()
    scope_request_quota: int = 4  # 每个会话的扩权申请数
    # 只读白名单（地图 Q36）：None 或空即开放道的扩权一事一卡（缺省）
    readonly_allow: ReadonlyAllow | None = None
    # 时限与花费分开（external-verdict §5.6）：elapsed 为旧行为（哮天犬按开题墙钟关题）；spend 时 budget.wall_s 只管
    # 花费墙钟，另由 deadline 与题的最长存活 life_s 兜底。开题时把取值抄进事件体，重放不读设置
    wall_mode: str = "elapsed"
    life_s: int = 7 * 86400
    # 设置层已登记的模型档案名（宪章 03 §3.1）：开题的 prefs.model 只能取其中之一；空即本部署不接受任务级模型偏好
    model_profiles: frozenset[str] = frozenset()
    # 开放道交付后闲置多久自动关（地图 Q33，设置 lanes.idle_close_days）：开放道开题时抄进事件体；None 即不抄。
    # 没抄入的题（更早的日志）不闲置自动关
    idle_close_s: int | None = 7 * 86400
    # 开放道交付后的复核（地图 Q34，设置 lanes.review）：开着时开放道开题抄入 review: true。缺省关：
    # 由组装根按设置打开（复核会话的形态在功法里，没装上就不该派）
    review_open: bool = False


def empty_state() -> State:
    return {
        "problems": {},
        "artifacts": {},
        "facts": {},
        "intents": {},
        "requests": {},
        "verdicts": [],
        "content_keys": {},
        "revoked": [],
        "approvals": {},
        "lease_seqs": {},
        "abandoned": [],
        "leases": {},
        "hints": {},
        "costs": [],
        "now": 0,
        "seq": 0,
    }


# ---------- 解析：提议体里反复出现的几种形状 ----------


def _rule(r: Obj) -> ScopeRule:
    risk = r.string("risk", "r2")  # 缺省 r2
    if risk not in RISKS:
        raise BadBody(f"risk 非法：{risk}")
    return {"resource": r.text("resource"), "pattern": r.text("pattern"), "actions": r.texts("actions"), "risk": risk}


MAX_CONTROL_INPUTS = 8


def _check(c: Obj, observation: bool = False, goal: bool = False) -> Check:
    """判据。observation：这是观察类论断的判据，才接受对照 `control`（§3.3.3，N1 提前）。
    goal：Goal 的判据，才接受外部裁决的绑定单 `binding`（external-verdict §5.2）。"""
    extra = c.keys() - {"judge_id", "spec_ref", "expect", "sealed", "control", "binding"}
    if extra:
        raise BadBody(f"check 多余字段 {sorted(extra)}")
    out: Check = {"judge_id": c.string("judge_id")}
    if "control" in c:
        if not observation:
            raise BadBody("check.control 只用于观察类论断的判据")
        ctl = c.child("control")
        if ctl.keys() != {"inputs"}:
            raise BadBody("check.control 只有 inputs 一个字段（对象形式的对照参数未启用）")
        inputs = ctl.strings("inputs")
        if not 1 <= len(inputs) <= MAX_CONTROL_INPUTS or len(set(inputs)) != len(inputs):
            raise BadBody(f"control.inputs 须为 1 到 {MAX_CONTROL_INPUTS} 个互不相同的 ArtifactId")
        out["control"] = {"inputs": inputs}
    if "binding" in c:
        if not goal:
            raise BadBody("check.binding 只用于 Goal 的判据")
        b = c.child("binding")
        if b.keys() != {"connector", "task", "max_submissions"}:
            raise BadBody("binding 须为 {connector, task, max_submissions}")
        n = b.get("max_submissions")
        if type(n) is not int or n < 1:
            raise BadBody("binding.max_submissions 须为正整数")
        out["binding"] = {"connector": b.string("connector"), "task": b.string("task"), "max_submissions": n}
    if "spec_ref" in c:
        out["spec_ref"] = c.string("spec_ref")
    if "expect" in c:
        out["expect"] = c.get("expect")
    if "sealed" in c:
        out["sealed"] = []
        for v in c.children("sealed"):
            if v.keys() != {"vault", "digest"} or not _HEX64.match(v.string("digest")):
                raise BadBody("sealed 必须是 VaultRef{vault, digest}")
            out["sealed"].append({"vault": v.text("vault"), "digest": v.string("digest")})
    return out


def _amount(b: Obj) -> Amount:
    """租约的预留：三条轨都取整，不能为负。"""
    out: Amount = {"usd_milli": b.integer("usd_milli"), "wall_s": b.integer("wall_s", 0)}
    if b.get("tokens") is not None:
        out["tokens"] = b.integer("tokens")
    if out["usd_milli"] < 0 or out["wall_s"] < 0 or out.get("tokens", 0) < 0:
        raise BadBody("预算不能为负")
    return out


def _ref(state: State, pid: str, ref: str, what: str) -> Reject | None:
    """引用的 Artifact 必须存在且属于本题。"""
    a = state["artifacts"].get(ref)
    if a is None:
        return Reject("unknown_ref", f"{what} {ref} 不存在")
    if a["problem_id"] != pid:
        return Reject("scope_mismatch", f"{what} {ref} 属于别题")
    return None


def _node(state: State, node_id: str) -> Fact | Intent | None:
    return state["facts"].get(node_id) or state["intents"].get(node_id)


def _session_count(nodes: dict[str, Fact] | dict[str, Intent], session: str | None) -> int:
    return sum(1 for x in nodes.values() if session and x["session"] == session)


# ---------- 人的决定绑定所见（§3.1.9、HMI H2） ----------


def _seen(state: State, pid: str, kind: str, target: str, body: Obj) -> Body | Reject:
    """决策操作带 seen {seq, card_hash}：在当前状态（链头）重算这张卡的投影哈希，不等即 stale_view。

    seq 只留作审计，不参与比较；哈希按卡片范围计算，与这张卡无关的事件不会让它过期。"""
    seen = body.get("seen")
    if not (
        isinstance(seen, dict)
        and set(seen) == {"seq", "card_hash"}
        and isinstance(seen["card_hash"], str)
        and _HEX64.match(seen["card_hash"])
        and type(seen["seq"]) is int
        and seen["seq"] >= 0
    ):
        return Reject("schema_error", "决策操作须带 seen {seq, card_hash}")
    card = cards.card_object(state, pid, kind, target)
    if card is None:
        return Reject("unknown_ref", f"没有 {kind} 卡 {target}")
    if rm.validate_decision(seen["card_hash"], card) != "ok":
        return Reject("stale_view", f"{kind} 卡 {target} 在你查看之后已变化", (kind, target))
    return {"seq": seen["seq"], "card_hash": seen["card_hash"]}


def _reason(body: Obj) -> str:
    return body.text("reason").strip() if body.get("reason") is not None else ""


Validator = Callable[[State, Actor, str, Obj, Config], "Ok | Reject"]
TimedValidator = Callable[[State, Actor, str, Obj, Config, int], "Ok | Reject"]
Applier = Callable[[State, Event], None]  # 就地改写 apply 交来的浅副本：只替换被改动的集合，不改入参的任何对象
