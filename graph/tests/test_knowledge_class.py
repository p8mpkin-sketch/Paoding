"""knowledge 类（资料库第二期，K1；cz 2026-11-20 验收附加条件 2）。

- 只由书库的组件令牌（graph:shuku）登记，带出处 {source, revision, chunk, locator}；会话与人都不能登记这一类。
- 开放道：交付的主张（claims）可以引用 knowledge 依据；自检（self_check）不认——自检要的是这次跑出来的东西。
- 判定道（严格道）不认 knowledge 依据：事实的 grounds、人工验收清单的依据都拒为 inadmissible_class。
- 视图里登记人显示为“人”（资料是人给的），并带出处；prefs.knowledge 取 auto / pick / off。
"""

from __future__ import annotations

import hashlib

from conftest import ADAPTER, EXECUTOR, HUMAN, Kernel, explore
from test_acceptance import checks, deliver, open_human
from test_open_lane import lease_solve, open_lane, solver
from test_prefs import body as open_body

from paoding_graph import views
from paoding_graph.cards import seen as seen_card
from paoding_graph.contract import ADMISSIBLE_CLASSES, ARTIFACT_CLASSES, KNOWLEDGE_REGISTRAR

SHUKU = {"kind": "graph", "id": "shuku"}
REF = {"source": "s_abc123", "revision": 1, "chunk": "k_0123456789abcdef", "locator": "ops.md / 回滚"}


def kn_body(text: bytes = "回滚用上一个标签。".encode(), **extra) -> dict:
    return {
        "hash": hashlib.sha256(text).hexdigest(),
        "size": len(text),
        "media_type": "text/plain",
        "class": "knowledge",
        "knowledge": dict(REF),
        **extra,
    }


def knowledge(k: Kernel, pid: str = "p1", actor: dict | None = None, **extra) -> str:
    return k.submit(actor or SHUKU, pid, "register_artifact", kn_body(**extra))


def test_contract_names_the_class_and_keeps_it_out_of_admissible():
    assert "knowledge" in ARTIFACT_CLASSES
    assert "knowledge" not in ADMISSIBLE_CLASSES
    assert KNOWLEDGE_REGISTRAR == SHUKU


def test_only_the_shuku_token_registers_knowledge():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    for who in (solver(lid), HUMAN, EXECUTOR, ADAPTER, {"kind": "graph", "id": "graph"}):
        assert knowledge(k, actor=who) == "forbidden_op", who
    aid = knowledge(k)
    assert aid.startswith("a_"), aid
    art = k.state["artifacts"][aid]
    assert art["class"] == "knowledge" and art["knowledge"] == REF
    assert knowledge(k, pid="nope") == "unknown_ref"


def test_knowledge_needs_its_provenance_and_only_it():
    k = Kernel()
    open_lane(k)
    bare = kn_body()
    bare.pop("knowledge")
    assert k.submit(SHUKU, "p1", "register_artifact", bare) == "schema_error"
    for bad in (
        {**REF, "extra": 1},
        {**REF, "revision": 0},
        {**REF, "revision": "1"},
        {**REF, "source": " "},
        {**REF, "chunk": ""},
    ):
        assert k.submit(SHUKU, "p1", "register_artifact", {**kn_body(), "knowledge": bad}) == "schema_error", bad
    # 别的类别不许夹带出处
    other = {**kn_body(), "class": "authored"}
    assert k.submit(ADAPTER, "p1", "register_artifact", other) == "schema_error"


def test_open_lane_claims_may_cite_knowledge_but_self_check_may_not():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    kid = knowledge(k)
    proof = k.art("p1", "exec", b"curl output")
    ans = k.art("p1", "authored", b"the answer", actor=solver(lid))
    bad = {
        "outcome": "answered",
        "answer": ans,
        "claims": [{"text": "回滚用上一个标签", "refs": [kid]}],
        "self_check": [{"what": "照资料核对", "result": "pass", "refs": [kid]}],
    }
    assert k.submit(solver(lid), "p1", "deliver", bad) == "inadmissible_class"
    good = {
        "outcome": "answered",
        "answer": ans,
        "claims": [{"text": "回滚用上一个标签", "refs": [kid]}, {"text": "接口返回 200", "refs": [proof]}],
        "self_check": [{"what": "再请求一次", "result": "pass", "refs": [proof]}],
    }
    assert k.submit(solver(lid), "p1", "deliver", good).startswith("d_")
    d = k.state["problems"]["p1"]["deliveries"][0]
    assert d["claims"][0]["refs"] == [kid]


def test_strict_lane_facts_never_rest_on_knowledge():
    """cz 验收附加条件 2：判定道不认 knowledge 依据。"""
    k = Kernel()
    k.open("p1")
    kid = knowledge(k)
    assert kid.startswith("a_")
    assert k.obs(grounds=[kid]) == "inadmissible_class"
    assert k.obs(grounds=[k.art("p1", "exec", b"run"), kid]) == "inadmissible_class"
    assert k.obs(grounds=[k.art("p1", "exec", b"run")]).startswith("f_")  # 对照：执行记录照常
    assert k.obs(actor=explore(), grounds=[kid], title="o2") == "inadmissible_class"


def test_human_acceptance_checklist_never_rests_on_knowledge():
    k = Kernel()
    open_human(k)
    deliver(k)
    kid = knowledge(k)
    seen = seen_card(k.state, "p1", "closeout", "p1")
    c = checks(k)
    c[1]["ref"] = kid
    assert k.submit(HUMAN, "p1", "accept", {"decision": "accept", "checks": c, "seen": seen}) == "inadmissible_class"


def test_view_shows_provenance_and_registers_as_human():
    k = Kernel()
    open_lane(k)
    kid = knowledge(k)
    v = views.artifact(k.state, kid)
    assert v is not None and v["knowledge"] == REF
    assert views.REGISTER["artifact:knowledge"] == "人"


def test_knowledge_prefs():
    k = Kernel()
    for good in ({"mode": "auto"}, {"mode": "off"}, {"mode": "pick", "pick": ["s_abc123"]}):
        k2 = Kernel()
        assert k2.submit(HUMAN, "p1", "open_problem", open_body(k2, prefs={"knowledge": good})) == "ok", good
        assert k2.state["problems"]["p1"]["prefs"]["knowledge"]["mode"] == good["mode"]
    for bad in (
        {"mode": "all"},
        {"mode": "pick"},
        {"mode": "pick", "pick": []},
        {"mode": "auto", "extra": 1},
        "auto",
    ):
        assert k.submit(HUMAN, "p1", "open_problem", open_body(k, prefs={"knowledge": bad})) == "schema_error", bad
