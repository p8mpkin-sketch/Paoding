"""交付族：deliver（开放道，docs/design/open-lane/ §3.4、§8）。

开放道的题没有判官。求解会话（solve）做完了用 deliver 交出答案，附上它认为支撑答案的执行留档、自检和没验证的部分。
内核对交付只做机械检查：引用的 Artifact 存在、属于本题、类别可采信（exec 或 input；主张另可引 knowledge）。
**内核检查“引用是真的”，不检查“结论是对的”。** 没有引用的主张允许存在，读端如实标成“无留档支撑”。

交付不关题：交付之后不再派新的求解会话，任务等人看（work 里的 human 项 why=delivered|blocked）。
"""

from __future__ import annotations

from typing import cast

from ..parse import Obj
from ..state import Actor, Body, Event, Problem, State
from .common import Config, Ok, Reject, _ref

OUTCOMES = ("answered", "partial", "blocked")  # 完整回答 | 部分完成 | 受阻
CHECK_RESULTS = ("pass", "fail", "skipped")
ADMISSIBLE = ("exec", "input")  # 自检的依据：执行层登记的输出，或人给的材料；模型写的 authored 不算证据
# 主张另可引 knowledge（K1，cz 2026-11-20）：人给的资料里的一段，由书库登记。读端与执行记录分开写，
# 不算“有执行记录”；判定道不认它（参考模型的 ADMISSIBLE 里没有它，add_fact 与验收清单都拒）。
CLAIM_ADMISSIBLE = (*ADMISSIBLE, "knowledge")
ANSWER_CLASSES = ("authored", "exec", "input")  # 答案本身可以是会话写的文字
CLAIMS_MAX, CHECKS_MAX, LIST_MAX, REFS_MAX = 64, 32, 32, 16
TEXT_MAX = 1000


def _refs(state: State, pid: str, o: Obj, key: str, where: str, ok: tuple[str, ...] = ADMISSIBLE) -> list[str] | Reject:
    refs = o.strings(key, [])
    if len(refs) > REFS_MAX or len(set(refs)) != len(refs):
        return Reject("schema_error", f"{where} 的 {key} 至多 {REFS_MAX} 个、不重复")
    for r in refs:
        err = _ref(state, pid, r, f"{where} 的依据")
        if err:
            return err
        cls = state["artifacts"][r]["class"]
        if cls not in ok:
            also = "、knowledge（资料）" if "knowledge" in ok else ""
            return Reject(
                "inadmissible_class", f"{where} 的依据 {r} 是 {cls} 类：只接受 exec（执行留档）、input（材料）{also}"
            )
    return refs


def _text(o: Obj, key: str, where: str) -> str | Reject:
    t = o.text(key).strip()
    if not t or len(t) > TEXT_MAX:
        return Reject("schema_error", f"{where}.{key} 须非空、不超过 {TEXT_MAX} 字")
    return t


def _texts(o: Obj, key: str) -> list[str] | Reject:
    out = [x.strip() for x in o.texts(key, [])]
    if len(out) > LIST_MAX or any(not x or len(x) > TEXT_MAX for x in out):
        return Reject("schema_error", f"{key} 至多 {LIST_MAX} 条，每条非空、不超过 {TEXT_MAX} 字")
    return out


def _v_deliver(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    p = state["problems"][pid]
    if p["goal"]["accept"] != "open":
        return Reject("forbidden_op", "只有开放道的题有交付：判定道的题用 claim_done 把候选交给判官")
    lease = state["leases"].get(actor.get("session") or "")
    if lease is None or lease["problem_id"] != pid or not lease["active"] or lease["kind"] != "solve":
        return Reject("forbidden_op", "交付只由本题在途的求解会话提交")
    allowed = {"outcome", "answer", "claims", "self_check", "unverified", "needs"}
    if not body.keys() <= allowed:
        return Reject("schema_error", f"deliver 的字段为 {sorted(allowed)}，多了 {sorted(body.keys() - allowed)}")
    outcome = body.get("outcome")
    if outcome not in OUTCOMES:
        return Reject("schema_error", f"outcome 取 {OUTCOMES}")
    out: Body = {"outcome": outcome, "lease": lease["id"]}
    answer = body.opt_string("answer")
    if answer is None and outcome != "blocked":
        return Reject("schema_error", "完整回答与部分完成都要给答案 answer（ArtifactId）")
    if answer is not None:
        err = _ref(state, pid, answer, "答案")
        if err:
            return err
        if state["artifacts"][answer]["class"] not in ANSWER_CLASSES:
            return Reject("inadmissible_class", "答案只接受 authored、exec 或 input 类")
        out["answer"] = answer
    claims = body.children("claims", [])
    if len(claims) > CLAIMS_MAX:
        return Reject("schema_error", f"主张至多 {CLAIMS_MAX} 条")
    out["claims"] = []
    for i, c in enumerate(claims):
        if not c.keys() <= {"text", "refs"} or "text" not in c:
            return Reject("schema_error", f"claims[{i}] 须为 {{text, refs?}}")
        text = _text(c, "text", f"claims[{i}]")
        if isinstance(text, Reject):
            return text
        refs = _refs(state, pid, c, "refs", f"claims[{i}]", CLAIM_ADMISSIBLE)
        if isinstance(refs, Reject):
            return refs
        out["claims"].append({"text": text, "refs": refs})
    checks = body.children("self_check", [])
    if len(checks) > CHECKS_MAX:
        return Reject("schema_error", f"自检至多 {CHECKS_MAX} 条")
    out["self_check"] = []
    for i, c in enumerate(checks):
        if not {"what", "result"} <= c.keys() <= {"what", "result", "refs", "item"}:
            return Reject("schema_error", f"self_check[{i}] 须为 {{what, result, refs?, item?}}")
        what = _text(c, "what", f"self_check[{i}]")
        if isinstance(what, Reject):
            return what
        if c.get("result") not in CHECK_RESULTS:
            return Reject("schema_error", f"self_check[{i}].result 取 {CHECK_RESULTS}")
        refs = _refs(state, pid, c, "refs", f"self_check[{i}]")
        if isinstance(refs, Reject):
            return refs
        row: Body = {"what": what, "result": c.string("result"), "refs": refs}
        if "item" in c:  # 对应开题时登记的哪一条必做自检（c1、c2…）
            item = c.string("item")
            if item not in {x["id"] for x in p["goal"].get("self_checks", [])}:
                return Reject("unknown_ref", f"self_check[{i}].item={item} 不是本题登记的自检项")
            row["item"] = item
        out["self_check"].append(row)
    for key in ("unverified", "needs"):
        xs = _texts(body, key)
        if isinstance(xs, Reject):
            return xs
        out[key] = xs
    if outcome == "blocked" and not out["needs"]:
        return Reject("schema_error", "受阻的交付要写明需要人提供什么（needs）")
    return Ok(out)


def _a_deliver(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    entry = {"id": f"d_{ev['seq']}", "seq": ev["seq"], **ev["body"]}
    s["problems"] = {**s["problems"], pid: cast(Problem, {**p, "deliveries": [*p.get("deliveries", []), entry]})}
