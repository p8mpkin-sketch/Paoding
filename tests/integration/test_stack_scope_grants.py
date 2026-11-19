"""运行时扩权在图服务与执行层之间的接线（设计 docs/design/runtime-grants/，§12 第一步）。不需要 Docker。

验收门（§11 第 6 条，cz 2026-11-19）：人批准一个带 needs_scope 的 Intent 之后，执行层编出的出站规则必须含那条规则。
修复之前这条测试失败：compile_spec 只读 Problem.scope，而批准从不修订它。
"""

from __future__ import annotations

import hashlib

import pytest

from paoding_executor.compile import compile_spec
from paoding_graph import work as wk
from paoding_graph.cards import seen as seen_card
from paoding_graph.reducer import Config
from paoding_graph.service import GraphService
from paoding_graph.tokens import TokenRegistry

JUDGES = {"exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0}}
HUMAN = {"kind": "human", "id": "cz"}
REASON = {"kind": "adapter", "id": "ad1", "session": "R1", "role": "reason"}
ENV = {"base": "basic", "baseline_ref": "basic@1"}
WANT = {"resource": "net", "pattern": "q7.lab:8443", "actions": ["connect"], "risk": "r0"}


@pytest.fixture
def g(tmp_path):
    reg = TokenRegistry()
    reg.issue(HUMAN, "tok-h")
    reg.issue(REASON, "tok-r")
    t = [1000]

    def tick():
        t[0] += 1
        return t[0]

    return GraphService(tmp_path / "g.sqlite", Config(judges=JUDGES), reg, tick)


def submit(g, tok, ops, key):
    out = g.submit(tok, "p1", key, [{"op": k, "body": b} for k, b in ops])
    assert out["ok"], out
    return out["results"]


def opened(g):
    st = {"hash": hashlib.sha256(b"s").hexdigest(), "size": 1, "media_type": "text/plain", "class": "input"}
    body = {
        "title": "t",
        "origin": {"statement_ref": "$0", "materials": []},
        "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": 500, "wall_s": 600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": ENV,
        "judges": ["exact_match"],
    }
    submit(g, "tok-h", [("register_artifact", st), ("open_problem", body)], "open")


def egress(g):
    p = g.state["problems"]["p1"]
    return compile_spec("s1", p["scope"], ENV, "r0", False, "/w").egress_rules


def test_approved_needs_scope_is_compiled_into_the_sandbox(g):
    """验收门：批准之前不通，批准之后编进容器。"""
    opened(g)
    need = {k: WANT[k] for k in ("resource", "pattern", "actions", "risk")}
    iid = submit(
        g,
        "tok-r",
        [("add_intent", {"title": "读接口", "risk": "r0", "budget": {"usd_milli": 50}, "needs_scope": [need]})],
        "i",
    )[0]["id"]
    assert wk.intent_status(g.state, "p1", iid) == "needs_human"
    assert egress(g) == ()
    seen = seen_card(g.state, "p1", "approval", iid)
    submit(g, "tok-h", [("approve", {"intent": iid, "decision": "approve", "seen": seen})], "a")
    assert egress(g) == (("q7.lab:8443", ("connect",)),)


def test_revoked_rule_leaves_the_sandbox(g):
    """撤销留在原位、下标不变，执行层不再编入（§4.3）。"""
    test_approved_needs_scope_is_compiled_into_the_sandbox(g)
    k = len(g.state["problems"]["p1"]["scope"]) - 1
    submit(g, "tok-h", [("revoke_scope", {"rule": k, "reason": "用完了"})], "rv")
    assert egress(g) == () and len(g.state["problems"]["p1"]["scope"]) == k + 1


def test_settings_grants_reach_the_kernel(tmp_path):
    """设置层 grants 节与风险表随设置变更整体替换内核 Config；新装缺省 runtime = on（§12 第四步）。"""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from stack import Stack, StackConfig

    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none"))
    try:
        assert s.graph.cfg.grants_runtime is True and s.graph.cfg.grants_auto_practice is True
        store = s.settings.store
        table = [{"resource": "net", "pattern": "q*.lab:*", "actions": ["connect"], "risk": "r0"}]
        store.settings = {**store.settings, "risk": table, "grants": {"runtime": True, "auto": {"practice": False}}}
        s.settings.apply()
        assert s.graph.cfg.grants_runtime is True and s.graph.cfg.grants_auto_practice is False
        assert s.graph.cfg.risk_table == tuple(table)
    finally:
        s.http.close()
