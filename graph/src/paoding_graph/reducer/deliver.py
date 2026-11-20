"""交付族：deliver、follow_up、halt（开放道，docs/design/open-lane/ §3.4、§3.5、§8；地图 v0.9 Q20、Q31）。

开放道的题没有判官。求解会话（solve）做完了用 deliver 交出答案，附上它认为支撑答案的执行留档、自检和没验证的部分。
内核对交付只做机械检查：引用的 Artifact 存在、属于本题、类别可采信（exec 或 input）。**内核检查“引用是真的”，
不检查“结论是对的”。** 没有引用的主张允许存在，读端如实标成“无留档支撑”。

交付不关题：交付之后不再派新的求解会话，任务等人看（work 里的 human 项 why=delivered|blocked）。

人在交付之后的两个动作（地图 02 §4 的 P4、P6、P8）：
- follow_up（追问）：写一句话，任务回到求解，带着工作区与上一轮交付。开放道没有续期门（D10）：剩余预算低于
  收尾保留（题预算的 10%）时，追问必须附追加预算 budget_add_usd_milli，追加后的题预算受单题硬顶管。
- halt（叫停）：任何时候可以停。之后不再派新的求解会话；在途的收到收尾轮，哮天犬在 HALT_GRACE_S 之后仍未交付
  就终止它（D12）。追问会解除叫停。
"""

from __future__ import annotations

from typing import cast

from ..parse import Obj
from ..state import Actor, Body, Event, Problem, State
from ..work import budget_view
from .common import Config, Ok, Reject, _ref

OUTCOMES = ("answered", "partial", "blocked")  # 完整回答 | 部分完成 | 受阻
CHECK_RESULTS = ("pass", "fail", "skipped")
ADMISSIBLE = ("exec", "input")  # 主张与自检的依据：执行层登记的输出，或人给的材料；模型写的 authored 不算证据
ANSWER_CLASSES = ("authored", "exec", "input")  # 答案本身可以是会话写的文字
CLAIMS_MAX, CHECKS_MAX, LIST_MAX, REFS_MAX = 64, 32, 32, 16
TEXT_MAX = 1000
FOLLOW_UP_MAX = 2000  # 追问的字数上限（与网页输入框一致）
CLOSE_RESERVE = 0.1  # 收尾保留：题预算的这一份留给收尾交付（open-lane §3.3 第 2 条）
HALT_GRACE_S = 60  # 叫停之后等在途会话收尾交付多久（D12），过了由哮天犬终止


