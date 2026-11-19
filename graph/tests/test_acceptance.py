"""人工验收（宪章 D3、02 §3.3）：accept=human 的题开题时登记验收清单，人逐条判、绑定所见，全部通过才 accepted。"""

from conftest import HUMAN, Kernel

from paoding_graph import work as wk
from paoding_graph.cards import seen as seen_card

GRAPH = {"kind": "graph", "id": "graph"}
LIST = [
    {"text": "说明覆盖三个场景", "src": "span"},
    {"text": "附运行结果", "src": "human", "needs": "artifact"},
    {"text": "写明没做的部分", "src": "human", "needs": "note"},
]


def open_human(k, pid="p1", acceptance=LIST, judge="advice", **goal):
    st = k.art(pid, "input", b"statement " + pid.encode())
    body = {
        "title": "t",
        "origin": {"statement_ref": st, "materials": []},
        "goal": {
            "statement": "写一份说明",
            "check": {"judge_id": judge},
            "max_attempts": 3,
            "accept": "human",
            **({"acceptance": acceptance} if acceptance is not None else {}),
            **goal,  # 覆盖 accept、check 用
        },
        "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["replay", "exact_match", "advice"],
    }
    return k.submit(HUMAN, pid, "open_problem", body)


def deliver(k, pid="p1", result="pass"):
    cand = k.art(pid, "authored", b"deliverable " + str(len(k.events)).encode())
    assert k.verdict(pid, "goal", result, judge="advice", candidate=cand) == "ok"
    return cand


def checks(k, pid="p1", fail=()):
    run = k.art(pid, "exec", b"run output")
    out = []
    for a in k.state["problems"][pid]["goal"]["acceptance"]:
        c = {"id": a["id"], "verdict": "fail" if a["id"] in fail else "pass"}
        if a.get("needs") == "artifact":
            c["ref"] = run
        if a.get("needs") == "note":
            c["note"] = "数据导出没做，原因见说明第 4 节"
        out.append(c)
    return out


def accept(k, pid="p1", decision="accept", fail=(), seen=None, **extra):
    four = [i["item"] for i in wk.closeout_items(k.state, pid)]  # 默认逐条确认四顾清单（Q21）
    body = {
        "decision": decision,
        "checks": checks(k, pid, fail),
        "seen": seen or seen_card(k.state, pid, "closeout", pid),
        **({"closeout": four} if decision == "accept" else {}),
        **extra,
    }
    return k.submit(HUMAN, pid, "accept", body)


def test_open_registers_numbered_list_and_human_authority():
    k = Kernel()
    assert open_human(k) == "ok"
    g = k.state["problems"]["p1"]["goal"]
    assert [a["id"] for a in g["acceptance"]] == ["a1", "a2", "a3"]
    assert g["authority"] == "human" and g["accept"] == "human"


def test_open_rules():
    k = Kernel()
    assert open_human(k, "p1", acceptance=None) == "schema_error"  # human 必带清单
    assert open_human(k, "p2", acceptance=[]) == "schema_error"
    assert open_human(k, "p3", acceptance=[{"text": "x", "src": "model"}]) == "schema_error"  # 模型起草的不进
    assert open_human(k, "p4", acceptance=[{"id": "a9", "text": "x", "src": "human"}]) == "schema_error"
    assert open_human(k, "p5", acceptance=[{"text": "x" * 201, "src": "human"}]) == "schema_error"
    assert open_human(k, "p6", acceptance=[{"text": "x", "src": "human", "needs": "photo"}]) == "schema_error"
    # judge 道不接受清单
    assert open_human(k, "p7", accept="judge") == "schema_error"
    assert open_human(k, "p8", acceptance=None, accept="judge", check={"judge_id": "exact_match"}) == "ok"


def test_acceptance_waits_for_a_passing_deliverable():
    k = Kernel()
    open_human(k)
    assert accept(k) == "schema_error"  # 还没有交付物
    assert not any(w.get("why") == "acceptance" for w in wk.work(k.state, "p1"))
    deliver(k, result="fail")
    assert wk.acceptance_ready(k.state, "p1") is None
    deliver(k)
    assert wk.acceptance_ready(k.state, "p1") is not None
    assert {"kind": "human", "target": "p1", "why": "acceptance"} in wk.work(k.state, "p1")


def test_accept_all_pass_then_graph_closes_accepted():
    k = Kernel()
    open_human(k)
    deliver(k)
    assert accept(k) == "ok"
    p = k.state["problems"]["p1"]
    assert p["accepted"] and wk.terminal(k.state, "p1") == "accepted"
    assert wk.followups(k.state, "p1") == [
        ("close_problem", {"terminal": "accepted", "card_hash": None, "by": "accept"})
    ]
    assert k.submit(GRAPH, "p1", "close_problem", {"terminal": "accepted", "card_hash": None, "by": "accept"}) == "ok"
    assert k.state["problems"]["p1"]["terminal"] == "accepted"


