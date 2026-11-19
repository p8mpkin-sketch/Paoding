"""运行时扩权族：request_scope、grant_scope、revoke_scope（设计 docs/design/runtime-grants/ §4）。

开题时的授权只是起点；执行中要访问新的外部资源，先申请，再由人或确定性的练习道白名单批准。
批准把规则追加进 Problem.scope（只追加，下标不变），画像随之重算并写进事件体；执行层只编译已批未撤的规则。

- 申请不是授权：谁都可以申请（任务会话、人；图服务替带 needs_scope 的 Intent 申请），批准只有两种来源。
- 风险不信自报：每条规则的风险在写入时查风险表（设置层），未命中按 r2；人在卡上只可上调。
- 图服务的身份不是信任来源：actor 为 graph 的批准，validate 当场重算它所依据的判定，不成立即 forbidden_op。
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Any, cast

from ..parse import BadBody, Obj
from ..practice import rule_violations
from ..resources import RESOURCE_REQUESTABLE
from ..state import Actor, Body, Event, Problem, Profile, ScopeRequest, ScopeRule, State
from ..work import active, requests
from .common import RISK_RANK, RISKS, Config, Ok, Reject, RiskRow, _reason, _seen
from .problem import _derive_profile

REQUEST_ROLES = ("bootstrap", "reason", "explore")


def table_hit(table: tuple[RiskRow, ...], resource: str, pattern: str, actions: list[str]) -> int | None:
    """顺序匹配风险表（与起草服务 qicao 的 Settings.risk_of 同一语义）：命中的行号（从 0 起），未命中 None。"""
    for i, r in enumerate(table):
        if r.get("resource") != resource or not fnmatchcase(pattern, str(r.get("pattern", ""))):
            continue
        allowed = set(r.get("actions") or ["*"])
        if "*" in allowed or set(actions) <= allowed:
            return i
    return None


def table_risk(table: tuple[RiskRow, ...], resource: str, pattern: str, actions: list[str]) -> str | None:
    """命中行的风险；未命中返回 None。"""
    i = table_hit(table, resource, pattern, actions)
    return None if i is None else str(table[i]["risk"])


def risk_of(table: tuple[RiskRow, ...], resource: str, pattern: str, actions: list[str]) -> str:
    """未命中按 r2（规格 3.1.2：风险由授权的人逐条标注，缺省 r2）。"""
    return table_risk(table, resource, pattern, actions) or "r2"


def _key(r: ScopeRule | Body) -> tuple[str, str, tuple[str, ...]]:
    return (r["resource"], r["pattern"], tuple(sorted(r["actions"])))


def auto_blockers(state: State, pid: str, rules: list[ScopeRule], cfg: Config) -> list[str]:
    """练习道白名单的确定性判定（§4.4）：返回不能自动批准的每条原因，空即可以。纯函数。"""
    p = state["problems"][pid]
    draft = p["origin"].get("draft")
    if not cfg.grants_auto_practice:
        return ["设置里关了练习道自动批准"]
    if draft is None or draft["lane"] != "practice" or "policy" not in draft:
        return ["不是练习道开的任务"]
    pol = cfg.practice
    if pol is None or pol.digest != draft["policy"]["digest"]:
        return ["信封已不是开题时签的那一份"]
    out = rule_violations(pol, list(rules))
    if p["budget"]["usd_milli"] > pol.usd_milli_max or p["budget"]["wall_s"] > pol.wall_s_max:
        out.append("任务预算超过练习上限")
    return out


def _requested_rules(body: Obj, cfg: Config) -> list[ScopeRule]:
    out: list[ScopeRule] = []
    for r in body.children("rules"):
        if r.keys() != {"resource", "pattern", "actions"}:
            raise BadBody("申请的规则只写 resource、pattern、actions；风险由图服务查风险表")
        resource, pattern, actions = r.string("resource"), r.string("pattern"), sorted(set(r.strings("actions")))
        shape = RESOURCE_REQUESTABLE.get(resource)
        if shape is None:
            raise BadBody(f"资源 {resource} 不能经申请扩权")
        if not re.match(shape[0], pattern):
            raise BadBody(f"{resource} 的 pattern 形状不对：{pattern!r}")
        if not actions or not set(actions) <= shape[1]:
            raise BadBody(f"{resource} 的 actions 只取 {sorted(shape[1])}")
        out.append(
            {
                "resource": resource,
                "pattern": pattern,
                "actions": actions,
                "risk": risk_of(cfg.risk_table, resource, pattern, actions),
            }
        )
    if not out:
        raise BadBody("rules 必填且非空")
    return out


def _v_request_scope(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if not body.keys() <= {"rules", "why", "intent"} or "rules" not in body:
        return Reject("schema_error", "字段为 rules、why，可选 intent")
    by_graph = actor["kind"] == "graph"
    if not by_graph and not cfg.grants_runtime:
        return Reject("not_enabled", "运行时扩权在设置里关着（grants.runtime = off）")
    rules = _requested_rules(body, cfg)
    if len({_key(r) for r in rules}) != len(rules):
        return Reject("schema_error", "同一条规则只列一次")
    why = body.text("why").strip() if "why" in body else ""
    if not why and not by_graph:
        return Reject("schema_error", "申请须写理由")
    iid = body.opt_string("intent")
    if iid is not None:
        i = state["intents"].get(iid)
        if i is None:
            return Reject("unknown_ref", f"Intent {iid} 不存在")
        if i["problem_id"] != pid:
            return Reject("scope_mismatch", f"Intent {iid} 属于别题")
    if by_graph:
        # 图服务只替带 needs_scope 的 Intent 申请，规则照抄，不自创
        if iid is None or any(r.get("intent") == iid for r in requests(state).values()):
            return Reject("forbidden_op", "图服务只为尚无申请的 needs_scope Intent 追加申请")
        need = state["intents"][iid].get("needs_scope") or []
        if sorted(_key(r) for r in need) != sorted(_key(r) for r in rules):
            return Reject("forbidden_op", "图服务追加的申请必须照抄 Intent 的 needs_scope")
    p = state["problems"][pid]
    held = {_key(r) for r in active(p["scope"])}
    mine = [x for x in requests(state).values() if x["problem_id"] == pid]
    pending = {_key(r) for x in mine if x["status"] == "pending" for r in x["rules"]}
    denied = {_key(r) for x in mine if x["status"] == "denied" for r in x["rules"]}
    for r in rules:
        k = _key(r)
        if k in denied and not by_graph:
            return Reject("forbidden_op", f"{r['pattern']} 在本题被人拒过，不能再申请")
        if k in held:
            return Reject("schema_error", f"{r['pattern']} 已在授权范围内")
        if k in pending and not by_graph:
            return Reject("schema_error", f"{r['pattern']} 已在申请中")
    session = actor.get("session")
    if session and sum(1 for x in mine if x["session"] == session) >= cfg.scope_request_quota:
        return Reject("quota_exceeded", f"本会话已申请 {cfg.scope_request_quota} 次")
    blockers = auto_blockers(state, pid, rules, cfg)
    rows = [table_hit(cfg.risk_table, r["resource"], r["pattern"], r["actions"]) for r in rules]
    out: Body = {
        "rules": rules,
        # 风险从哪来（扩权卡照写，runtime-grants §7.1）：风险表第几行（从 0 起），未命中为 null，按缺省 r2
        "risk_from": rows,
        "why": why,
        **({"intent": iid} if iid is not None else {}),
        "auto": not blockers,
        **({"blockers": blockers} if blockers else {}),
    }
    if not blockers and cfg.practice is not None:
        out["policy"] = cfg.practice.stamp()
    if cfg.settings:
        out["settings"] = {"version": cfg.settings[0], "digest": cfg.settings[1]}
    return Ok(out)


def _reprofile(p: Problem, scope: list[ScopeRule], cfg: Config) -> Profile:
    goal_judge = p["judge_snapshot"][p["goal"]["check"]["judge_id"]]
    return _derive_profile(active(scope), goal_judge, cfg)


def _graph_decision(state: State, req: ScopeRequest, via: str, cfg: Config) -> tuple[str, str] | Reject:
    """图服务的批或拒必须由判定推出：练习道白名单（auto），或所随 Intent 的人工审批（approval）。"""
    if via == "auto":
        bad = auto_blockers(state, req["problem_id"], req["rules"], cfg)
        if not req["auto"] or bad:
            return Reject("forbidden_op", "练习道白名单不许：" + "；".join(bad or ["申请时未判为自动批准"]))
        return "approve", ""
    if via == "approval":
        iid = req.get("intent")
        if iid is None:
            return Reject("forbidden_op", "这条申请不随 Intent，不能随审批批准")
        if state["approvals"].get(iid):
            return "approve", ""
        if iid in state["abandoned"]:
            return "deny", f"Intent {iid} 未获批准"
        return Reject("forbidden_op", f"Intent {iid} 还没有审批结果")
    return Reject("schema_error", "via 只取 auto、approval")


def _v_grant_scope(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    rid = body.string("request")
    req = requests(state).get(rid)
    if req is None:
        return Reject("unknown_ref", f"扩权申请 {rid} 不存在")
    if req["problem_id"] != pid:
        return Reject("scope_mismatch", f"扩权申请 {rid} 属于别题")
    out: Body = {"request": rid}
    rules: list[ScopeRule] = [cast(ScopeRule, dict(r)) for r in req["rules"]]
    if actor["kind"] == "graph":
        if not body.keys() <= {"request", "via"}:
            return Reject("schema_error", "图服务的批准只带 request、via")
        via = body.string("via")
        if req["status"] != "pending":
            return Reject("schema_error", f"扩权申请 {rid} 已经{req['status']}")
        d = _graph_decision(state, req, via, cfg)
        if isinstance(d, Reject):
            return d
        decision, reason = d
        out.update(via=via, decision=decision, **({"reason": reason} if reason else {}))
        if via == "auto" and cfg.practice is not None:
            out["policy"] = cfg.practice.stamp()
        if via == "approval" and decision == "approve":
            # 人在审批卡上看到并批准的是 Intent 申报的风险，这就是"授权的人逐条标注"；
            # 风险表命中时取两者的较高者（表是人事先写下的下限），未命中时以人批的为准
            declared = {_key(r): r["risk"] for r in state["intents"][req["intent"]].get("needs_scope") or []}
            for r in rules:
                hit = table_risk(cfg.risk_table, r["resource"], r["pattern"], r["actions"])
                mine = declared.get(_key(r), "r2")
                r["risk"] = mine if hit is None else max(hit, mine, key=RISK_RANK.__getitem__)
    else:
        if not body.keys() <= {"request", "decision", "risk", "reason", "seen"}:
            return Reject("schema_error", "字段为 request、decision、seen，可选 risk、reason")
        seen = _seen(state, pid, "scope", rid, body)  # 先于状态检查：卡变了，人先看到新卡
        if isinstance(seen, Reject):
            return seen
        if req["status"] != "pending":
            return Reject("schema_error", f"扩权申请 {rid} 已经{req['status']}")
        decision = body.string("decision")
        if decision not in ("approve", "deny"):
            return Reject("schema_error", "decision 只取 approve、deny")
        reason = _reason(body)
        if decision == "deny" and not reason:
            return Reject("schema_error", "拒绝须写理由")
        if "risk" in body:
            raised = body.strings("risk")
            if decision != "approve" or len(raised) != len(rules) or any(x not in RISKS for x in raised):
                return Reject("schema_error", "risk 是与 rules 一一对应的风险列表，只在批准时给")
            for r, x in zip(rules, raised, strict=True):
                if RISK_RANK[x] < RISK_RANK[r["risk"]]:
                    return Reject("schema_error", f"{r['pattern']} 的风险只可上调（风险表给 {r['risk']}）")
                r["risk"] = x
        out.update(decision=decision, seen=seen, **({"reason": reason} if reason else {}))
    if out["decision"] == "approve":
        p = state["problems"][pid]
        out["rules"] = rules
        out["derived"] = _reprofile(p, p["scope"] + rules, cfg)
    return Ok(out)


def _v_revoke_scope(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if body.keys() != {"rule", "reason"}:
        return Reject("schema_error", "字段为 rule、reason")
    k = body.integer("rule")
    p = state["problems"][pid]
    if not 0 <= k < len(p["scope"]):
        return Reject("unknown_ref", f"规则 {k} 不在授权范围内")
    if "revoked" in p["scope"][k]:
        return Reject("schema_error", f"规则 {k} 已撤销")
    reason = _reason(body)
    if not reason:
        return Reject("schema_error", "撤销须写理由")
    rest = [r for i, r in enumerate(p["scope"]) if i != k]
    if not active(rest):
        return Reject("schema_error", "授权范围至少留一条规则")
    return Ok({"rule": k, "reason": reason, "derived": _reprofile(p, rest, cfg)})


# ---------- 应用 ----------


def _set_profile(p: Problem, derived: Profile) -> Problem:
    """新的推出值；人工覆盖过的轴（裁决 A7）照旧盖在上面。"""
    overrides = p.get("profile_overrides") or []
    if not overrides:
        return {**p, "profile": derived}
    last = {o["axis"]: o["value"] for o in overrides}
    return {**p, "derived_profile": derived, "profile": cast(Profile, {**derived, **last})}


def _a_request_scope(s: State, ev: Event) -> None:
    b, rid = ev["body"], f"r_{ev['seq']}"
    rec = {
        "id": rid,
        "problem_id": ev["problem_id"],
        "rules": b["rules"],
        "why": b["why"],
        "auto": b["auto"],
        "status": "pending",
        "by": ev["actor"]["id"],
        "session": ev["actor"].get("session"),
        **({"role": ev["actor"]["role"]} if ev["actor"].get("role") else {}),
        "seq": ev["seq"],
        **({"risk_from": b["risk_from"]} if "risk_from" in b else {}),
        **({"intent": b["intent"]} if "intent" in b else {}),
        **({"blockers": b["blockers"]} if "blockers" in b else {}),
    }
    s["scope_requests"] = {**requests(s), rid: cast(ScopeRequest, rec)}


def _a_grant_scope(s: State, ev: Event) -> None:
    b, pid = ev["body"], ev["problem_id"]
    req = requests(s)[b["request"]]
    done: ScopeRequest = {
        **req,
        "status": "granted" if b["decision"] == "approve" else "denied",
        "decided_seq": ev["seq"],
        "decided_by": ev["actor"]["id"],
    }
    if b.get("via"):
        done["via"] = b["via"]
    if b.get("policy"):
        done["policy"] = b["policy"]
    if b.get("reason"):
        done["reason"] = b["reason"]
    s["scope_requests"] = {**requests(s), req["id"]: done}
    if b["decision"] == "approve":
        p = s["problems"][pid]
        granted = {"seq": ev["seq"], "by": ev["actor"]["id"], "request": req["id"]}
        added = [cast(ScopeRule, {**r, "granted": granted}) for r in b["rules"]]
        s["problems"] = {**s["problems"], pid: _set_profile({**p, "scope": p["scope"] + added}, b["derived"])}


def _a_revoke_scope(s: State, ev: Event) -> None:
    b, pid = ev["body"], ev["problem_id"]
    p = s["problems"][pid]
    scope = [cast(ScopeRule, {**r, "revoked": ev["seq"]}) if i == b["rule"] else r for i, r in enumerate(p["scope"])]
    s["problems"] = {**s["problems"], pid: _set_profile({**p, "scope": scope}, b["derived"])}


def followups(state: State, pid: str) -> list[tuple[str, dict[str, Any]]]:
    """图服务自己追加的扩权事件（与触发它的批次同一事务）：
    带 needs_scope 而尚无申请的 Intent → 申请；判为自动批准的申请 → 批准；随 Intent 的申请 → 跟着审批结果。"""
    out: list[tuple[str, dict[str, Any]]] = []
    asked = {x.get("intent") for x in requests(state).values()}
    for iid, i in state["intents"].items():
        if i["problem_id"] == pid and i.get("needs_scope") and iid not in asked and iid not in state["abandoned"]:
            rules = [{k: r[k] for k in ("resource", "pattern", "actions")} for r in i["needs_scope"]]
            out.append(("request_scope", {"rules": rules, "intent": iid}))
    for x in requests(state).values():
        if x["problem_id"] != pid or x["status"] != "pending":
            continue
        if x["auto"]:
            out.append(("grant_scope", {"request": x["id"], "via": "auto"}))
        elif "intent" in x and (state["approvals"].get(x["intent"]) or x["intent"] in state["abandoned"]):
            out.append(("grant_scope", {"request": x["id"], "via": "approval"}))
    return out
