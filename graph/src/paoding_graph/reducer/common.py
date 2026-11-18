"""reducer 各事件族共用的部分：结果类型、配置、空状态，以及提议体里反复出现的几种形状的解析。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import cards
from .. import refmodel as rm
from ..parse import BadBody, Obj
from ..resources import external_resources
from ..state import Actor, Amount, Body, Check, Event, Fact, Intent, JudgeEntry, ScopeRule, State

RISKS = ("r0", "r1", "r2")


RISK_RANK = {r: i for i, r in enumerate(RISKS)}


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


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


def _check(c: Obj) -> Check:
    extra = c.keys() - {"judge_id", "spec_ref", "expect", "sealed", "control"}
    if extra:
        raise BadBody(f"check 多余字段 {sorted(extra)}")
    if "control" in c:
        raise BadBody("check.control 是 M1 的对照判据，M0 未启用")
    out: Check = {"judge_id": c.string("judge_id")}
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