def test_evidence_rules_per_item():
    k = Kernel()
    open_human(k)
    deliver(k)
    seen = seen_card(k.state, "p1", "closeout", "p1")
    c = checks(k)
    no_ref = [{**x} for x in c]
    no_ref[1].pop("ref")
    assert k.submit(HUMAN, "p1", "accept", {"decision": "accept", "checks": no_ref, "seen": seen}) == "missing_evidence"
    no_note = [{**x} for x in c]
    no_note[2].pop("note")
    assert (
        k.submit(HUMAN, "p1", "accept", {"decision": "accept", "checks": no_note, "seen": seen}) == "missing_evidence"
    )
    authored = k.art("p1", "authored", b"self report")
    bad_ref = [{**x} for x in c]
    bad_ref[1]["ref"] = authored
    seen = seen_card(k.state, "p1", "closeout", "p1")
    assert (
        k.submit(HUMAN, "p1", "accept", {"decision": "accept", "checks": bad_ref, "seen": seen}) == "inadmissible_class"
    )
    assert k.submit(HUMAN, "p1", "accept", {"decision": "accept", "checks": c[:2], "seen": seen}) == "schema_error"
    assert (
        k.submit(HUMAN, "p1", "accept", {"decision": "accept", "checks": [c[0], c[0], c[2]], "seen": seen})
        == "schema_error"
    )


def test_any_fail_only_rejects_and_waits_for_a_new_deliverable():
    k = Kernel()
    open_human(k)
    deliver(k)
    assert accept(k, fail=("a1",)) == "schema_error"  # 有不通过只能拒收
    assert accept(k, decision="reject", fail=("a1",)) == "schema_error"  # 拒收须写理由
    assert accept(k, decision="reject", fail=("a1",), reason="第三个场景没写") == "ok"
    p = k.state["problems"]["p1"]
    assert not p.get("accepted") and not p["closed"]
    assert wk.acceptance_ready(k.state, "p1") is None  # 回到人介入：等新的交付物
    assert accept(k) == "schema_error"
    deliver(k)
    assert accept(k) == "ok"


def test_seen_binds_the_list_and_the_deliverable():
    k = Kernel()
    open_human(k)
    deliver(k)
    old = seen_card(k.state, "p1", "closeout", "p1")
    deliver(k)  # 又交了一份：人看的那份已不是待验收的
    assert accept(k, seen=old) == "stale_view"
    assert accept(k) == "ok"


def test_judge_lane_has_no_accept_and_no_accepted():
    k = Kernel()
    k.open("p1")
    seen = seen_card(k.state, "p1", "closeout", "p1")
    assert k.submit(HUMAN, "p1", "accept", {"decision": "accept", "checks": [], "seen": seen}) == "forbidden_op"
    assert (
        k.submit(GRAPH, "p1", "close_problem", {"terminal": "accepted", "card_hash": None, "by": "accept"})
        == "schema_error"
    )


def test_external_judge_rejects_human_accept():
    from paoding_graph.reducer import problem

    assert problem.authority_of({"authority": "external"}, "human") == "human"


def test_closeout_items_must_each_be_confirmed_before_accepting():
    """关题三步不可跳（地图 Q21、AC9.2）：四顾清单每一项都要逐条确认，缺哪一项就指出哪一项。"""
    from paoding_graph.parse import Obj
    from paoding_graph.reducer import Config
    from paoding_graph.reducer.close import _v_accept

    k = Kernel()
    open_human(k)
    deliver(k)
    assert [i["item"] for i in wk.closeout_items(k.state, "p1")] == ["closeout_review"]
    body = {
        "decision": "accept",
        "checks": checks(k),
        "seen": seen_card(k.state, "p1", "closeout", "p1"),
        "closeout": [],
    }
    r = _v_accept(k.state, HUMAN, "p1", Obj(body), Config())
    assert r.code == "schema_error" and "closeout_review" in r.detail
    assert accept(k, closeout=["closeout_review", "nope"]) == "schema_error"
    assert accept(k, decision="reject", reason="没写完") == "ok"  # 拒收不需要四顾
    deliver(k)
    assert accept(k) == "ok"
    ev = [e for e in k.events if e["kind"] == "accept"][-1]
    assert ev["body"]["closeout"] == ["closeout_review"]


def test_runtime_grants_and_live_sessions_join_the_closeout_list():
    k = Kernel()
    open_human(k)
    p = k.state["problems"]["p1"]
    rule = {
        "resource": "net",
        "pattern": "q1:80",
        "actions": ["connect"],
        "risk": "r1",
        "granted": {"seq": 9, "by": "cz", "request": "s_9"},
    }
    k.state["problems"]["p1"] = {**p, "scope": [*p["scope"], rule]}
    items = {i["item"]: i for i in wk.closeout_items(k.state, "p1")}
    assert items["scope_granted"]["rules"] == [
        {"resource": "net", "pattern": "q1:80", "actions": ["connect"], "risk": "r1"}
    ]
    k.state["problems"]["p1"]["scope"][-1] = {**rule, "revoked": 12}
    assert "scope_granted" not in {i["item"] for i in wk.closeout_items(k.state, "p1")}
