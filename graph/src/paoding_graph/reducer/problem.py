"""开题族：open_problem、register_artifact、profile_override（画像的推导与事后覆盖）。"""

from __future__ import annotations

from typing import cast

from .. import refmodel as rm
from ..parse import Obj
from ..practice import LANES, violations
from ..state import Actor, Artifact, Body, Event, JudgeEntry, Problem, Profile, ScopeRule, State
from . import recall
from .common import _HEX64, RISK_RANK, RISKS, Config, Ok, Reject, _check, _reason, _ref, _rule

# ---------- 校验 ----------


def _derive_profile(scope: list[ScopeRule], goal_judge: JudgeEntry, cfg: Config) -> Profile:
    """画像推导（§3.1.2）。人不填写；只在开题、范围修订与人工覆盖时重算，结果写进事件体。"""
    reversibility = max((r["risk"] for r in scope), key=RISK_RANK.__getitem__)
    if goal_judge["grade"] == "advisory":
        judge = "none"
    elif goal_judge["kind"] == "deferred" or goal_judge["grade"] == "consistent":
        judge = "deferred"
    elif goal_judge["max_cost"] <= cfg.cheap_judge_max_cost:
        judge = "hard"
    else:
        judge = "costly"
    info = "partial" if any(r["resource"] in cfg.external_resources for r in scope) else "complete"
    return {"info": info, "judge": judge, "reversibility": reversibility}


