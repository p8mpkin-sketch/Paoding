"""日志上的派生量：Intent 的完整状态、/work、预算账本投影、图服务自己追加的事件（§3.1.2、§3.5.2）。

全部是状态的纯函数，不读时钟、不做 IO、不调用模型。时钟是参数 `ts`（服务层给出的"现在"）或 state["now"]。
等级相关的判断一律经 levels.py 调用参考模型的副本，这里不重写等级语义。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict, cast

from . import levels as lv
from . import refmodel as rm
from .state import Lease, Request, ScopeRequest, ScopeRule, State

TASK_KINDS = ("bootstrap", "reason", "explore")
OPEN_RELAYS = 5  # 开放道：未交付时最多接力几个求解会话，用完转人（docs/design/open-lane/ §3.2）
FAIL_OUTCOMES = ("failed", "nothing", "budget_exhausted", "expired")
MAX_ATTEMPTS = 2  # Intent 回到 open 并累计尝试次数，两次后放弃（§3.4.4）
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


# ---------- 资源占用（v1.5 增量 11，规格 4.1） ----------

_RANK = {"r0": 0, "r1": 1, "r2": 2}


def requests(state: State) -> dict[str, ScopeRequest]:
    """扩权申请（runtime-grants §4.1）；第一条申请之前状态里没有这个键。"""
    return state.get("scope_requests", {})


def active(scope: list[ScopeRule]) -> list[ScopeRule]:
    """已批未撤的规则：执行层只编译这些（撤销的规则留在原位，下标不变）。"""
    return [r for r in scope if "revoked" not in r]


def pending_for_human(state: State, pid: str) -> list[str]:
    """等人批的扩权申请：不自动批、也不随 Intent 审批走的那些。"""
    return [
        x["id"]
        for x in requests(state).values()
        if x["problem_id"] == pid and x["status"] == "pending" and not x["auto"] and "intent" not in x
    ]


def holds(state: State, iid: str) -> dict[int, str]:
    """Intent 占用的授权规则：下标 → read | write。声明了 touches 就用 add_intent 校验过的那份；
    没声明时保守展开为"全部 risk ≤ Intent 风险的规则，r1 以上按写"，所以不声明也正确，只是并行度低。"""
    rec = state["intents"][iid]
    if "touches" in rec:
        return {t["rule"]: t["mode"] for t in rec["touches"]}
    scope = state["problems"][rec["problem_id"]]["scope"]
    rank = _RANK[rec["risk"]]
    return {
        k: "read" if r["risk"] == "r0" else "write"
        for k, r in enumerate(scope)
        if _RANK[r["risk"]] <= rank and "revoked" not in r
    }


def clash(a: Mapping[int, str], b: Mapping[int, str]) -> list[int]:
    """两份占用之间的写冲突：任一方写、另一方碰的规则下标（升序）。"""
    return sorted(k for k in a.keys() & b.keys() if "write" in (a[k], b[k]))


def resource_conflict(state: State, pid: str, iid: str) -> tuple[Lease, int] | None:
    """iid 与某个在途 explore 租约所服务的 Intent 有写冲突时，返回第一个这样的租约与冲突规则。
    同一条写规则同时只给一个在途租约：后来者不进 /work，等前一个租约结束。"""
    mine = holds(state, iid)
    for l in active_leases(state, pid):
        other = l.get("target")
        if l["kind"] != "explore" or other == iid or other not in state["intents"]:
            continue
        both = clash(mine, holds(state, other))
        if both:
            return l, both[0]
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
        failures = sum(
            1
            for l in ended
            if l["outcome"] in FAIL_OUTCOMES
            or (rec.get("done") and l["outcome"] == "done" and not _judge_pending(state, pid, iid))
        )
        if rec["risk"] == "r2" and last["outcome"] != "done" and not rm._is_approved(st, intent):
            return "needs_human"  # 不可逆动作不自动重做
        if failures >= MAX_ATTEMPTS:
            return "abandoned"
    return base


def _judge_pending(state: State, pid: str, target: str) -> bool:
    return any(
        r["target"] == target and r.get("verdict_seq") is None
        for r in state["requests"].values()
        if r["problem_id"] == pid
    )


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

Totals = dict[str, Any]  # 三条轨的合计：usd_milli、tokens、wall_s


class BudgetView(TypedDict):
    cap: Totals  # 只含开题时设了上限的轨
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
        amt = {
            "usd_milli": c["usd_milli"],
            "tokens": c["tokens_in"] + c["tokens_cached"] + c["tokens_out"],
            "wall_s": c["wall_s"],
        }
        spent = add(spent, amt)
        kind = c["lease_kind"]
        by_kind[kind] = add(by_kind.get(kind, zero()), amt)
        if kind == "judge":
            verify_spent = add(verify_spent, amt)
    reserved = zero()
    for l in active_leases(state, pid):
        reserved = add(reserved, l["reserve"])
    return {
        "cap": cap,
        "spent": spent,
        "reserved": reserved,
        "by_kind": by_kind,
        "verify_spent": verify_spent,
        "marks": list(p.get("marks", [])),
    }


def fits(
    view: BudgetView,
    reserve: Mapping[str, object],
    share: float | None = None,
    pool_spent: Totals | None = None,
    pool_reserved: Totals | None = None,
) -> bool:
    """spent + reserved + reserve ≤ cap，逐轨比较（只比较 cap 里设了的金额与 token 两轨）。"""
    for k in ("usd_milli", "tokens"):
        if k not in view["cap"]:
            continue
        cap = view["cap"][k]
        want = cast(Any, reserve.get(k)) or 0
        if view["spent"][k] + view["reserved"][k] + want > cap:
            return False
        if (
            share is not None
            and pool_spent is not None
            and pool_reserved is not None
            and pool_spent[k] + pool_reserved[k] + want > share * cap
        ):
            return False
    return True


def in_review(state: State, pid: str) -> bool:
    """预算复盘期：最近一个 budget_mark 之后，还没有 reason 租约释放。"""
    marks = state["problems"][pid].get("mark_seqs", [])
    if not marks:
        return False
    last = max(marks)
    return not any(l["kind"] == "reason" and not l["active"] and l["ended_seq"] > last for l in leases_of(state, pid))


# ---------- /work（§3.1.2） ----------


def recall_pending(state: State, pid: str) -> bool:
    """召回还没做完：开题登记了要复核的召回清单，且还没有一个 recall 租约结束过（过期也算结束）。"""
    rec = state["problems"][pid].get("recall") or {}
    if not rec.get("items"):
        return False
    return not any(l["kind"] == "recall" and not l["active"] for l in leases_of(state, pid))


def recheck_wanted(state: State, pid: str) -> list[dict[str, Any]]:
    """延迟判官的复判（external-verdict §5.3）：最近一次请求的裁决是 inconclusive(pending)，就派生一项复判。

    `not_before` 是判官给的 recheck_at；本函数不读时钟，到没到时候由判官运行器按自己的时钟判断。
    同一候选的复判不消耗次数上限（request_judge 按不同候选计数）。"""
    p = state["problems"][pid]
    latest: dict[tuple[str, str | None], Request] = {}
    for r in state["requests"].values():
        if r["problem_id"] != pid:
            continue
        key = (r["target"], r.get("candidate"))
        if key not in latest or int(r["id"][2:]) > int(latest[key]["id"][2:]):
            latest[key] = r
    out = []
    for (target, candidate), r in sorted(latest.items(), key=lambda kv: int(kv[1]["id"][2:])):
        if r.get("inconclusive") != "pending" or "recheck_at" not in r:
            continue
        jid = r["judge_id"]
        out.append(
            {
                "kind": "rejudge",
                "target": target,
                "judge": jid,
                "version": p["judge_snapshot"][jid]["version"],
                "candidate": candidate,
                "not_before": r["recheck_at"],
                "why": "pending",
            }
        )
    return out


def open_lane(state: State, pid: str) -> bool:
    return state["problems"][pid]["goal"]["accept"] == "open"


def delivered(state: State, pid: str) -> bool:
    """开放道的终态是否为 delivered：至少有一次完整回答或部分完成的交付（open-lane §5.1）。受阻不算。"""
    return any(d["outcome"] in ("answered", "partial") for d in state["problems"][pid].get("deliveries", []))


def _last_seq(p: Mapping[str, Any], key: str) -> int:
    xs = p.get(key) or []
    return int(xs[-1]["seq"]) if xs else -1


def open_round(state: State, pid: str) -> int:
    """开放道当前这一轮从哪条事件起算：最后一次追问的 seq；没有追问即开题（地图 Q31）。"""
    p = state["problems"][pid]
    return max(p["opened_seq"], _last_seq(p, "follow_ups"))


def halted(state: State, pid: str) -> bool:
    """叫停是否仍有效：叫停之后没有新的追问（地图 Q20、D12）。"""
    p = state["problems"][pid]
    h = p.get("halted")
    return h is not None and h["seq"] > _last_seq(p, "follow_ups")


def waiting_since(state: State, pid: str) -> int | None:
    """开放道交付之后等人的起点（事件时间戳，毫秒）：这一轮已经交付、没有在途会话、也没有更新的追问。
    闲置自动关从这里计时（地图 Q33）；不在等人时 None。"""
    p = state["problems"][pid]
    if p.get("closed") or p["goal"]["accept"] != "open":
        return None
    ds = p.get("deliveries") or []
    if not ds or ds[-1]["seq"] < open_round(state, pid):
        return None
    if any(l["active"] and l["kind"] == "solve" for l in leases_of(state, pid)):
        return None
    return int(ds[-1].get("ts", p["opened_ts"]))


IDLE_CLOSE_S = 7 * 86400  # 开放道交付后闲置自动关的缺省（open-lane §12 第 8 条），由 Config 在开题时抄进事件体


def idle_close_at(state: State, pid: str) -> int | None:
    """开题时没抄入 idle_close_s 的题（这项之前的日志）不闲置自动关。"""
    p = state["problems"][pid]
    since = waiting_since(state, pid)
    if since is None or "idle_close_s" not in p:
        return None
    return since + int(p["idle_close_s"]) * 1000


def open_work(state: State, pid: str) -> list[dict[str, Any]]:
    """开放道的 /work（open-lane §3.2、§3.3、§3.5）：一个求解会话做到底；未交付而会话结束就接力，每一轮至多
    OPEN_RELAYS 个；交付之后不再派，等人看（why=delivered，受阻为 blocked）；人追问开始新的一轮（地图 Q31）；
    人叫停之后不再派（Q20），在途的交出已有结果；接力用完或叫停后没有交付，转人（stalled）。
    没有 bootstrap、reason、explore，也没有判官项：开放道的 Goal 不设判官。"""
    p = state["problems"][pid]
    items: list[dict[str, Any]] = []
    start = open_round(state, pid)
    solves = [l for l in leases_of(state, pid) if l["kind"] == "solve" and l["issued_seq"] > start]
    ds = [d for d in (p.get("deliveries") or []) if d["seq"] > start]
    last = ds[-1] if ds else None
    busy = any(l["active"] for l in solves)
    if last is not None:
        items.append(
            {"kind": "human", "target": pid, "why": "blocked" if last["outcome"] == "blocked" else "delivered"}
        )
    elif not busy:
        if not halted(state, pid) and len(solves) < OPEN_RELAYS:
            items.append({"kind": "solve"})
        else:
            items.append({"kind": "human", "target": pid, "why": "stalled"})
    for rid in pending_for_human(state, pid):
        items.append({"kind": "human", "target": rid, "why": "scope_request"})
    return items


def work(state: State, pid: str) -> list[dict[str, Any]]:
    p = state["problems"].get(pid)
    if p is None or p.get("closed"):
        return []
    if open_lane(state, pid):
        return open_work(state, pid)
    st, res = lv.compute(state, pid)
    cache = {"ref": (st, res)}
    leases = leases_of(state, pid)
    items: list[dict[str, Any]] = []
    review = in_review(state, pid)
    task_leases = [l for l in leases if l["kind"] in TASK_KINDS]
    recalling = recall_pending(state, pid)
    if recalling and in_flight(state, pid, "recall") is None:
        items.append({"kind": "recall"})  # v1.5 增量 8：召回复核先于 Bootstrap，由不含模型的召回运行器领走
    if not task_leases and not recalling:
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
        triggers += [
            v["seq"]
            for v in state["verdicts"]
            if v["problem_id"] == pid and v["target"] == "goal" and v["result"] == "fail"
        ]
        reason_due = any(t > since for t in triggers)
        if reason_due:
            items.append({"kind": "reason", **({"reflect": True} if review else {})})
    statuses = {iid: intent_status(state, pid, iid, cache) for iid in st.intents}
    if not review:
        for iid, s in statuses.items():
            if s == "open" and resource_conflict(state, pid, iid) is None:
                items.append({"kind": "explore", "target": iid})
    pending = [r for r in state["requests"].values() if r["problem_id"] == pid and r.get("verdict_seq") is None]
    for r in pending:
        if in_flight(state, pid, "judge", r["id"]) is None:
            items.append({"kind": "judge", "target": r["id"]})
    for target, judge, version, candidate in rm.rejudge_wanted(st):
        if not any(r["target"] == target and r.get("candidate") == candidate for r in pending):
            items.append(
                {"kind": "rejudge", "target": target, "judge": judge, "version": version, "candidate": candidate}
            )
    rechecks = recheck_wanted(state, pid)
    items += rechecks
    for iid, s in statuses.items():
        if s == "needs_human":
            items.append({"kind": "human", "target": iid, "why": "needs_human"})
    stalled = (
        not active_leases(state, pid)
        and "open" not in statuses.values()
        and not pending
        and not rechecks
        and not reason_due
        and boot_done
    )
    for rid in pending_for_human(state, pid):
        items.append({"kind": "human", "target": rid, "why": "scope_request"})
    ready = acceptance_ready(state, pid) is not None
    if ready:
        items.append({"kind": "human", "target": pid, "why": "acceptance"})
    if stalled and not ready:
        items.append({"kind": "human", "target": pid, "why": "stalled"})
    return items


# ---------- 终态（3.1.2）与图服务自己追加的事件 ----------


def terminal(state: State, pid: str) -> str:
    """终态四值（open-lane §5.1）：solved 只来自判官判到 E3，accepted 只来自登记在先的清单逐条验过，
    delivered 只来自开放道的交付（未经判定），其余 unsolved。四者永不互换。"""
    p = state["problems"][pid]
    if p["goal"]["accept"] == "open":
        return "delivered" if delivered(state, pid) else "unsolved"
    if p["goal"]["accept"] == "judge" and lv.levels(state, pid)["goal"] == "E3":
        return "solved"
    return "accepted" if p.get("accepted") else "unsolved"


def acceptance_ready(state: State, pid: str) -> int | None:
    """accept=human 的题（宪章 D3）：最近一条 Goal 裁决为 pass、且晚于上一次验收或拒收时，交付物等人验收。
    返回那条裁决的 seq；不该验收时返回 None。拒收之后要等会话交出新的、再次通过结构检查的交付物。"""
    p = state["problems"][pid]
    if p["goal"]["accept"] != "human" or p.get("closed") or p.get("accepted"):
        return None
    goal = [v for v in state["verdicts"] if v["problem_id"] == pid and v["target"] == "goal"]
    if not goal:
        return None
    last = max(goal, key=lambda v: v["seq"])
    if last["result"] != "pass" or last["seq"] <= max([a["seq"] for a in p.get("accept_log", [])] or [0]):
        return None
    return last["seq"]


def closeout_items(state: State, pid: str) -> list[dict[str, Any]]:
    """四顾清单（3.1.8）。只对画像为 r1、r2 或 accept=human 的题列项；M0 的 r0 判官验收题恒为空。
    完整清单（范围修订、r2 凭据、stale/disputed/E3d）在 M4 落地，这里先给出 r1/r2 题的占位项。"""
    p = state["problems"][pid]
    if p["profile"]["reversibility"] == "r0" and p["goal"]["accept"] == "judge":
        return []
    items: list[dict[str, Any]] = []
    if p["profile"]["reversibility"] != "r0" or p["goal"]["accept"] == "human":
        items.append({"item": "closeout_review", "reason": p["profile"]["reversibility"]})
    if p["goal"]["accept"] in ("human", "open"):
        # 开放道（地图 v0.9 P7、Q32）同人工验收：采纳或不采纳关题之前，运行时扩过的权逐条确认
        # 人工验收的题（宪章 D3、地图 Q21）：影响面逐项列出，验收通过之前人要逐条确认（accept 的 closeout 字段）
        granted = [
            {k: r[k] for k in ("resource", "pattern", "actions", "risk")}
            for r in p["scope"]
            if "granted" in r and "revoked" not in r
        ]
        if granted:
            items.append({"item": "scope_granted", "rules": granted})
        live = sorted(l["id"] for l in active_leases(state, pid) if l["kind"] != "judge")
        # 开放道只列扩过的权：交付之后求解会话随即收尾，关题时的藏刀一并收掉它，不另要人确认
        if live and p["goal"]["accept"] == "human":
            items.append({"item": "leases_active", "leases": live})
    return items


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
        crossed = [
            k for k in ("usd_milli", "tokens") if k in view["cap"] and view["spent"][k] * 100 >= m * view["cap"][k]
        ]
        if crossed:
            out.append(("budget_mark", {"mark": m, "axis": crossed[0]}))
    if open_lane(state, pid):  # 开放道不自动关题：交付之后由人关，或由哮天犬按预算与墙钟关（open-lane §3.5）
        return out
    if lv.levels(state, pid)["goal"] == "E3" and not closeout_items(state, pid):
        out.append(("close_problem", {"terminal": "solved", "card_hash": None, "by": "goal_e3"}))
    elif p.get("accepted"):  # 人逐条验收全部通过（accept 事件已绑定收尾卡）：图服务随即关题，终态 accepted
        out.append(("close_problem", {"terminal": "accepted", "card_hash": None, "by": "accept"}))
    return out
