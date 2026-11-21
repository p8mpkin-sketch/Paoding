"""复核（开放道，docs/design/open-lane/ §3.6；地图 Q34；体质修炼 002）。

交付之后可以起一个独立的复核会话（verify 席位）：全新上下文，只读交付与留档，逐条核对“这条引用是否真的支撑
这条主张”，能重跑的自检重跑一遍。它交回的是读数，用 review 提交：

- **复核只给读数**：不改终态、不拦交付、不进等级与任何判定统计。`delivered` 仍是“未经判定”。
- **内核对读数也只做机械检查**：对的是哪一次交付、每条主张恰好核一次、重跑引用的自检存在、依据的 Artifact
  存在、属本题、类别可采信。内核不判断复核说得对不对。
- **钱从验证份额里出**（`verify_share`）：verify 租约与判官租约同一个池子。
- 开题时抄入 `review: true` 的题才复核（设置 `lanes.review`）；没抄入的题（这项之前的日志）不复核。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..parse import Obj
from ..state import Actor, Body, Event, Problem, State
from .common import Config, Ok, Reject
from .deliver import CLAIM_ADMISSIBLE, TEXT_MAX, _refs, _texts

VERDICTS = ("supported", "unsupported", "unclear")  # 有据 | 引用与主张不符 | 看不出
RERUN_RESULTS = ("pass", "fail", "not_rerun")  # 重跑通过 | 重跑不过 | 没能重跑
REVIEWED_OUTCOMES = ("answered", "partial")  # 受阻的交付没有答案可核，不复核


def _v_review(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    p = state["problems"][pid]
    if p["goal"]["accept"] != "open" or not p.get("review"):
        return Reject("forbidden_op", "只有开题时开了复核的开放道题有复核")
    lease = state["leases"].get(actor.get("session") or "")
    if lease is None or lease["problem_id"] != pid or not lease["active"] or lease["kind"] != "verify":
        return Reject("forbidden_op", "复核只由本题在途的复核会话提交")
    allowed = {"delivery", "claims", "reruns", "counterexamples", "summary"}
    if not {"delivery", "claims", "summary"} <= body.keys() <= allowed:
        return Reject("schema_error", "review 的字段为 delivery、claims、summary，可选 reruns、counterexamples")
    did = body.string("delivery")
    if did != lease.get("target"):
        return Reject("scope_mismatch", f"这个复核会话核的是 {lease.get('target')}，不是 {did}")
    d = next((x for x in p.get("deliveries") or [] if x["id"] == did), None)
    if d is None:
        return Reject("unknown_ref", f"本题没有交付 {did}")
    if any(r["delivery"] == did for r in p.get("reviews") or []):
        return Reject("conflict", f"交付 {did} 已经复核过")
    summary = body.text("summary").strip()
    if not summary or len(summary) > TEXT_MAX:
        return Reject("schema_error", f"summary 须非空、不超过 {TEXT_MAX} 字")
    claims = body.children("claims")
    n = len(d["claims"])
    if sorted(c.get("claim") for c in claims) != list(range(n)):
        return Reject("schema_error", f"claims 要把交付的 {n} 条主张逐条核一次（claim 取 0…{n - 1}，不重复）")
    out_claims: list[Body] = []
    for c in sorted(claims, key=lambda c: c.integer("claim")):
        i = c.integer("claim")
        if not {"claim", "verdict", "note"} <= c.keys() <= {"claim", "verdict", "note", "refs"}:
            return Reject("schema_error", f"claims[{i}] 须为 {{claim, verdict, note, refs?}}")
        if c.get("verdict") not in VERDICTS:
            return Reject("schema_error", f"claims[{i}].verdict 取 {VERDICTS}")
        note = c.text("note").strip()
        if not note or len(note) > TEXT_MAX:
            return Reject("schema_error", f"claims[{i}].note 须非空、不超过 {TEXT_MAX} 字")
        refs = _refs(state, pid, c, "refs", f"claims[{i}]", CLAIM_ADMISSIBLE)
        if isinstance(refs, Reject):
            return refs
        out_claims.append({"claim": i, "verdict": c.string("verdict"), "note": note, "refs": refs})
    reruns = body.children("reruns", [])
    seen: set[int] = set()
    out_reruns: list[Body] = []
    for k, r in enumerate(reruns):
        if not {"check", "result"} <= r.keys() <= {"check", "result", "note", "refs"}:
            return Reject("schema_error", f"reruns[{k}] 须为 {{check, result, note?, refs?}}")
        j = r.integer("check")
        if not 0 <= j < len(d["self_check"]) or j in seen:
            return Reject("schema_error", f"reruns[{k}].check={j} 不是交付里的自检，或重复")
        seen.add(j)
        if r.get("result") not in RERUN_RESULTS:
            return Reject("schema_error", f"reruns[{k}].result 取 {RERUN_RESULTS}")
        refs = _refs(state, pid, r, "refs", f"reruns[{k}]")
        if isinstance(refs, Reject):
            return refs
        if r.get("result") != "not_rerun" and not refs:
            return Reject("schema_error", f"reruns[{k}] 说重跑了，要附重跑的执行留档（refs）")
        row: Body = {"check": j, "result": r.string("result"), "refs": refs}
        if "note" in r:
            note = r.text("note").strip()
            if not note or len(note) > TEXT_MAX:
                return Reject("schema_error", f"reruns[{k}].note 须非空、不超过 {TEXT_MAX} 字")
            row["note"] = note
        out_reruns.append(row)
    counter = _texts(body, "counterexamples")
    if isinstance(counter, Reject):
        return counter
    return Ok(
        {
            "delivery": did,
            "lease": lease["id"],
            "claims": out_claims,
            "reruns": sorted(out_reruns, key=lambda r: r["check"]),
            "counterexamples": counter,
            "summary": summary,
        }
    )


def _a_review(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    entry = {"id": f"rv_{ev['seq']}", "seq": ev["seq"], **ev["body"]}
    s["problems"] = {**s["problems"], pid: cast(Problem, {**p, "reviews": [*p.get("reviews", []), entry]})}


def readings(r: Mapping[str, Any]) -> Body:
    """一份复核的读数（读端与读数表共用）：主张几条、有据几条、不符几条、看不出几条；重跑过与不过各几条。"""
    verdicts = [c["verdict"] for c in r["claims"]]
    results = [x["result"] for x in r["reruns"]]
    return {
        "claims": len(verdicts),
        **{v: verdicts.count(v) for v in VERDICTS},
        "reruns": {x: results.count(x) for x in RERUN_RESULTS},
        "counterexamples": len(r["counterexamples"]),
    }
