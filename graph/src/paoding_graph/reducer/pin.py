"""体质修炼 003（docs/design/fenjue/tizhi-003-pinned-forms.md）：一道题此刻生效的功法，与人改钉它。

开题时 `open_problem.gongfa` 记下题开在哪一版功法之下（F3）；能力层每次派工都按这一版取功法（FJ6）。
- T4-3：领租约时 `lease.form` 按这道题**生效的**那一版查 `Config.gongfa_archive` 抄，不再照抄启动时的配置；
- T4-4：`repin` 只有人能提交，把一道在跑的题改钉到存档里更低的一版，下一次派工起生效，在跑的会话不受影响；

内核不认识任何一团火：版本只是 (摘要, 品阶) 两个不透明的值，形态表由组装根从功法存档取来，内核只查不解释。
`apply` 不读配置（R2）：改钉记进题的 `repins`，开题时的 `gongfa` 不动，两样都留着备查。
"""

from __future__ import annotations

from typing import cast

from ..parse import Obj
from ..state import Actor, Body, Event, Problem, State
from .common import Config, Ok, Reject
from .deliver import TEXT_MAX


def effective(p: Problem) -> Body | None:
    """这道题此刻生效的功法 {jie, digest}：最后一次改钉的那一版，否则开题时记下的；焚决之前的题没有。"""
    repins = p.get("repins") or []
    if repins:
        return dict(repins[-1]["to"])
    g = p.get("gongfa")
    return dict(g) if g else None


def form_for(p: Problem, kind: str, cfg: Config) -> str | None:
    """T4-3：这次租约的形态。题生效的那一版在存档表里就按它查，否则退回启动时的 Config.forms（F3 原样）。"""
    g = effective(p)
    if g is not None:
        for dg, _jie, forms in cfg.gongfa_archive:
            if dg == g["digest"]:
                return dict(forms).get(kind)
    return dict(cfg.forms).get(kind)


def _v_repin(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    p = state["problems"][pid]
    if not body.keys() <= {"to", "reason"}:
        return Reject("schema_error", "repin 的字段只有 to 与 reason")
    to = body.child("to")
    if to.keys() != {"jie", "digest"}:
        return Reject("schema_error", "to 是 {jie, digest}")
    jie, dg = to.integer("jie"), to.string("digest")
    reason = body.text("reason").strip()
    if not reason or len(reason) > TEXT_MAX:
        return Reject("schema_error", f"改钉要写原因，不超过 {TEXT_MAX} 字")
    now, opened = effective(p), p.get("gongfa")
    if now is None or opened is None:
        return Reject("forbidden_op", "这道题开题时没有记下功法版本（焚决之前），没有可改钉的")
    if not any(d == dg and j == jie for d, j, _ in cfg.gongfa_archive):
        return Reject("unknown_ref", f"功法存档里没有第 {jie} 阶 {dg[:12]}…")
    if dg == now["digest"]:
        return Reject("conflict", "这道题已经在这一版上")
    if jie >= now["jie"]:
        return Reject("forbidden_op", f"只能改到更低的一阶（此刻第 {now['jie']} 阶）")
    return Ok({"to": {"jie": jie, "digest": dg}, "reason": reason})


def _a_repin(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    entry = {"seq": ev["seq"], "ts": ev["ts"], "to": dict(ev["body"]["to"]), "reason": ev["body"]["reason"]}
    s["problems"] = {**s["problems"], pid: cast(Problem, {**p, "repins": [*p.get("repins", []), entry]})}