def _v_open_problem(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if pid in state["problems"]:
        return Reject("schema_error", "题目已存在")
    if "profile" in body:
        return Reject("schema_error", "profile 是派生字段，提交时不接受")
    allowed = {"title", "origin", "goal", "scope", "budget", "env", "judges"}
    optional = {"labels", "recall"}  # v1.5 增量 9、10：可选，缺省时事件体与旧版相同
    if not allowed <= body.keys() <= allowed | optional:
        return Reject("schema_error", f"字段应为 {sorted(allowed)}，可选 {sorted(optional)}")
    judges = body.strings("judges")
    for j in judges:
        if j not in cfg.judges:
            return Reject("unknown_ref", f"判官 {j} 未注册")
    g = body.child("goal")
    check = _check(g.child("check"))
    if check["judge_id"] not in judges:
        return Reject("unknown_ref", "Goal 判官不在本题启用的判官里")
    if g.get("accept") != "judge":
        return Reject("schema_error", "M0 只实现 accept=judge")
    max_attempts = g.get("max_attempts")
    if type(max_attempts) is not int or max_attempts < 1:
        return Reject("schema_error", "goal.max_attempts 必须是正整数")
    goal = {**g.raw, "check": check}
    scope = [_rule(r) for r in body.children("scope")]
    if not scope:
        return Reject("schema_error", "scope 必填且非空")
    b = body.child("budget")
    budget: Body = {k: b.number(k) for k in ("usd_milli", "wall_s", "verify_share", "bootstrap_share")}
    if "tokens" in b:
        budget["tokens"] = b.number("tokens")
    if not (
        budget["usd_milli"] > 0
        and budget["wall_s"] > 0
        and 0 <= budget["verify_share"] <= 1
        and 0 <= budget["bootstrap_share"] <= 1
        and budget.get("tokens", 1) > 0
    ):
        return Reject("schema_error", "预算必须为正，份额在 [0,1]")
    for key, cap, unit in (("usd_milli", cfg.open_cap_usd_milli, "毫美元"), ("wall_s", cfg.open_cap_wall_s, "秒")):
        if cap is not None and budget[key] > cap:
            return Reject("over_budget", f"budget.{key}={budget[key]} 超过单题硬顶 {cap} {unit}")
    o = body.child("origin")
    if not {"statement_ref", "materials"} <= o.keys() <= {"statement_ref", "materials", "draft"}:
        return Reject("schema_error", "origin 字段应为 statement_ref、materials，可选 draft")
    statement_ref, materials = o.string("statement_ref"), o.strings("materials")
    draft: Body | None = None
    if "draft" in o:
        # 一句话开题（增量 13）：出处账的引用与道别。policy 由图服务从已加载的信封抄入，提交时不接受
        d = o.child("draft")
        if d.keys() != {"record", "lane"} or d.get("lane") not in LANES:
            return Reject("schema_error", "origin.draft 须为 {record, lane: practice|confirm}")
        draft = {"record": d.string("record"), "lane": d.string("lane")}
    for ref in [statement_ref, *materials, *([draft["record"]] if draft else [])]:
        err = _ref(state, pid, ref, "Origin 引用")
        if err:
            return err
        if state["artifacts"][ref]["class"] != "input":
            return Reject("inadmissible_class", "Origin 只接受 input 类")
    if draft is not None and draft["lane"] == "practice":
        # 练习道信封（增量 15）：零确认没有人在回路里，"它最多能做什么"只在这里、由唯一写入者检查
        if cfg.practice is None:
            return Reject("forbidden_op", "本部署没有加载练习道信封，不接受练习道开题")
        bad = violations(cfg.practice, list(scope), check, budget, max_attempts)
        if bad:
            return Reject("forbidden_op", "练习道信封不许：" + "；".join(bad))
        draft["policy"] = cfg.practice.stamp()
    snapshot = {j: cfg.judges[j] for j in judges}
    extras = recall.open_extras(state, pid, body, judges)
    if isinstance(extras, Reject):
        return extras
    return Ok(
        {
            "title": body.text("title"),
            "origin": {
                "statement_ref": statement_ref,
                "materials": materials,
                **({"draft": draft} if draft is not None else {}),
            },
            "goal": goal,
            "scope": scope,
            "budget": budget,
            "env": body.child("env").raw,
            "judges": judges,
            "judge_snapshot": {j: dict(e) for j, e in snapshot.items()},
            "profile": _derive_profile(scope, snapshot[check["judge_id"]], cfg),
            **extras,
            # 宪章 D5：开在哪一版设置之下。由图服务抄入，提交体里不接受；不进等级、消费门与画像
            **({"settings": {"version": cfg.settings[0], "digest": cfg.settings[1]}} if cfg.settings else {}),
        }
    )


_EXEC_FIELDS = {
    "sandbox_id",
    "base",
    "baseline_ref",
    "tool",
    "command",
    "cwd",
    "exit_code",
    "touched",
    "started_at",
    "ended_at",
    "truncated",
}


def _v_register_artifact(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    cls = body.string("class")
    if cls not in rm.REGISTRAR:
        return Reject("schema_error", f"未知类别 {cls}")
    if rm.validate_register(actor["kind"], cls) != "ok":
        return Reject("forbidden_op", f"{actor['kind']} 的令牌不能登记 {cls} 类")
    if pid not in state["problems"] and actor["kind"] != "human":
        return Reject("unknown_ref", f"题目 {pid} 未开")
    if "producer" in body:
        return Reject("schema_error", "producer 由令牌决定，提交时不接受")
    size = body.req("size")
    if not _HEX64.match(body.string("hash")) or type(size) is not int or size < 0:
        return Reject("schema_error", "hash 须为 sha256，size 须为非负整数")
    ex: Body | None = None
    if cls in ("exec", "judge"):
        if "exec" not in body or body.child("exec").keys() != _EXEC_FIELDS:
            return Reject("schema_error", f"{cls} 类必须带完整的 exec 出处字段")
        ex = dict(body.child("exec").raw)
    elif "exec" in body:
        return Reject("schema_error", "只有 exec 与 judge 类带 exec 出处字段")
    parents = body.strings("parents", [])
    for p in parents:
        err = _ref(state, pid, p, "parent")
        if err:
            return err
    producer = {"actor": actor["id"], **({"session": actor["session"]} if "session" in actor else {})}
    return Ok(
        {
            "hash": body.string("hash"),
            "size": size,
            "media_type": body.text("media_type"),
            "class": cls,
            "parents": parents,
            "producer": producer,
            **({"exec": ex} if ex is not None else {}),
        }
    )


PROFILE_AXES: dict[str, tuple[str, ...]] = {
    "info": ("complete", "partial"),
    "judge": ("hard", "costly", "deferred", "none"),
    "reversibility": RISKS,
}


def _v_profile_override(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    """画像只能事后覆盖并留痕（裁决 A7）：逐轴覆盖，理由必填，推出值与覆盖值都留在事件体里。"""
    axis, value = body.string("axis"), body.string("value")
    if axis not in PROFILE_AXES:
        return Reject("schema_error", f"轴只取 {sorted(PROFILE_AXES)}")
    if value not in PROFILE_AXES[axis]:
        return Reject("schema_error", f"{axis} 只取 {PROFILE_AXES[axis]}")
    reason = _reason(body)
    if not reason:
        return Reject("schema_error", "覆盖须写理由")
    p = state["problems"][pid]
    derived = cast(dict[str, str], p.get("derived_profile", p["profile"]))
    return Ok({"axis": axis, "value": value, "reason": reason, "derived": derived[axis]})


# ---------- 应用 ----------


def _a_open_problem(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    opened = cast(Problem, {**ev["body"], "id": pid, "closed": False, "opened_seq": ev["seq"], "opened_ts": ev["ts"]})
    s["problems"] = {**s["problems"], pid: opened}


def _a_register_artifact(s: State, ev: Event) -> None:
    aid = f"a_{ev['seq']}"
    s["artifacts"] = {**s["artifacts"], aid: cast(Artifact, {**ev["body"], "id": aid, "problem_id": ev["problem_id"]})}


def _a_profile_override(s: State, ev: Event) -> None:
    body, pid = ev["body"], ev["problem_id"]
    p = s["problems"][pid]
    s["problems"] = {
        **s["problems"],
        pid: {
            **p,
            "derived_profile": p.get("derived_profile", p["profile"]),
            "profile": cast(Profile, {**p["profile"], body["axis"]: body["value"]}),
            "profile_overrides": p.get("profile_overrides", [])
            + [
                {
                    "axis": body["axis"],
                    "value": body["value"],
                    "reason": body["reason"],
                    "derived": body["derived"],
                    "seq": ev["seq"],
                    "by": ev["actor"]["id"],
                }
            ],
        },
    }
