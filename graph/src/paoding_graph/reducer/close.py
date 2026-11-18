"""关题族：close_problem（终态三值由图服务算出）与 budget_mark。"""

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
    if actor["kind"] == "graph" and term != "solved":
        return Reject("schema_error", "图服务只在 Goal 到 E3 时自动关题")
    if wk.closeout_items(state, pid) and actor["kind"] == "graph":
        return Reject("schema_error", "四顾清单非空，需人确认")
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


def _v_budget_mark(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    return Ok({"mark": body.integer("mark"), "axis": body.text("axis")})


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