def _refs(state: State, pid: str, o: Obj, key: str, where: str) -> list[str] | Reject:
    refs = o.strings(key, [])
    if len(refs) > REFS_MAX or len(set(refs)) != len(refs):
        return Reject("schema_error", f"{where} 的 {key} 至多 {REFS_MAX} 个、不重复")
    for r in refs:
        err = _ref(state, pid, r, f"{where} 的依据")
        if err:
            return err
        cls = state["artifacts"][r]["class"]
        if cls not in ADMISSIBLE:
            return Reject(
                "inadmissible_class", f"{where} 的依据 {r} 是 {cls} 类：只接受 exec（执行留档）或 input（材料）"
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
        refs = _refs(state, pid, c, "refs", f"claims[{i}]")
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


def last_seq(p: Problem, key: str) -> int:
    """开放道某一类记录（deliveries、follow_ups）里最后一条的 seq；没有即 -1。"""
    xs = cast(list[Body], p.get(key) or [])
    return int(xs[-1]["seq"]) if xs else -1


def remaining_usd_milli(state: State, pid: str) -> int:
    v = budget_view(state, pid)
    return int(v["cap"].get("usd_milli", 0)) - int(v["spent"]["usd_milli"])


def _v_follow_up(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    p = state["problems"][pid]
    if p["goal"]["accept"] != "open":
        return Reject("forbidden_op", "只有开放道的题能追问：判定道的题用 hint 给指导")
    if not body.keys() <= {"text", "seen", "budget_add_usd_milli"} or "text" not in body or "seen" not in body:
        return Reject("schema_error", "follow_up 的字段为 text、seen {seq}，可选 budget_add_usd_milli")
    text = body.text("text").strip()
    if not text or len(text) > FOLLOW_UP_MAX:
        return Reject("schema_error", f"追问须非空、不超过 {FOLLOW_UP_MAX} 字")
    seen = body.get("seen")
    if not (isinstance(seen, dict) and set(seen) == {"seq"} and type(seen["seq"]) is int and seen["seq"] >= 0):
        return Reject("schema_error", "follow_up 须带 seen {seq}：你看到的链头")
    last_d = last_seq(p, "deliveries")
    if last_d < 0:
        return Reject("conflict", "还没有交付：在做的时候用 hint 补充一句")
    if last_seq(p, "follow_ups") > last_d:
        return Reject("conflict", "上一次追问还没有交付：等它交付之后再问，或用 hint 补充一句")
    if seen["seq"] < last_d:
        return Reject("stale_view", "你看到的不是最新一次交付：刷新之后再问")
    add = body.get("budget_add_usd_milli")
    if add is not None and (type(add) is not int or add <= 0):
        return Reject("schema_error", "budget_add_usd_milli 是正整数（毫美元）")
    cap = int(p["budget"]["usd_milli"])
    after = cap + (add or 0)
    if cfg.open_cap_usd_milli is not None and after > cfg.open_cap_usd_milli:
        return Reject("over_budget", f"追加后的题预算 {after} 超过单题硬顶 {cfg.open_cap_usd_milli} 毫美元")
    left = remaining_usd_milli(state, pid) + (add or 0)
    need = -(-after * int(CLOSE_RESERVE * 100) // 100)  # 收尾保留：追加后题预算的 10%，向上取整
    if left < need:
        return Reject(
            "over_budget",
            f"剩余 {left} 毫美元，低于收尾保留 {need}：追问要附追加预算 budget_add_usd_milli",
        )
    return Ok(
        {
            "text": text,
            "seen": {"seq": seen["seq"]},
            "after_delivery": p["deliveries"][-1]["id"],
            **({"budget_add_usd_milli": add} if add else {}),
        }
    )


def _v_halt(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    p = state["problems"][pid]
    if p["goal"]["accept"] != "open":
        return Reject("forbidden_op", "叫停目前只用于开放道（严格道的 terminate_lease 仍待裁决，地图 Q20）")
    if not body.keys() <= {"reason"}:
        return Reject("schema_error", "halt 的字段只有可选的 reason")
    h = p.get("halted")
    if h is not None and h["seq"] > last_seq(p, "follow_ups"):
        return Reject("conflict", "已经叫停了")
    reason = body.text("reason").strip() if "reason" in body else ""
    if len(reason) > TEXT_MAX:
        return Reject("schema_error", f"reason 不超过 {TEXT_MAX} 字")
    return Ok({"reason": reason} if reason else {})


def _a_follow_up(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    b = ev["body"]
    entry = {
        "id": f"u_{ev['seq']}",
        "seq": ev["seq"],
        "ts": ev["ts"],
        "text": b["text"],
        "after_delivery": b["after_delivery"],
    }
    nxt = cast(Problem, {**p, "follow_ups": [*p.get("follow_ups", []), entry]})
    if b.get("budget_add_usd_milli"):
        nxt["budget"] = {**p["budget"], "usd_milli": p["budget"]["usd_milli"] + b["budget_add_usd_milli"]}
    s["problems"] = {**s["problems"], pid: nxt}


def _a_halt(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    halted = {"seq": ev["seq"], "ts": ev["ts"], **({"reason": ev["body"]["reason"]} if "reason" in ev["body"] else {})}
    s["problems"] = {**s["problems"], pid: cast(Problem, {**p, "halted": halted})}


def _a_deliver(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    entry = {"id": f"d_{ev['seq']}", "seq": ev["seq"], "ts": ev["ts"], **ev["body"]}
    s["problems"] = {**s["problems"], pid: cast(Problem, {**p, "deliveries": [*p.get("deliveries", []), entry]})}
