"""日志上的派生量：Intent 的完整状态、/work、预算账本投影、图服务自己追加的事件（§3.1.2、§3.5.2）。

全部是状态的纯函数，不读时钟、不做 IO、不调用模型。时钟是参数 `ts`（服务层给出的"现在"）或 state["now"]。
等级相关的判断一律经 levels.py 调用参考模型的副本，这里不重写等级语义。
"""
from __future__ import annotations

from typing import Any, Mapping, TypedDict, cast

from . import levels as lv
from . import refmodel as rm
from .state import Lease, State

TASK_KINDS = ("bootstrap", "reason", "explore")
FAIL_OUTCOMES = ("failed", "nothing", "budget_exhausted", "expired")
MAX_ATTEMPTS = 2                        # Intent 回到 open 并累计尝试次数，两次后放弃（§3.4.4）
MARKS = (50, 80)


# ---------- 租约 ----------

def leases_of(state: State, pid: str) -> list[Lease]:
    return [l for l in state["leases"].values() if l["problem_id"] == pid]


def active_leases(state: State, pid: str) -> list[Lease]:
    if pid in state["problems"] and state["problems"][pid]["closed"]:
        return []
    return [l for l in leases_of(state, pid) if l["active"]]


def in_flight(state: State, pid: str, kind: str, target: str | None = None) -> Lease | None:
    for l in active_leases(state, pid):
        if l["kind"] == kind and l.get("target") == target:
            return l
    return None


# ---------- Intent 的完整状态（3.1.2 状态机 = 参考模型的资格状态 + 租约生命周期） ----------

def intent_status(state: State, pid: str, iid: str, _cache: dict[str, Any] | None = None) -> str:
    """achieved | abandoned | needs_human | blocked | open | leased | done。"""
    st, res = _cache["ref"] if _cache and "ref" in _cache else lv.compute(state, pid)
    intent = st.intents[iid]
    base = rm.intent_state(st, res, intent)
    if base in ("achieved", "abandoned"):
        return base
    rec = state["intents"][iid]
    history = [l for l in leases_of(state, pid) if l.get("target") == iid and l["kind"] == "explore"]
    if any(l["active"] for l in history) and not state["problems"][pid].get("closed"):
        return "leased"
    ended = [l for l in history if not l["active"]]
    if ended:
        last = max(ended, key=lambda l: l["ended_seq"])
        if not rec.get("done") and last["outcome"] == "done":
            return "done"
        failures = sum(1 for l in ended if l["outcome"] in FAIL_OUTCOMES
                       or (rec.get("done") and l["outcome"] == "done" and not _judge_pending(state, pid, iid)))
        if rec["risk"] == "r2" and last["outcome"] != "done" and not rm._is_approved(st, intent):
            return "needs_human"                    # 不可逆动作不自动重做
        if failures >= MAX_ATTEMPTS:
            return "abandoned"
    return base


def _judge_pending(state: State, pid: str, target: str) -> bool:
    return any(r["target"] == target and r.get("verdict_seq") is None
               for r in state["requests"].values() if r["problem_id"] == pid)


def premise_lost(state: State, pid: str) -> set[str]:
    """在途 explore 租约里，Intent 的前提已不满足消费门（被证伪或降级）的租约 id。"""
    st, res = lv.compute(state, pid)
    out = set()
    for l in active_leases(state, pid):
        if l["kind"] == "explore" and l.get("target") in st.intents:
            if not rm.premises_ok(st, res, st.intents[l["target"]]):
                out.add(l["id"])
    return out


# ---------- 预算账本投影（§3.5.2） ----------

Totals = dict[str, Any]                 # 三条轨的合计：usd_milli、tokens、wall_s


class BudgetView(TypedDict):
    cap: Totals                         # 只含开题时设了上限的轨
    spent: Totals
    reserved: Totals
    by_kind: dict[str, Totals]
    verify_spent: Totals
    marks: list[int]


def zero() -> Totals:
    return {"usd_milli": 0, "tokens": 0, "wall_s": 0}


def add(a: Totals, b: Mapping[str, object]) -> Totals:
    return {k: a.get(k, 0) + (cast(Any, b.get(k)) or 0) for k in ("usd_milli", "tokens", "wall_s")}


def budget_view(state: State, pid: str) -> BudgetView:
    p = state["problems"][pid]
    budget = cast(Totals, p["budget"])
    cap: Totals = {k: budget[k] for k in ("usd_milli", "tokens", "wall_s") if k in budget}
    spent, verify_spent = zero(), zero()
    by_kind: dict[str, Totals] = {}
    for c in state["costs"]:
        if c["problem_id"] != pid:
            continue
        amt = {"usd_milli": c["usd_milli"], "tokens": c["tokens_in"] + c["tokens_cached"] + c["tokens_out"],
               "wall_s": c["wall_s"]}
        spent = add(spent, amt)
        kind = c["lease_kind"]
        by_kind[kind] = add(by_kind.get(kind, zero()), amt)
        if kind == "judge":
            verify_spent = add(verify_spent, amt)
    reserved = zero()
    for l in active_leases(state, pid):
        reserved = add(reserved, l["reserve"])
    return {"cap": cap, "spent": spent, "reserved": reserved, "by_kind": by_kind,
            "verify_spent": verify_spent, "marks": list(p.get("marks", []))}


