"""论断族：add_fact 与内容键（§3.1.2）。"""

from __future__ import annotations

from typing import Any, cast

from .. import levels as lv
from .. import refmodel as rm
from ..envelope import sha256_hex
from ..jcs import canonicalize
from ..parse import Obj
from ..state import Actor, Body, Event, Fact, State
from .common import Config, Ok, Reject, _check, _node, _ref, _session_count

# ---------- 校验 ----------


def _ref_artifacts(state: State) -> dict[str, Any]:
    return {aid: rm.Artifact(aid, a["class"], a["problem_id"]) for aid, a in state["artifacts"].items()}


def content_key(state: State, f: Body) -> str:
    """内容键（§3.1.2）：观察类取 check 的规范化哈希（spec_ref 按 Blob 哈希代入）；
    推断类取 title 与排序后的 premises。"""
    if f["claim_type"] == "observation":
        c = dict(f["check"])
        if "spec_ref" in c:
            c["spec_ref"] = state["artifacts"][c["spec_ref"]]["hash"]
        return "o:" + sha256_hex(canonicalize(c))
    return "i:" + sha256_hex(canonicalize([f["title"], sorted(f["premises"])]))


def _v_add_fact(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    allowed = {"title", "summary", "body_ref", "claim_type", "check", "premises", "grounds"}
    if "yielded_by" in body:
        return Reject("schema_error", "yielded_by 由租约推出，不由提议方填写")
    if not body.keys() <= allowed:
        return Reject("schema_error", f"多余字段 {sorted(body.keys() - allowed)}")
    claim_type, title, summary = body.string("claim_type"), body.string("title"), body.string("summary", "")
    if claim_type not in ("observation", "inference"):
        return Reject("schema_error", "claim_type 非法")
    if len(title) > 120 or len(summary) > 600:
        return Reject("schema_error", "title ≤120、summary ≤600 字符")
    premises, grounds = body.strings("premises", []), body.strings("grounds", [])
    check = _check(body.child("check")) if body.get("check") is not None else None
    body_ref = body.opt_string("body_ref")
    for ref in [body_ref, check.get("spec_ref") if check else None]:
        if ref is None:
            continue
        err = _ref(state, pid, ref, "引用")
        if err:
            return err
    # 等级不出题（I7）：前提指向别题的节点一律 scope_mismatch
    for p in premises:
        node = _node(state, p)
        if node is not None and node["problem_id"] != pid:
            return Reject("scope_mismatch", f"前提 {p} 属于别题")
    lvls = lv.levels(state, pid)
    code = str(
        rm.validate_add_fact(
            _ref_artifacts(state), lvls, pid, claim_type, check is not None, tuple(premises), tuple(grounds)
        )
    )
    if code != "ok":
        return Reject(code)
    if _session_count(state["facts"], actor.get("session")) >= cfg.fact_quota:
        return Reject("quota_exceeded", f"本任务已写 {cfg.fact_quota} 条论断")
    out: Body = {
        "title": title,
        "summary": summary,
        "claim_type": claim_type,
        "premises": premises,
        "grounds": grounds,
        **({"check": check} if check else {}),
        **({"body_ref": body_ref} if body_ref else {}),
    }
    key = content_key(state, out)
    existing = state["content_keys"].get(pid, {}).get(key)
    return Ok({**out, "content_key": key, **({"merge_into": existing} if existing else {})})


# ---------- 应用 ----------


def _a_add_fact(s: State, ev: Event) -> None:
    body, pid, session = ev["body"], ev["problem_id"], ev["actor"].get("session")
    target = body.get("merge_into")
    if target:  # 内容键相同：幂等合并，grounds 并入
        old = s["facts"][target]
        merged = old["grounds"] + [g for g in body["grounds"] if g not in old["grounds"]]
        s["facts"] = {**s["facts"], target: {**old, "grounds": merged}}
        return
    fid = f"f_{ev['seq']}"
    rec = {k: v for k, v in body.items() if k != "content_key"}
    lease = s["leases"].get(session) if session else None
    if lease and lease["kind"] == "explore":  # yields 边由租约推出，不由模型填写
        rec["yielded_by"] = lease["target"]
    s["facts"] = {**s["facts"], fid: cast(Fact, {**rec, "id": fid, "problem_id": pid, "session": session})}
    s["content_keys"] = {**s["content_keys"], pid: {**s["content_keys"].get(pid, {}), body["content_key"]: fid}}
