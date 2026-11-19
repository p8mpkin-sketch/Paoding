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
        if "check" not in g:  # 开放道：Goal 没有判官，结论随 deliver 交付（docs/design/open-lane/ §3.4）
            return None, None
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
    if actor["kind"] == "judge" and not any(
        r["problem_id"] == pid and r["target"] == target and r["judge_id"] == judge and r.get("candidate") == candidate
        for r in state["requests"].values()
    ):
        # 判官运行器补的复判（unstable 或延迟判官的 pending）只能重复已有的请求，不能自己挑候选
        return Reject("forbidden_op", "判官令牌只能复判已有请求的同一目标、判官与候选")
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


# §3.3.2 reason_code 的无结论各项；no_contrast 是对照判据的：主运行与对照都通过，结果不依赖输入（§3.3.3）
# pending 是延迟判官的"回执还没出"（external-verdict §5.3）：带 recheck_at，图服务到时派生复判，等级不变
INCONCLUSIVE_REASONS = ("timeout", "env_error", "unsupported", "untouched", "no_contrast", "pending")
# 对照运行的结束类别（§3.3.3 的 control_end）：not_run 表示主运行没通过，对照不必跑
CONTROL_ENDS = ("pass", "fail", "flaky", "timeout", "env_error", "untouched", "unsupported", "not_run")


def _controlled(state: State, pid: str, target: str) -> bool:
    f = state["facts"].get(target)
    return f is not None and f["problem_id"] == pid and "control" in f.get("check", {})


def _control_rule(result: str, reason: str | None, end: str | None, controlled: bool) -> str | None:
    """带对照的判据：主运行通过且对照不通过才算通过。内核再核一遍，不只信判官运行器。"""
    if not controlled:
        if end is not None or reason == "no_contrast":
            return "目标的判据不带对照，裁决不能带 control_end 或 no_contrast"
        return None
    if end not in CONTROL_ENDS:
        return f"带对照的判据，裁决须带 control_end {CONTROL_ENDS}"
    if result == "pass" and end != "fail":
        return "带对照的判据：主运行通过且对照不通过才算通过"
    if reason == "no_contrast" and end not in ("pass", "flaky"):
        return "no_contrast 只在对照也通过（或抖动）时给出"
    return None


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
    recheck_at: int | None = None
    snap = state["problems"][pid]["judge_snapshot"][req["judge_id"]]
    if reason == "pending":
        if result != "inconclusive" or snap["kind"] != "deferred":
            return Reject("schema_error", "pending 只用于延迟判官（kind=deferred）的 inconclusive")
        recheck_at = body.get("recheck_at")
        if type(recheck_at) is not int or recheck_at <= 0:
            return Reject("schema_error", "pending 须带 recheck_at（毫秒，正整数）")
    elif "recheck_at" in body:
        return Reject("schema_error", "recheck_at 只随 pending 给出")
    end = body.text("control_end") if "control_end" in body else None
    controlled = _controlled(state, pid, req["target"])
    why = _control_rule(result, reason, end, controlled)
    if why:
        return Reject("schema_error", why)
    evidence = body.strings("evidence", [])
    for ref in evidence:
        err = _ref(state, pid, ref, "evidence")
        if err:
            return err
        if state["artifacts"][ref]["class"] != "judge":
            return Reject("inadmissible_class", "evidence 必须是 judge 类")
    return Ok(
        {
            "request": rid,
            "result": result,
            "version": body.text("version"),
            "grade": snap["grade"],
            "evidence": evidence,
            **({"reason": reason} if reason is not None else {}),
            **({"recheck_at": recheck_at} if recheck_at is not None else {}),
            **({"control_end": end, "controlled": result == "pass"} if controlled else {}),
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
        if "recheck_at" in body:
            judged["recheck_at"] = body["recheck_at"]
    if "control_end" in body:
        judged["control_end"] = body["control_end"]
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
    if "control_end" in body:  # 对照判据：支持记录带 controlled，另记对照运行的结束类别（§3.3.3）
        verdict["controlled"] = body["controlled"]
        verdict["control_end"] = body["control_end"]
    s["verdicts"] = s["verdicts"] + [verdict]