def fits(view: BudgetView, reserve: Mapping[str, object], share: float | None = None,
         pool_spent: Totals | None = None, pool_reserved: Totals | None = None) -> bool:
    """spent + reserved + reserve ≤ cap，逐轨比较（只比较 cap 里设了的金额与 token 两轨）。"""
    for k in ("usd_milli", "tokens"):
        if k not in view["cap"]:
            continue
        cap = view["cap"][k]
        want = cast(Any, reserve.get(k)) or 0
        if view["spent"][k] + view["reserved"][k] + want > cap:
            return False
        if share is not None and pool_spent is not None and pool_reserved is not None \
                and pool_spent[k] + pool_reserved[k] + want > share * cap:
            return False
    return True


def in_review(state: State, pid: str) -> bool:
    """预算复盘期：最近一个 budget_mark 之后，还没有 reason 租约释放。"""
    marks = state["problems"][pid].get("mark_seqs", [])
    if not marks:
        return False
    last = max(marks)
    return not any(l["kind"] == "reason" and not l["active"] and l["ended_seq"] > last
                   for l in leases_of(state, pid))


# ---------- /work（§3.1.2） ----------

def work(state: State, pid: str) -> list[dict[str, Any]]:
    p = state["problems"].get(pid)
    if p is None or p.get("closed"):
        return []
    st, res = lv.compute(state, pid)
    cache = {"ref": (st, res)}
    leases = leases_of(state, pid)
    items: list[dict[str, Any]] = []
    review = in_review(state, pid)
    task_leases = [l for l in leases if l["kind"] in TASK_KINDS]
    if not task_leases:
        items.append({"kind": "bootstrap"})
    boot_done = any(l["kind"] == "bootstrap" and not l["active"] for l in leases)
    reason_now = in_flight(state, pid, "reason") is not None
    reason_due = False
    if boot_done and not reason_now:
        issued = [l["issued_seq"] for l in leases if l["kind"] == "reason"]
        since = max(issued) if issued else 0
        triggers = [l["ended_seq"] for l in leases if l["kind"] != "reason" and not l["active"]]
        triggers += [h["seq"] for h in state["hints"].values() if h["problem_id"] == pid]
        triggers += list(p.get("mark_seqs", []))
        triggers += [v["seq"] for v in state["verdicts"]
                     if v["problem_id"] == pid and v["target"] == "goal" and v["result"] == "fail"]
        reason_due = any(t > since for t in triggers)
        if reason_due:
            items.append({"kind": "reason", **({"reflect": True} if review else {})})
    statuses = {iid: intent_status(state, pid, iid, cache) for iid in st.intents}
    if not review:
        for iid, s in statuses.items():
            if s == "open":
                items.append({"kind": "explore", "target": iid})
    pending = [r for r in state["requests"].values()
               if r["problem_id"] == pid and r.get("verdict_seq") is None]
    for r in pending:
        if in_flight(state, pid, "judge", r["id"]) is None:
            items.append({"kind": "judge", "target": r["id"]})
    for target, judge, version, candidate in rm.rejudge_wanted(st):
        if not any(r["target"] == target and r.get("candidate") == candidate for r in pending):
            items.append({"kind": "rejudge", "target": target, "judge": judge, "version": version,
                          "candidate": candidate})
    for iid, s in statuses.items():
        if s == "needs_human":
            items.append({"kind": "human", "target": iid, "why": "needs_human"})
    stalled = (not active_leases(state, pid) and "open" not in statuses.values() and not pending
               and not reason_due and boot_done)
    if stalled:
        items.append({"kind": "human", "target": pid, "why": "stalled"})
    return items


# ---------- 终态（3.1.2）与图服务自己追加的事件 ----------

def terminal(state: State, pid: str) -> str:
    p = state["problems"][pid]
    if p["goal"]["accept"] == "judge" and lv.levels(state, pid)["goal"] == "E3":
        return "solved"
    return "accepted" if p.get("accepted") else "unsolved"


def closeout_items(state: State, pid: str) -> list[dict[str, Any]]:
    """四顾清单（3.1.8）。只对画像为 r1、r2 或 accept=human 的题列项；M0 的 r0 判官验收题恒为空。
    完整清单（范围修订、r2 凭据、stale/disputed/E3d）在 M4 落地，这里先给出 r1/r2 题的占位项。"""
    p = state["problems"][pid]
    if p["profile"]["reversibility"] == "r0" and p["goal"]["accept"] == "judge":
        return []
    return [{"item": "closeout_review", "reason": p["profile"]["reversibility"]}]


def followups(state: State, pid: str) -> list[tuple[str, dict[str, Any]]]:
    """应用一条事件之后，图服务应当自己追加的事件：budget_mark、自动关题。纯函数。"""
    p = state["problems"].get(pid)
    if p is None or p.get("closed"):
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    view = budget_view(state, pid)
    for m in MARKS:
        if m in view["marks"]:
            continue
        crossed = [k for k in ("usd_milli", "tokens") if k in view["cap"]
                   and view["spent"][k] * 100 >= m * view["cap"][k]]
        if crossed:
            out.append(("budget_mark", {"mark": m, "axis": crossed[0]}))
    if lv.levels(state, pid)["goal"] == "E3" and not closeout_items(state, pid):
        out.append(("close_problem", {"terminal": "solved", "card_hash": None, "by": "goal_e3"}))
    return out
