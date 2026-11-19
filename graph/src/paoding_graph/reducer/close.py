"""关题族：close_problem（终态三值由图服务算出）、budget_mark、人工验收 accept，以及续期门的 extend 与 budget_add。"""

from __future__ import annotations

from .. import work as wk
from ..parse import Obj
from ..state import Actor, Body, Event, Problem, State
from .common import Config, Ok, Reject, _seen

# ---------- 校验 ----------


def _v_close_problem(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if "terminal" in body and actor["kind"] != "graph":
        return Reject("schema_error", "terminal 是派生量，由图服务按三值算出")
    term = wk.terminal(state, pid)
    if actor["kind"] == "graph" and term not in ("solved", "accepted"):
        return Reject("schema_error", "图服务只在 Goal 到 E3、或人逐条验收通过之后自动关题")
    if wk.closeout_items(state, pid) and actor["kind"] == "graph" and term != "accepted":
        return Reject("schema_error", "四顾清单非空，需人确认")  # 验收通过的题：清单已由 accept 事件逐条绑定
    seen: Body | None = None
    if actor["kind"] == "human":
        if "card_hash" in body:
            return Reject("schema_error", "card_hash 不单独接受：所见的收尾清单经 seen {seq, card_hash} 给出并校验")
        if "seen" in body:  # 人关题时所见的四顾清单；带了就必须与链头相符
            checked = _seen(state, pid, "closeout", pid, body)
            if isinstance(checked, Reject):
                return checked
            seen = checked
    return Ok(
        {
            "terminal": term,
            "by": actor["kind"],
            "card_hash": seen["card_hash"] if seen else None,
            **({"seen": seen} if seen else {}),
            **({"reason": body.text("reason")} if "reason" in body else {}),
        }
    )


CHECK_NOTE_MAX = 2000


def _v_accept(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    """验收或拒收（宪章 D3、02 §3.3；规格 3.1.9 的 accept）：人按开题时登记的验收清单逐条判，绑定所见的收尾卡。

    body = {decision: accept | reject, checks: [{id, verdict: pass | fail, ref?, note?}], seen, reason?}
    全部 pass 才能 accept（之后图服务关题，终态 accepted）；任何一条 fail 只能 reject，回到人介入。"""
    p = state["problems"][pid]
    if p["goal"]["accept"] != "human":
        return Reject("forbidden_op", "只有 accept=human 的题有验收：判官验收的题终态只有 solved 与 unsolved")
    if not body.keys() <= {"decision", "checks", "seen", "reason", "closeout"}:
        return Reject("schema_error", "accept 的字段为 decision、checks、seen，可选 reason、closeout")
    decision = body.get("decision")
    if decision not in ("accept", "reject"):
        return Reject("schema_error", "decision 取 accept 或 reject")
    seen = _seen(state, pid, "closeout", pid, body)  # 校验先于状态检查：所见的卡过期即 stale_view
    if isinstance(seen, Reject):
        return seen
    if wk.acceptance_ready(state, pid) is None:
        return Reject("schema_error", "还没有待验收的交付物：要等 Goal 的结构检查通过（拒收之后要等新的交付物）")
    items = {a["id"]: a for a in p["goal"]["acceptance"]}
    checks: list[Body] = []
    for c in body.children("checks"):
        if not {"id", "verdict"} <= c.keys() <= {"id", "verdict", "ref", "note"}:
            return Reject("schema_error", "每项须为 {id, verdict, ref?, note?}")
        cid, verdict = c.string("id"), c.get("verdict")
        if cid not in items or any(x["id"] == cid for x in checks):
            return Reject("schema_error", f"验收项 {cid} 不在清单里或重复")
        if verdict not in ("pass", "fail"):
            return Reject("schema_error", "verdict 取 pass 或 fail")
        out: Body = {"id": cid, "verdict": verdict}
        if "ref" in c:
            ref = c.string("ref")
            art = state["artifacts"].get(ref)
            if art is None or art["problem_id"] != pid:
                return Reject("unknown_ref", f"验收项 {cid} 的依据 {ref} 不是本题的 Artifact")
            if art["class"] not in ("exec", "input"):
                return Reject("inadmissible_class", "验收依据只接受 exec 类或 input 类")
            out["ref"] = ref
        if "note" in c:
            note = c.text("note").strip()
            if len(note) > CHECK_NOTE_MAX:
                return Reject("schema_error", f"说明不超过 {CHECK_NOTE_MAX} 字")
            if note:
                out["note"] = note
        need = items[cid].get("needs")
        if verdict == "pass" and need == "artifact" and "ref" not in out:
            return Reject("missing_evidence", f"验收项 {cid} 要附交付物（exec 类或 input 类 Artifact）")
        if verdict == "pass" and need == "note" and "note" not in out:
            return Reject("missing_evidence", f"验收项 {cid} 要附说明")
        checks.append(out)
    if len(checks) != len(items):
        return Reject("schema_error", "验收清单里每一条都要判")
    failed = [c["id"] for c in checks if c["verdict"] == "fail"]
    if decision == "accept" and failed:
        return Reject("schema_error", f"有不通过的条目（{'、'.join(failed)}）：只能拒收")
    reason = body.text("reason").strip() if "reason" in body else ""
    if decision == "reject" and not reason:
        return Reject("schema_error", "拒收须写理由（会作为指导之外的记录留在时间轴上）")
    # 关题三步不可跳（地图 Q21、AC9.2）：验收通过之前，四顾清单的每一项都要人逐条确认
    confirmed = [str(x) for x in body.get("closeout") or []] if isinstance(body.get("closeout"), list) else None
    if "closeout" in body and confirmed is None:
        return Reject("schema_error", "closeout 是已确认的四顾项名单")
    want = [str(i["item"]) for i in wk.closeout_items(state, pid)]
    if decision == "accept":
        missing = [x for x in want if x not in (confirmed or [])]
        if missing:
            return Reject("schema_error", f"四顾清单有未确认项（{'、'.join(missing)}）：逐条确认之后才能验收")
        if confirmed and set(confirmed) - set(want):
            return Reject("schema_error", f"四顾清单里没有 {'、'.join(sorted(set(confirmed) - set(want)))}")
    return Ok(
        {
            "decision": decision,
            "checks": checks,
            "seen": seen,
            "card_hash": seen["card_hash"],
            **({"reason": reason} if reason else {}),
            **({"closeout": want} if decision == "accept" else {}),
        }
    )


def _a_accept(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    b = ev["body"]
    entry = {
        "seq": ev["seq"],
        "decision": b["decision"],
        "checks": b["checks"],
        **({"reason": b["reason"]} if "reason" in b else {}),
    }
    nxt: Problem = {**p, "accept_log": [*p.get("accept_log", []), entry]}
    if ev["body"]["decision"] == "accept":
        nxt["accepted"] = True
    s["problems"] = {**s["problems"], pid: nxt}


def _v_budget_mark(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    return Ok({"mark": body.integer("mark"), "axis": body.text("axis")})


def _v_extend(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    """放行续期门（§3.5.2 的 pd extend）：门关着时才接受，绑定所见的续期卡。body = {seen}"""
    if not body.keys() <= {"seen"}:
        return Reject("schema_error", "extend 只有 seen 一个字段")
    seen = _seen(state, pid, "extension", pid, body)
    if isinstance(seen, Reject):
        return seen
    if not wk.extension_pending(state, pid):
        return Reject("schema_error", "续期门没有关着：没有越过 80% 标记、50% 以来已有进展，或已经放行")
    return Ok({"seen": seen})


def _v_budget_add(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    """追加题预算（HMI §3.10 的第二个选项）。body = {usd_milli, seen?}：续期门关着时追加须带所见的续期卡，
    并同时放行；单题硬顶（设置层 open_cap_usd_milli）照样管追加后的上限。"""
    if not body.keys() <= {"usd_milli", "seen"}:
        return Reject("schema_error", "budget_add 的字段为 usd_milli，可选 seen")
    add = body.integer("usd_milli")
    if add <= 0:
        return Reject("schema_error", "追加的金额须为正")
    p = state["problems"][pid]
    cap = p["budget"]["usd_milli"] + add
    if cfg.open_cap_usd_milli is not None and cap > cfg.open_cap_usd_milli:
        return Reject("over_budget", f"追加后的上限 {cap} 超过单题硬顶 {cfg.open_cap_usd_milli}（设置层）")
    gated = wk.extension_pending(state, pid)
    seen: Body | None = None
    if gated or "seen" in body:
        checked = _seen(state, pid, "extension", pid, body)
        if isinstance(checked, Reject):
            return checked
        seen = checked
    return Ok({"usd_milli": add, "cap_usd_milli": cap, **({"seen": seen} if seen else {})})


# ---------- 应用 ----------


def _a_close_problem(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    closed: Problem = {**p, "closed": True, "terminal": ev["body"]["terminal"], "closed_seq": ev["seq"]}
    s["problems"] = {**s["problems"], pid: closed}


def _a_budget_mark(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    marked: Problem = {
        **p,
        "marks": p.get("marks", []) + [ev["body"]["mark"]],
        "mark_seqs": p.get("mark_seqs", []) + [ev["seq"]],
    }
    s["problems"] = {**s["problems"], pid: marked}


def _a_extend(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    nxt: Problem = {**p, "extended_seqs": [*p.get("extended_seqs", []), ev["seq"]]}
    s["problems"] = {**s["problems"], pid: nxt}


def _a_budget_add(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    nxt: Problem = {
        **p,
        "budget": {**p["budget"], "usd_milli": ev["body"]["cap_usd_milli"]},
        "extended_seqs": [*p.get("extended_seqs", []), ev["seq"]],
    }
    s["problems"] = {**s["problems"], pid: nxt}
