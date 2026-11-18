"""租约族（§3.1.2、§3.5.2）：lease、renew、release、expire_lease，以及挂在租约上的用量 cost。"""

from __future__ import annotations

from typing import cast

from .. import work as wk
from ..parse import Obj
from ..state import Actor, Cost, Event, Lease, State
from .common import Config, Ok, Reject, _amount

# ---------- 校验 ----------


def _v_lease(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    kind, target = body.string("kind"), body.opt_string("target")
    if kind not in ("bootstrap", "reason", "explore", "judge"):
        return Reject("schema_error", f"租约种类 {kind} 非法")
    if (kind == "judge") != (actor["kind"] == "judge"):
        return Reject("forbidden_op", "judge 租约只由判官运行器申请；任务租约只由司南申请")
    reserve, ttl, holder = _amount(body.child("reserve")), body.integer("ttl_s"), body.text("holder")
    if ttl <= 0:
        return Reject("schema_error", "ttl_s 必须为正")
    if wk.in_flight(state, pid, kind, target) is not None:
        return Reject("conflict_leased", "目标上已有在途租约")
    if kind == "explore" and target in state["intents"]:
        hit = wk.resource_conflict(state, pid, target)
        if hit is not None:
            return Reject("conflict_leased", f"规则 {hit[1]} 正被在途租约 {hit[0]['id']} 写占用，排队等它结束")
    item = {"kind": kind, **({"target": target} if target is not None else {})}
    offered = [{k: v for k, v in w.items() if k in ("kind", "target")} for w in wk.work(state, pid)]
    if item not in offered:
        return Reject("forbidden_op", "目标不在 /work 内")
    view = wk.budget_view(state, pid)
    prob = state["problems"][pid]
    if kind == "bootstrap" and reserve["usd_milli"] > prob["budget"]["bootstrap_share"] * view["cap"]["usd_milli"]:
        return Reject("over_budget", "Bootstrap 的预留不超过 bootstrap_share × cap")
    pool_res = wk.zero()
    for l in wk.active_leases(state, pid):
        if l["kind"] == "judge":
            pool_res = wk.add(pool_res, l["reserve"])
    ok = (
        wk.fits(view, reserve, prob["budget"]["verify_share"], view["verify_spent"], pool_res)
        if kind == "judge"
        else wk.fits(view, reserve)
    )
    if not ok:
        return Reject("over_budget", "spent + reserved + reserve 超过上限")
    attempt = 1 + sum(1 for l in wk.leases_of(state, pid) if l["kind"] == kind and l.get("target") == target)
    return Ok(
        {
            "kind": kind,
            **({"target": target} if target is not None else {}),
            "holder": holder,
            "reserve": reserve,
            "ttl_s": ttl,
            "attempt": attempt,
            **({"reflect": True} if kind == "reason" and wk.in_review(state, pid) else {}),
        }
    )


def _own_lease(state: State, actor: Actor, pid: str, body: Obj) -> Lease | Reject:
    """续租与释放的共同前置：租约存在、属于提交所指的这道题、提交方是持有者、租约在途。

    四条在关题前后都查（关题只放宽 outcome 的取值，不放宽归属）。判官运行器的令牌不带会话，
    按身份种类放行，但只限 judge 租约。"""
    l = state["leases"].get(body.string("lease"))
    if l is None:
        return Reject("unknown_ref", "租约不存在")
    if l["problem_id"] != pid:
        return Reject("scope_mismatch", f"租约 {l['id']} 属于别题")
    by_judge = actor["kind"] == "judge" and l["kind"] == "judge"
    if not by_judge and actor["id"] != l["holder"] and actor.get("session") != l["id"]:
        return Reject("forbidden_op", "续租与释放限持有者")
    if not l["active"]:
        return Reject("schema_error", "租约已结束")
    return l


def _v_renew(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    l = _own_lease(state, actor, pid, body)
    if isinstance(l, Reject):
        return l
    if ts >= l["expires_at"]:
        return Reject("schema_error", "租约已过期，等待 expire_lease")
    ttl = body.integer("ttl_s", l["ttl_s"])
    if ttl <= 0:
        return Reject("schema_error", "ttl_s 必须为正")
    return Ok({"lease": l["id"], "ttl_s": ttl})


RELEASE_OUTCOMES = ("done", "failed", "nothing", "budget_exhausted")


def _v_release(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    l = _own_lease(state, actor, pid, body)
    if isinstance(l, Reject):
        return l
    tr = body.opt_string("transcript_ref")
    if state["problems"][pid]["closed"]:  # 关题后在途任务交回租约：结局一律记 closed
        keep = tr is not None and tr in state["artifacts"] and state["artifacts"][tr]["problem_id"] == pid
        return Ok(
            {"lease": l["id"], "outcome": "closed", "after_close": True, **({"transcript_ref": tr} if keep else {})}
        )  # 交回的留档照样挂到租约上
    outcome = body.string("outcome")
    if outcome not in RELEASE_OUTCOMES:
        return Reject("schema_error", f"outcome 只取 {RELEASE_OUTCOMES}")
    if tr is not None and (tr not in state["artifacts"] or state["artifacts"][tr]["problem_id"] != pid):
        return Reject("unknown_ref", "transcript_ref 不存在或属于别题")
    suggestions = body.texts("suggestions", None)
    return Ok(
        {
            "lease": l["id"],
            "outcome": outcome,
            **({"transcript_ref": tr} if tr else {}),
            **({"suggestions": suggestions} if suggestions else {}),
        }
    )


def _v_expire_lease(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    l = state["leases"].get(body.string("lease"))
    if l is None or l["problem_id"] != pid or not l["active"]:
        return Reject("unknown_ref", "没有这条在途租约")
    if ts < l["expires_at"]:
        return Reject("schema_error", "ts < expires_at，租约未到期")
    return Ok({"lease": l["id"]})


def _v_cost(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    l = state["leases"].get(body.string("task_id"))
    if l is None or l["problem_id"] != pid:
        return Reject("unknown_ref", "任务不存在")
    source = body.string("source")
    if source not in ("proxy", "judge", "cli_reported"):
        return Reject("schema_error", "source 非法")
    nums = {
        k: body.integer(k) if body.get(k) else 0
        for k in ("tokens_in", "tokens_cached", "tokens_out", "usd_milli", "wall_s")
    }
    if any(v < 0 for v in nums.values()):
        return Reject("schema_error", "用量不能为负")
    return Ok(
        {
            "task_id": l["id"],
            "source": source,
            **nums,
            "price_table": body.text("price_table"),
            **({"model": body.text("model")} if body.get("model") else {}),
            **({"tokens_cached_unknown": True} if body.get("tokens_cached") is None else {}),
        }
    )


# ---------- 应用 ----------


def _a_lease(s: State, ev: Event) -> None:
    body, seq = ev["body"], ev["seq"]
    lid = f"l_{seq}"
    issued = {
        **body,
        "id": lid,
        "problem_id": ev["problem_id"],
        "issued_seq": seq,
        "active": True,
        "expires_at": ev["ts"] + body["ttl_s"] * 1000,
    }
    s["leases"] = {**s["leases"], lid: cast(Lease, issued)}
    if body["kind"] == "explore":
        s["lease_seqs"] = {**s["lease_seqs"], body["target"]: s["lease_seqs"].get(body["target"], []) + [seq]}


def _a_renew(s: State, ev: Event) -> None:
    l = s["leases"][ev["body"]["lease"]]
    s["leases"] = {**s["leases"], l["id"]: {**l, "expires_at": ev["ts"] + ev["body"]["ttl_s"] * 1000}}


def _a_end_lease(s: State, ev: Event) -> None:
    """release 与 expire_lease：租约结束，结局记在租约上。"""
    body = ev["body"]
    l = s["leases"][body["lease"]]
    ended: Lease = {
        **l,
        "active": False,
        "ended_seq": ev["seq"],
        "outcome": "expired" if ev["kind"] == "expire_lease" else body["outcome"],
    }
    if body.get("transcript_ref"):
        ended["transcript_ref"] = body["transcript_ref"]
    s["leases"] = {**s["leases"], l["id"]: ended}


def _a_cost(s: State, ev: Event) -> None:
    body = ev["body"]
    lk = s["leases"][body["task_id"]]["kind"]
    s["costs"] = s["costs"] + [cast(Cost, {**body, "problem_id": ev["problem_id"], "seq": ev["seq"], "lease_kind": lk})]
