"""Intent 族：add_intent、abandon_intent、approve（审批绑定所见），以及人的 Hint。"""

from __future__ import annotations

from typing import cast

from .. import levels as lv
from .. import refmodel as rm
from .. import work as wk
from ..parse import Obj
from ..state import Actor, Body, Done, Event, Hint, Intent, Problem, ScopeRule, State, Touch
from .common import RISK_RANK, RISKS, Config, Ok, Reject, _check, _node, _reason, _rule, _seen, _session_count

# ---------- 校验 ----------


def _v_add_intent(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    later = {"follows", "executor", "rollback", "delegate"} & body.keys()
    if later:
        return Reject("schema_error", f"{sorted(later)} 属于后续里程碑，M0 未启用")
    allowed = {"title", "summary", "premises", "risk", "budget", "done", "needs_scope", "expected_gain", "touches"}
    if not body.keys() <= allowed:
        return Reject("schema_error", f"多余字段 {sorted(body.keys() - allowed)}")
    prob = state["problems"][pid]
    risk = body.string("risk")
    if risk not in RISKS:
        return Reject("schema_error", "risk 非法")
    needs = [_rule(r) for r in body.children("needs_scope", None)]
    touches = _capability(prob, risk, needs, body)
    if isinstance(touches, Reject):
        return touches
    premises = body.strings("premises", [])
    lvls = lv.levels(state, pid)
    for p in premises:
        node = _node(state, p)
        if node is not None and node["problem_id"] != pid:
            return Reject("scope_mismatch", f"前提 {p} 属于别题")
        if p not in lvls:
            return Reject("unknown_ref", f"前提 {p} 不存在或不是带判据的 Intent")
        if lvls[p] == rm.X:
            return Reject("stale_premise", f"前提 {p} 已被证伪")
    done: Done | None = None
    if body.get("done") is not None:
        d = body.child("done")
        if "tests" in d:
            return Reject("schema_error", "done.tests 属于完整版")
        rest = Obj({k: v for k, v in d.raw.items() if k != "max_attempts"}, d.where)
        done = cast(Done, {**_check(rest), "max_attempts": d.integer("max_attempts")})
        if done["judge_id"] not in prob["judges"]:
            return Reject("unknown_ref", "done 的判官不在本题启用的判官里")
    bud = body.child("budget")
    budget: Body = {k: bud.number(k) for k in ("usd_milli", "wall_s", "tokens") if k in bud or k == "usd_milli"}
    lo, hi = cfg.intent_budget_usd_milli
    if not (lo <= budget["usd_milli"] <= hi) or any(v < 0 for v in budget.values()):
        return Reject("schema_error", f"预算须在 [{lo}, {hi}] 毫美元，各轨不能为负")
    if actor["kind"] == "adapter" and _session_count(state["intents"], actor.get("session")) >= cfg.intent_quota:
        return Reject("quota_exceeded", f"本任务已加 {cfg.intent_quota} 条 Intent")
    out: Body = {
        "title": body.string("title"),
        "summary": body.string("summary", ""),
        "premises": premises,
        "risk": risk,
        "budget": budget,
        **({"done": done} if done else {}),
        **({"needs_scope": needs} if needs else {}),
        **({"touches": touches} if touches is not None else {}),
    }
    if "expected_gain" in body:  # 估值，只供司南排序（I8）
        out["expected_gain"] = float(body.number("expected_gain"))
    return Ok(out)


def _capability(prob: Problem, risk: str, needs: list[ScopeRule], body: Obj) -> list[Touch] | None | Reject:
    """I5 在内核里的唯一校验点：能力 ≤ Intent 风险 ≤ 授权范围（规格 v1.5 第 52 条）。

    风险上限与 `touches` 的只许收窄是同一个检查，不拆到执行层：执行层只按这里存下的规则集编译，
    不再另查。`touches` 只能指向 Problem.scope 的下标（needs_scope 尚未授权，不能被占用）；
    每条规则的 risk 不高于 Intent 的 risk；write 只用于 r1 以上的规则；同一条规则只列一次。
    返回规范化（按下标排序）的列表；未声明时返回 None，由 work.holds 保守展开。"""
    ceiling = max((r["risk"] for r in wk.active(prob["scope"]) + needs), key=RISK_RANK.__getitem__)
    if RISK_RANK[risk] > RISK_RANK[ceiling]:
        return Reject("scope_mismatch", f"risk {risk} 高于授权范围的最高风险 {ceiling}")
    if body.get("touches") is None:
        return None
    out: dict[int, Touch] = {}
    for t in body.children("touches"):
        if not t.keys() <= {"rule", "mode"}:
            return Reject("schema_error", f"touches 多余字段 {sorted(t.keys() - {'rule', 'mode'})}")
        k, mode = t.integer("rule"), t.string("mode")
        if mode not in ("read", "write"):
            return Reject("schema_error", "touches.mode 只取 read、write")
        if not 0 <= k < len(prob["scope"]):
            return Reject("unknown_ref", f"touches 指向的规则 {k} 不在授权范围内")
        if k in out:
            return Reject("schema_error", f"touches 重复列出规则 {k}")
        rule = prob["scope"][k]
        if "revoked" in rule:
            return Reject("unknown_ref", f"touches 指向的规则 {k} 已撤销")
        if RISK_RANK[rule["risk"]] > RISK_RANK[risk]:
            return Reject("scope_mismatch", f"规则 {k} 的风险 {rule['risk']} 高于 Intent 的 risk {risk}")
        if mode == "write" and rule["risk"] == "r0":
            return Reject("scope_mismatch", f"规则 {k} 是 r0，只能读")
        out[k] = {"rule": k, "mode": mode}
    return [out[k] for k in sorted(out)]


def _v_abandon_intent(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    iid = body.string("intent")
    i = state["intents"].get(iid)
    if i is None or i["problem_id"] != pid:
        return Reject("unknown_ref", "Intent 不存在")
    status = wk.intent_status(state, pid, iid)
    if status in ("achieved", "abandoned", "done"):
        return Reject("schema_error", f"Intent 已是终态 {status}")
    if status == "leased":
        return Reject("conflict_leased", "Intent 有在途租约")
    return Ok({"intent": iid, "reason": body.text("reason", "")})


def _v_approve(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    iid, decision = body.string("intent"), body.string("decision")
    i = state["intents"].get(iid)
    if i is None or i["problem_id"] != pid:
        return Reject("unknown_ref", "Intent 不存在")
    if decision not in ("approve", "deny"):
        return Reject("schema_error", "decision 只取 approve、deny")
    seen = _seen(state, pid, "approval", iid, body)  # 先于状态检查：卡片变了，人要先看到新卡
    if isinstance(seen, Reject):
        return seen
    if wk.intent_status(state, pid, iid) != "needs_human":
        return Reject("schema_error", "只有 needs_human 的 Intent 待审批")
    reason = _reason(body)
    if decision == "deny" and not reason:
        return Reject("schema_error", "拒绝须写理由（§3.2 pd deny --reason）")
    return Ok({"intent": iid, "decision": decision, "seen": seen, **({"reason": reason} if reason else {})})


def _v_hint(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if "close" in body:
        h = state["hints"].get(body.string("close"))
        if h is None or h["problem_id"] != pid:
            return Reject("unknown_ref", "Hint 不存在")
        return Ok({"close": h["id"]})
    about = body.opt_string("about")
    if about is not None and about != "goal":
        node = _node(state, about)
        if node is None:
            return Reject("unknown_ref", "about 所指节点不存在")
        if node["problem_id"] != pid:
            return Reject("scope_mismatch", f"about 所指节点 {about} 属于别题")
    return Ok({"text": body.text("text"), **({"about": about} if about else {})})


# ---------- 应用 ----------


def _a_add_intent(s: State, ev: Event) -> None:
    iid = f"i_{ev['seq']}"
    rec = {**ev["body"], "id": iid, "problem_id": ev["problem_id"], "session": ev["actor"].get("session")}
    s["intents"] = {**s["intents"], iid: cast(Intent, rec)}


def _a_abandon_intent(s: State, ev: Event) -> None:
    s["abandoned"] = s["abandoned"] + [ev["body"]["intent"]]


def _a_approve(s: State, ev: Event) -> None:
    body, seq = ev["body"], ev["seq"]
    if body.get("reason"):
        s["decision_reasons"] = {
            **s.get("decision_reasons", {}),
            body["intent"]: {
                "decision": body["decision"],
                "reason": body["reason"],
                "by": ev["actor"]["id"],
                "seq": seq,
            },
        }
    if body["decision"] == "approve":
        s["approvals"] = {**s["approvals"], body["intent"]: s["approvals"].get(body["intent"], []) + [seq]}
    else:
        s["abandoned"] = s["abandoned"] + [body["intent"]]


def _a_hint(s: State, ev: Event) -> None:
    body = ev["body"]
    if "close" in body:
        h = s["hints"][body["close"]]
        s["hints"] = {**s["hints"], h["id"]: {**h, "closed": True}}
        return
    hid = f"h_{ev['seq']}"
    hint = {
        **body,
        "id": hid,
        "problem_id": ev["problem_id"],
        "seq": ev["seq"],
        "ts": ev["ts"],
        "author": ev["actor"]["id"],
        "closed": False,
    }
    s["hints"] = {**s["hints"], hid: cast(Hint, hint)}
