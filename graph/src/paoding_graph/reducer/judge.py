"""判定族：request_judge 与 judge_verdict（判据先行 I4、候选次数上限、无结论原因码）。"""

from __future__ import annotations

from typing import cast

from ..parse import Obj
from ..state import Actor, Check, Event, Request, State, Verdict
from .common import Config, Ok, Reject, _node, _ref

# ---------- 校验 ----------


def _registered_check(state: State, pid: str, target: str) -> tuple[Check | None, int | None]:
    """目标登记过的判据与次数上限。判据先行（I4）：判官只能是创建时登记的那一个。"""
    if target == "goal":
        g = state["problems"][pid]["goal"]
        return g["check"], g["max_attempts"]
    f = state["facts"].get(target)
    if f is not None and f["problem_id"] == pid:
        return f.get("check"), None
    i = state["intents"].get(target)
    if i is not None and i["problem_id"] == pid and "done" in i:
        return i["done"], i["done"]["max_attempts"]
    return None, None


def _v_request_judge(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    target, judge = body.string("target"), body.string("judge_id")
    node = _node(state, target)
    if node is not None and node["problem_id"] != pid:
        return Reject("scope_mismatch", f"{target} 属于别题")
    check, max_attempts = _registered_check(state, pid, target)
    if check is None:
        return Reject("unknown_ref", f"{target} 不是本题带判据的对象")
    if judge not in state["problems"][pid]["judges"]:
        return Reject("unknown_ref", f"判官 {judge} 未在本题启用")
    if judge != check["judge_id"]:
        return Reject("schema_error", "判官必须是登记判据时的那一个（判据先行）")
    candidate = body.opt_string("candidate")
    if max_attempts is not None:
        if candidate is None:
            return Reject("schema_error", "Goal 与带判据的 Intent 须给候选")
        err = _ref(state, pid, candidate, "候选")
        if err:
            return err
        tried = {
            r["candidate"] for r in state["requests"].values() if r["problem_id"] == pid and r["target"] == target
        }  # 每题都有名为 goal 的目标，须按题计数
        if candidate not in tried and len(tried) >= max_attempts:
            return Reject("quota_exceeded", f"{target} 已用满 {max_attempts} 个候选")
    elif candidate is not None:
        return Reject("schema_error", "论断的判定没有候选")
    return Ok({"target": target, "judge_id": judge, "candidate": candidate})


INCONCLUSIVE_REASONS = ("timeout", "env_error", "unsupported", "untouched")  # §3.3.2 reason_code 的无结论各项


def _v_judge_verdict(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    rid, result = body.string("request"), body.string("result")
    req = state["requests"].get(rid)
    if req is None or req["problem_id"] != pid:
        return Reject("unknown_ref", "判官请求不存在")
    if "verdict_seq" in req:
        return Reject("schema_error", "该请求已裁决")
    if result not in ("pass", "fail", "flaky", "inconclusive"):
        return Reject("schema_error", "result 只取 pass、fail、flaky、inconclusive")
    reason = body.text("reason") if "reason" in body else None
    if result == "inconclusive" and reason not in INCONCLUSIVE_REASONS:
        return Reject("schema_error", f"inconclusive 须带原因码 {INCONCLUSIVE_REASONS}")
    evidence = body.strings("evidence", [])
    for ref in evidence:
        err = _ref(state, pid, ref, "evidence")
        if err:
            return err
        if state["artifacts"][ref]["class"] != "judge":
            return Reject("inadmissible_class", "evidence 必须是 judge 类")
    snap = state["problems"][pid]["judge_snapshot"][req["judge_id"]]
    return Ok(
        {
            "request": rid,
            "result": result,
            "version": body.text("version"),
            "grade": snap["grade"],
            "evidence": evidence,
            **({"reason": reason} if reason is not None else {}),
        }
    )


# ---------- 应用 ----------


def _a_request_judge(s: State, ev: Event) -> None:
    rid = f"j_{ev['seq']}"
    s["requests"] = {**s["requests"], rid: cast(Request, {**ev["body"], "id": rid, "problem_id": ev["problem_id"]})}


def _a_judge_verdict(s: State, ev: Event) -> None:
    body, seq = ev["body"], ev["seq"]
    req = s["requests"][body["request"]]
    judged: Request = {**req, "verdict_seq": seq}
    if body["result"] == "inconclusive":
        judged["inconclusive"] = body["reason"]
    s["requests"] = {**s["requests"], req["id"]: judged}
    if body["result"] == "inconclusive":  # 抖动以外的无结论裁决不进裁决序列（§3.1.2），等级不变
        return
    verdict: Verdict = {
        "seq": seq,
        "problem_id": ev["problem_id"],
        "target": req["target"],
        "judge": req["judge_id"],
        "version": body["version"],
        "grade": body["grade"],
        "result": body["result"],
        "candidate": req["candidate"],
        "request": req["id"],
        "evidence": body["evidence"],
    }
    s["verdicts"] = s["verdicts"] + [verdict]
