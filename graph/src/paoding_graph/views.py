"""只读投影（HMI §11.2；规格 §3.1.2 的 GET 端点）：全部是状态的纯函数，不读时钟、不做 IO、不调用模型。

- 每个投影只读 reducer 状态（实时即链头状态，回放即 `state_at(as_of)` 的状态），所以同一 as_of 两次调用逐字节相同。
- 等级、Intent 状态、消费门、失效集合、审批卡与 `card_hash` 一律经 levels.py / refmodel.py 的搬运函数算出，这里不重写语义。
- 四语域（HMI §3.4）：凡是文字内容都包成 `{"src", "register", "value"}`，语域由出处类别查 REGISTER 表得到，
  不由内容决定；渲染端（pd 与网页）只认这张表。结构字段（id、等级、状态、账目）恒属“证据”。
- 排序只用确定性的键（创建 seq、id）。时间只取事件 ts（state["now"]、opened_ts）。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Any, cast

from . import cards
from . import levels as lv
from . import refmodel as rm
from . import work as wk
from .parse import BadBody, Obj
from .reducer import Config, _derive_profile, _rule
from .state import Check, Fact, Hint, Intent, Lease, Problem, State

# 出处类别 → 语域（HMI §3.4 的表；pd 的行首标记与网页的样式同源）
REGISTER = {
    # 证据：exec、judge、input 类 Artifact 与判官裁决；以及由它们确定性算出的等级、状态、账目
    "artifact:exec": "证据", "artifact:judge": "证据", "artifact:input": "证据", "verdict": "证据",
    "level": "证据", "predicate": "证据", "status": "证据", "budget": "证据", "lease": "证据",
    "profile": "证据", "terminal": "证据", "structure": "证据",
    # 叙述：authored 类与模型写的一切文字
    "artifact:authored": "叙述", "title": "叙述", "summary": "叙述", "suggestion": "叙述", "candidate": "叙述",
    # 人：Hint、裁决与拒绝的理由、豁免、覆盖理由、开题时人写下的目标陈述
    "hint": "人", "human_reason": "人", "statement": "人",
    # 估：期望增益、预测、行情、存活计数
    "estimate": "估",
}
REGISTERS = ("证据", "叙述", "人", "估")
LEVEL_WORDS = {"E3": "判定通过", "E3d": "相符", "E2": "模型共识", "E1": "单源复核", "E0": "猜想", "X": "已证伪"}
View = dict[str, Any]            # 一份投影：JSON 对象
VIEW_LAYERS = ("title", "summary", "full")
CARD_KINDS = cards.CARD_KINDS


class NotFound(Exception):
    """unknown_ref：对象不存在，或在 as_of 那一刻还不存在。"""


class NotEnabled(Exception):
    """端点或参数属于后续里程碑。"""


def tag(src: str, value: Any) -> View:
    return {"src": src, "register": REGISTER[src], "value": value}


def _seq(node_id: str) -> int:
    return int(node_id.split("_", 1)[1])


def _problem(state: State, pid: str) -> Problem:
    p = state["problems"].get(pid)
    if p is None:
        raise NotFound(f"题目 {pid} 不存在（或在该序号时尚未开题）")
    return p


def _badge(p: Problem, judge_id: str) -> View:
    snap: Mapping[str, Any] = p["judge_snapshot"].get(judge_id) or {}
    return {"judge_id": judge_id, "version": snap.get("version"), "grade": snap.get("grade"),
            "kind": snap.get("kind"), "label": f"{judge_id}@{snap.get('version', '?')}"}


def _terminal(state: State, pid: str) -> str | None:
    p = state["problems"][pid]
    return p.get("terminal", "unsolved") if p.get("closed") else None    # 未关题没有终态（3.1.5 的 15）


# ---------- 判据卡（HMI §3.3）：Goal、带判据的 Intent、观察类论断同一形状 ----------

def _predicate(state: State, pid: str, target: str, check: Check, level: str | None,
               max_attempts: int | None = None) -> View:
    p = state["problems"][pid]
    verdicts = [v for v in state["verdicts"] if v["problem_id"] == pid and v["target"] == target]
    spec = state["artifacts"].get(check.get("spec_ref") or "")
    return {"target": target, **_badge(p, check["judge_id"]),
            "spec_ref": check.get("spec_ref"), "spec_hash": spec["hash"] if spec else None,
            "expect": check.get("expect", {}), "sealed": check.get("sealed", []),
            "max_attempts": max_attempts,
            "attempts_used": len({v.get("candidate") or v["request"] for v in verdicts}) if max_attempts else None,
            "level": level, "level_word": LEVEL_WORDS.get(level) if level else None,
            "fail_means": "refuted" if target.startswith("f_") else "not_yet",   # 论断：证伪；目标：未达成，计一次
            "verdicts": [{"seq": v["seq"], "result": v["result"], "judge": v["judge"], "version": v["version"],
                          "grade": v["grade"], "candidate": v.get("candidate"), "request": v["request"],
                          "evidence": list(v["evidence"])} for v in verdicts]}


# ---------- 节点 ----------

def _grounds(state: State, ids: list[str]) -> list[View]:
    out: list[View] = []
    for g in ids:
        a = state["artifacts"][g]
        out.append({"id": g, "class": a["class"], "src": f"artifact:{a['class']}",
                    "register": REGISTER[f"artifact:{a['class']}"], "hash": a["hash"], "size": a["size"]})
    return out


def _fact(state: State, pid: str, f: Fact, ctx: View, layer: str) -> View:
    level = ctx["levels"].get(f["id"])
    out: dict[str, Any] = {"id": f["id"], "type": "fact", "seq": _seq(f["id"]), "claim_type": f["claim_type"],
                           "level": level, "level_word": LEVEL_WORDS.get(level),
                           "unstable": f["id"] in ctx["res"].unstable, "disputed": f["id"] in ctx["res"].disputed,
                           "stale": f["id"] in ctx["res"].stale, "title": tag("title", f["title"])}
    if layer == "title":
        return out
    out.update({"summary": tag("summary", f.get("summary", "")), "premises": list(f["premises"]),
                "yielded_by": f.get("yielded_by"), "session": f.get("session"),
                "predicate": _predicate(state, pid, f["id"], f["check"], level) if f.get("check") else None,
                "grounds": [g["id"] for g in _grounds(state, f.get("grounds", []))]})
    if layer in ("evidence", "full"):
        out["grounds"] = _grounds(state, f.get("grounds", []))
        out["no_evidence_root"] = not out["grounds"]                 # H6：“无证据根”标记
        out["body_ref"] = f.get("body_ref")
    return out


def _intent(state: State, pid: str, i: Intent, ctx: View, layer: str) -> View:
    st, res = ctx["ref"]
    status = wk.intent_status(state, pid, i["id"], ctx)
    level = ctx["levels"].get(i["id"])
    out: dict[str, Any] = {"id": i["id"], "type": "intent", "seq": _seq(i["id"]), "status": status,
                           "risk": i["risk"], "level": level, "level_word": LEVEL_WORDS.get(level) if level else None,
                           "title": tag("title", i["title"])}
    if layer == "title":
        return out
    leases = [l for l in wk.leases_of(state, pid) if l.get("target") == i["id"] and l["kind"] == "explore"]
    out.update({"summary": tag("summary", i.get("summary", "")), "premises": list(i["premises"]),
                "budget": dict(i["budget"]), "session": i.get("session"),
                "needs_scope": list(i.get("needs_scope") or []),
                "gate": rm.gate(st, res, st.intents[i["id"]]),
                "approvals": list(state.get("approvals", {}).get(i["id"], [])),
                "attempts": len(leases),
                "predicate": (_predicate(state, pid, i["id"], i["done"], level, i["done"].get("max_attempts"))
                              if i.get("done") else None)})
    dr = state.get("decision_reasons", {}).get(i["id"])
    out["decision"] = ({"decision": dr["decision"], "by": dr["by"], "seq": dr["seq"],
                        "reason": tag("human_reason", dr["reason"])} if dr else None)
    # 估值永不与等级同框：单独一个字段，带“估”的语域（I8）
    out["expected_gain"] = tag("estimate", i["expected_gain"]) if "expected_gain" in i else None
    if layer in ("evidence", "full"):
        out["leases"] = [l["id"] for l in sorted(leases, key=lambda l: l["issued_seq"])]
    return out


def _hint(h: Hint) -> View:
    return {"id": h["id"], "type": "hint", "seq": h["seq"], "author": h["author"], "closed": bool(h.get("closed")),
            "about": h.get("about"), "text": tag("hint", h["text"])}


def _lease(l: Lease) -> View:
    keep = ("id", "kind", "target", "holder", "reserve", "issued_seq", "expires_at", "active", "outcome",
            "ended_seq", "transcript_ref", "reflect")
    rec = cast(View, l)
    return {k: rec[k] for k in keep if k in rec}


def _ctx(state: State, pid: str) -> View:
    st, res = lv.compute(state, pid)
    return {"ref": (st, res), "res": res, "levels": res.levels}


def _facts(state: State, pid: str) -> list[Fact]:
    return sorted((n for n in state["facts"].values() if n["problem_id"] == pid), key=lambda n: _seq(n["id"]))


def _intents(state: State, pid: str) -> list[Intent]:
    return sorted((n for n in state["intents"].values() if n["problem_id"] == pid), key=lambda n: _seq(n["id"]))


# ---------- 端点投影 ----------

def problems(state: State) -> View:
    """GET /v1/problems：题目列表（终态三值、画像、花费、每解成本）。"""
    items, spent_all, solved = [], 0, 0
    for pid in sorted(state["problems"], key=lambda k: state["problems"][k]["opened_seq"]):
        p = state["problems"][pid]
        b = wk.budget_view(state, pid)
        term = _terminal(state, pid)
        spent_all += b["spent"]["usd_milli"]
        solved += term == "solved"
        items.append({"id": pid, "title": tag("title", p["title"]), "closed": bool(p.get("closed")),
                      "terminal": term, "terminal_badge": _badge(p, p["goal"]["check"]["judge_id"]),
                      "profile": dict(p["profile"]), "opened_seq": p["opened_seq"], "opened_ts": p["opened_ts"],
                      "closed_seq": p.get("closed_seq"),
                      "spent_usd_milli": b["spent"]["usd_milli"], "cap_usd_milli": b["cap"].get("usd_milli")})
    return {"items": items, "totals": {"problems": len(items), "solved": solved, "spent_usd_milli": spent_all,
                                       "cost_per_solve_usd_milli": spent_all // solved if solved else None}}


def status(state: State, pid: str) -> View:
    """GET /status：等级、争议、Intent 状态的当前值（或某序号的值）。pd status 的结构化同源。"""
    p = _problem(state, pid)
    ctx = _ctx(state, pid)
    goal_level = ctx["levels"].get("goal")
    return {
        "problem": {
            "id": pid, "title": tag("title", p["title"]), "closed": bool(p.get("closed")),
            "terminal": _terminal(state, pid), "terminal_badge": _badge(p, p["goal"]["check"]["judge_id"]),
            "opened_seq": p["opened_seq"], "opened_ts": p["opened_ts"], "closed_seq": p.get("closed_seq"),
            "now_ts": state["now"],
            "profile": dict(p["profile"]), "derived_profile": dict(p.get("derived_profile", p["profile"])),
            "profile_overrides": [{"axis": o["axis"], "value": o["value"], "derived": o.get("derived"), "by": o["by"],
                                   "seq": o["seq"], "reason": tag("human_reason", o.get("reason", ""))}
                                  for o in p.get("profile_overrides", [])],
            "scope": [dict(r) for r in p["scope"]], "env": dict(p["env"]), "judges": sorted(p["judges"]),
            "origin": {"statement_ref": p["origin"]["statement_ref"], "materials": list(p["origin"]["materials"])},
        },
        "goal": {"statement": tag("statement", p["goal"]["statement"]), "accept": p["goal"]["accept"],
                 "predicate": _predicate(state, pid, "goal", p["goal"]["check"], goal_level,
                                         p["goal"]["max_attempts"])},
        "facts": [_fact(state, pid, f, ctx, "summary") for f in _facts(state, pid)],
        "intents": [_intent(state, pid, i, ctx, "summary") for i in _intents(state, pid)],
        "hints": [_hint(h) for h in sorted((h for h in state["hints"].values() if h["problem_id"] == pid),
                                           key=lambda h: h["seq"])],
        "leases": [_lease(l) for l in sorted(wk.leases_of(state, pid), key=lambda l: l["issued_seq"])],
        "requests": [{"id": r["id"], "seq": _seq(r["id"]), "target": r["target"], "judge_id": r["judge_id"],
                      "candidate": r.get("candidate"), "verdict_seq": r.get("verdict_seq")}
                     for r in sorted((r for r in state["requests"].values() if r["problem_id"] == pid),
                                     key=lambda r: _seq(r["id"]))],
        "review": wk.in_review(state, pid),
        "closeout": wk.closeout_items(state, pid),
    }


def view(state: State, pid: str, layer: str = "title", after_seq: int = 0, limit: int | None = None,
         full_dump: bool = False) -> View:
    """GET /view?layer=title|summary&after_seq=&limit=：按创建顺序的节点清单，游标为 seq。

    `frontier` 是摘要层的“前沿”（3.1.4）：活跃 Hint、待人处理项、未结束的 Intent 及其前提、未到终态的论断。
    layer=full 是三层视图的开关（SPEC：view=full_dump），只在服务端打开该开关时可用。"""
    _problem(state, pid)
    if layer not in VIEW_LAYERS:
        raise BadBody(f"layer 只取 {VIEW_LAYERS[:2]}")
    if layer == "full" and not full_dump:
        raise NotEnabled("layer=full 需要服务端打开 view_full_dump 开关")
    ctx = _ctx(state, pid)
    # 每个节点配一个惰性的渲染函数：先按创建序翻页，只渲染这一页
    nodes: list[tuple[str, Callable[[], View]]] = []
    for f in _facts(state, pid):
        nodes.append((f["id"], partial(_fact, state, pid, f, ctx, layer)))
    for i in _intents(state, pid):
        nodes.append((i["id"], partial(_intent, state, pid, i, ctx, layer)))
    nodes.sort(key=lambda kv: _seq(kv[0]))
    page = [kv for kv in nodes if _seq(kv[0]) > after_seq]
    more = limit is not None and len(page) > limit
    if limit is not None:
        page = page[:limit]
    items = [render() for _, render in page]
    statuses = {i["id"]: wk.intent_status(state, pid, i["id"], ctx) for i in _intents(state, pid)}
    live = [iid for iid, s in statuses.items() if s not in ("achieved", "abandoned", "done")]
    frontier = {
        "hints": sorted(h["id"] for h in state["hints"].values() if h["problem_id"] == pid and not h.get("closed")),
        "human": [w for w in wk.work(state, pid) if w["kind"] == "human"],
        "disputed": sorted(ctx["res"].disputed | ctx["res"].unstable, key=str),
        "intents": live,
        "premises": sorted({p for iid in live for p in state["intents"][iid]["premises"]}, key=_seq),
        "facts": [f["id"] for f in _facts(state, pid) if ctx["levels"].get(f["id"]) not in ("E3", "X")],
    }
    return {"layer": layer, "items": items, "next_after_seq": items[-1]["seq"] if more else None,
            "total": len(nodes), "frontier": frontier}


def node(state: State, nid: str, layer: str = "summary") -> View:
    """GET /v1/nodes/{id}?layer=…：下钻。论断 → 支持记录（判据卡里的裁决）→ 证据 Artifact，三步之内到证据根。"""
    if layer not in ("title", "summary", "evidence"):
        raise BadBody("layer 只取 title|summary|evidence")
    f = state["facts"].get(nid)
    if f is not None:
        return {"problem_id": f["problem_id"], **_fact(state, f["problem_id"], f, _ctx(state, f["problem_id"]), layer)}
    i = state["intents"].get(nid)
    if i is not None:
        return {"problem_id": i["problem_id"],
                **_intent(state, i["problem_id"], i, _ctx(state, i["problem_id"]), layer)}
    h = state["hints"].get(nid)
    if h is not None:
        return {"problem_id": h["problem_id"], **_hint(h)}
    raise NotFound(f"没有节点 {nid}")


def artifact(state: State, aid: str) -> View:
    """GET /v1/artifacts/{id}：登记记录与出处字段。语域由类别决定（authored 是叙述，其余是证据）。"""
    a = state["artifacts"].get(aid)
    if a is None:
        raise NotFound(f"没有 Artifact {aid}")
    src = f"artifact:{a['class']}"
    return {**{k: a[k] for k in ("id", "problem_id", "hash", "size", "media_type", "class", "parents", "producer")},
            "seq": _seq(aid), "src": src, "register": REGISTER[src], "exec": a.get("exec")}


def invalidations(state: State, pid: str, node_id: str) -> View:
    """GET /invalidations?node=：把该节点的证伪去掉重算，等级因此变高的其它节点（参考模型的搬运函数）。"""
    _problem(state, pid)
    st, _ = lv.compute(state, pid)
    if node_id not in st.facts and node_id not in st.intents:
        raise NotFound(f"本题没有节点 {node_id}")
    lost = sorted(rm.invalidations(st, node_id), key=_seq)
    return {"node": node_id, "invalidated": lost}


def budget(state: State, pid: str) -> View:
    """GET /budget：账本投影（量具）。墙钟取事件时钟，不读本机时间。"""
    p = _problem(state, pid)
    b = cast(View, wk.budget_view(state, pid))
    cap = b["cap"].get("usd_milli") or 0
    b["percent"] = {"spent": b["spent"]["usd_milli"] * 100 // cap if cap else 0,
                    "committed": (b["spent"]["usd_milli"] + b["reserved"]["usd_milli"]) * 100 // cap if cap else 0}
    b["mark_lines"] = list(wk.MARKS)
    b["mark_seqs"] = list(p.get("mark_seqs", []))
    b["verify_share"] = p["budget"]["verify_share"]
    b["bootstrap_share"] = p["budget"]["bootstrap_share"]
    end = state["now"]
    b["wall"] = {"cap_s": p["budget"]["wall_s"], "elapsed_s": max(0, end - p["opened_ts"]) // 1000}
    b["review"] = wk.in_review(state, pid)
    return b


def work(state: State, pid: str) -> View:
    _problem(state, pid)
    return {"items": wk.work(state, pid)}


# ---------- 卡片投影（H2）：pd 的文本卡与网页卡是同一个对象，card_hash 相同 ----------

def card(state: State, pid: str, kind: str, target: str) -> View:
    p = _problem(state, pid)
    if kind not in CARD_KINDS:
        raise NotFound(f"没有卡片种类 {kind}")
    ctx = _ctx(state, pid)
    if kind == "approval":
        i = state["intents"].get(target)
        if i is None or i["problem_id"] != pid:
            raise NotFound(f"本题没有 Intent {target}")
        obj = cards.card_object(state, pid, kind, target, ctx["ref"])
        display: View = {
            "status": wk.intent_status(state, pid, target, ctx),
            "title": tag("title", i["title"]), "summary": tag("summary", i.get("summary", "")),
            "reserve": dict(i["budget"]), "lease_note": "一次批准只管一次租约",
            "rollback": tag("summary", i["rollback"]["text"]) if i.get("rollback") else None,
            "predicate": (_predicate(state, pid, target, i["done"], ctx["levels"].get(target),
                                     i["done"]["max_attempts"]) if "done" in i else None),
            "premises": [{"id": x, "type": "fact" if x in state["facts"] else "intent",
                          "level": ctx["levels"].get(x), "level_word": LEVEL_WORDS.get(ctx["levels"].get(x)),
                          "title": tag("title", (state["facts"].get(x) or state["intents"][x])["title"])}
                         for x in i["premises"]],
            "disputes": [],                                          # M0 无反证操作
            "needs_scope": list(i.get("needs_scope") or []), "scope": [dict(r) for r in p["scope"]],
            "expected_gain": tag("estimate", i["expected_gain"]) if "expected_gain" in i else None,  # 只在折叠区
            # H1（r2 缺回退禁批）随 M4 的 rollback 字段落地；M0 内核不接受 rollback，卡面只标“未声明回退”
            "rollback_declared": bool(i.get("rollback")), "approve_enabled": True,
            "decision": state.get("decision_reasons", {}).get(target) and {
                **{k: state["decision_reasons"][target][k] for k in ("decision", "by", "seq")},
                "reason": tag("human_reason", state["decision_reasons"][target]["reason"])},
        }
    elif kind == "closeout":
        if target != pid:
            raise NotFound("四顾清单的 id 就是题目 id")
        obj = cards.card_object(state, pid, kind, target, ctx["ref"])
        display = {"steps": ["四顾", "满志", "藏刀"], "terminal_if_closed_now": wk.terminal(state, pid),
                   "terminal_badge": _badge(p, p["goal"]["check"]["judge_id"])}
    else:
        raise NotEnabled(f"{kind} 卡随 M1 落地（续期门、争议裁决）")
    if obj is None:
        raise NotFound(f"没有 {kind} 卡 {target}")
    return {"card": obj, "card_hash": cards.card_hash(obj), "display": display}


# ---------- Hint 效果追溯（H4）：时序关联与暴露关联两列，都只是“关联” ----------

def hint_trace(state: State, events: Sequence[Mapping[str, Any]], hid: str) -> View:
    """events：该题的事件（服务层读日志后传入，本函数不做 IO）。

    时序关联：该 Hint 之后新增与放弃的 Intent。
    暴露关联：任务包含该 Hint 的 Reason 会话（签发时 Hint 已存在且未关闭），以及这些会话产出与放弃的 Intent。"""
    h = state["hints"].get(hid)
    if h is None:
        raise NotFound(f"没有 Hint {hid}")
    pid = h["problem_id"]
    closed_seq = next((e["seq"] for e in events if e["kind"] == "hint" and e["body"].get("close") == hid), None)
    abandons = [(e["seq"], e["body"]["intent"], e["actor"].get("session")) for e in events
                if e["kind"] == "abandon_intent" or (e["kind"] == "approve" and e["body"].get("decision") == "deny")]
    intents = _intents(state, pid)
    sessions = sorted((l for l in wk.leases_of(state, pid) if l["kind"] == "reason" and l["issued_seq"] > h["seq"]
                       and (closed_seq is None or l["issued_seq"] < closed_seq)), key=lambda l: l["issued_seq"])
    ids = {l["id"] for l in sessions}
    return {"hint": _hint(h), "closed_seq": closed_seq, "note": "关联，不是因果",
            "temporal": {"added": [i["id"] for i in intents if _seq(i["id"]) > h["seq"]],
                         "abandoned": [iid for seq, iid, _ in abandons if seq > h["seq"]]},
            "exposure": {"sessions": [l["id"] for l in sessions],
                         "added": [i["id"] for i in intents if i.get("session") in ids],
                         "abandoned": [iid for _, iid, s in abandons if s in ids]}}


# ---------- 画像预览（HMI §3.2）：与开题同一个推导函数，不写日志 ----------

def profile_preview(body: Any, cfg: Config) -> View:
    """body 是未经校验的请求体：经解析层读，形状不对抛 BadBody（HTTP 层转成 400 schema_error）。"""
    b = Obj(body)
    if "profile" in b:
        raise BadBody("profile 是派生字段，提交时不接受")
    given = b.children("scope")
    scope = [_rule(Obj({"pattern": "", "actions": [], **r.raw}, r.where)) for r in given]   # 预览时这两项可以先不填
    if not scope:
        raise BadBody("scope 必填且非空")
    jid = b.child("goal").child("check").string("judge_id")
    if jid not in cfg.judges:
        raise NotFound(f"判官 {jid} 未注册")
    j = cfg.judges[jid]
    prof = _derive_profile(scope, j, cfg)
    top = next(i for i, r in enumerate(scope) if r["risk"] == prof["reversibility"])
    ext = [i for i, r in enumerate(scope) if r["resource"] in cfg.external_resources]
    why_judge: View
    if j["grade"] == "advisory":
        why_judge = {"rule": "grade=advisory", "field": "grade", "value": j["grade"]}
    elif j["kind"] == "deferred" or j["grade"] == "consistent":
        why_judge = ({"rule": "kind=deferred", "field": "kind", "value": j["kind"]} if j["kind"] == "deferred"
                     else {"rule": "grade=consistent", "field": "grade", "value": j["grade"]})
    else:
        why_judge = {"rule": "max_cost 与廉价判官阈值比较", "field": "max_cost", "value": j["max_cost"],
                     "threshold": cfg.cheap_judge_max_cost}
    return {"profile": prof, "basis": {
        "reversibility": {"rule": "scope 中的最高风险", "scope_index": top, "risk": scope[top]["risk"],
                          "defaulted": "risk" not in given[top]},
        "judge": {"judge_id": jid, "version": j.get("version"), **why_judge},
        "info": {"rule": "scope 中有外部资源即 partial", "scope_indexes": ext,
                 "resources": sorted({scope[i]["resource"] for i in ext})}}}


def judges(cfg: Config) -> View:
    """判官注册表（只读）。向导的判官选择器读这里；判官不能在向导里新建。"""
    return {"items": [{"judge_id": k, **dict(v)} for k, v in sorted(cfg.judges.items())],
            "external_resources": sorted(cfg.external_resources)}
