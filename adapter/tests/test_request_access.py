"""request_access 工具（设计 docs/design/runtime-grants/ §6；§12 第二步）。真图服务，执行层用进程内替身。

申请不是授权：练习道白名单内当场自动批并立即对齐沙箱；其余挂进人的待办，批下来后 exec 的返回里带 access；
人拒过的地址再申请即 denied；风险高于任务上限的规则批了也不进本任务的沙箱；开关关着时会话里没有这个工具。
"""

import dataclasses
import hashlib

import pytest
from adapter_rig import CFG, FakeExec

from paoding_adapter.tools import Session, ToolHost, tool_schemas
from paoding_graph.contract import BlobStore, GraphService, TokenRegistry, load_policy, seen_card

POLICY = {
    "version": 3,
    "allow": {"resources": ["net", "workspace"], "net_patterns": ["q*.lab:*"], "max_risk": "r0"},
    "judge": {"ids": ["exact_match"], "require_sealed": True},
    "budget": {"usd_milli_max": 500, "wall_s_max": 1800},
    "goal": {"max_attempts_max": 5},
}
TABLE = (
    {"resource": "net", "pattern": "q*.lab:*", "actions": ["connect"], "risk": "r0"},
    {"resource": "net", "pattern": "hot.lab:*", "actions": ["connect"], "risk": "r1"},
)
ON = dataclasses.replace(
    CFG, external_resources=frozenset({"net"}), grants_runtime=True, risk_table=TABLE, practice=load_policy(POLICY)
)


def make(tmp_path, cfg=ON, lane="practice"):
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": "cz"}, "tok-human")
    reg.issue({"kind": "sinan", "id": "sn1"}, "tok-sinan")
    reg.issue({"kind": "executor", "id": "ex1"}, "tok-exec")
    t = [1000]

    def tick():
        t[0] += 1
        return t[0]

    g = GraphService(tmp_path / "g.sqlite", cfg, reg, tick)
    art = {"size": 1, "media_type": "text/plain", "class": "input"}
    origin = {"statement_ref": "$0", "materials": []}
    if lane:
        origin["draft"] = {"record": "$1", "lane": lane}
    body = {
        "title": "t",
        "origin": origin,
        "goal": {
            "statement": "g",
            "check": {"judge_id": "exact_match", "sealed": [{"vault": "v", "digest": "d" * 64}]},
            "max_attempts": 5,
            "accept": "judge",
        },
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": 500, "wall_s": 1800, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "basic@1"},
        "judges": ["exact_match"],
    }
    ops = [
        {"op": "register_artifact", "body": {**art, "hash": hashlib.sha256(b"s").hexdigest()}},
        {"op": "register_artifact", "body": {**art, "hash": hashlib.sha256(b"r").hexdigest()}},
        {"op": "open_problem", "body": body},
    ]
    assert g.submit("tok-human", "p1", "open", ops)["ok"]
    lease = {"kind": "bootstrap", "holder": "sn1", "reserve": {"usd_milli": 100, "wall_s": 600}, "ttl_s": 600}
    out = g.submit("tok-sinan", "p1", "lease", [{"op": "lease", "body": lease}])
    assert out["ok"], out
    lid = out["results"][0]["id"]
    tok = g.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": "bootstrap"})
    blobs = BlobStore(tmp_path / "blobs")
    aligned = []
    tools = ("exec", "submit", "show", "request_access")
    s = Session("p1", lid, "bootstrap", tok, tmp_path, tools, "sbx-1")

    def align():
        aligned.append(1)
        return {"added": [], "removed": []}

    host = ToolHost(s, g, g, blobs, FakeExec(g, blobs), access=align)
    return g, host, aligned


def human(g, kind, body, key):
    out = g.submit("tok-human", "p1", key, [{"op": kind, "body": body}])
    assert out["ok"], out


def test_practice_whitelist_is_granted_and_aligned_at_once(tmp_path):
    g, host, aligned = make(tmp_path)
    r = host.call("request_access", {"target": "q7.lab:8443", "why": "题目给的接口"})
    assert r["status"] == "granted" and r["risk"] == "r0" and "detail" not in r
    assert aligned == [1]  # 返回时闸门已对齐
    assert g.state["problems"]["p1"]["scope"][-1]["granted"]["by"] == "graph"
    again = host.call("request_access", {"target": "q7.lab:8443", "why": "再要一次"})
    assert again["status"] == "granted" and "request" not in again  # 已在范围内：不再提申请
    assert len(g.state["scope_requests"]) == 1


def test_outside_whitelist_waits_for_human_then_exec_reports(tmp_path):
    g, host, aligned = make(tmp_path)
    r = host.call("request_access", {"target": "api.example.com:443", "why": "文档里的服务"})
    assert r["status"] == "pending" and aligned == []
    assert "access" not in host.call("exec", {"cmd": "true"})
    rid = r["request"]
    seen = seen_card(g.state, "p1", "scope", rid)
    human(g, "grant_scope", {"request": rid, "decision": "approve", "seen": seen}, "g1")
    out = host.call("exec", {"cmd": "true"})
    assert out["access"] == [{"request": rid, "status": "granted", "target": "api.example.com:443"}]
    assert aligned == [1]
    assert "access" not in host.call("exec", {"cmd": "true"})  # 只报一次


def test_denied_is_reported_and_cannot_be_asked_again(tmp_path):
    g, host, _ = make(tmp_path)
    rid = host.call("request_access", {"target": "api.example.com:443", "why": "x"})["request"]
    seen = seen_card(g.state, "p1", "scope", rid)
    human(g, "grant_scope", {"request": rid, "decision": "deny", "reason": "不需要", "seen": seen}, "d1")
    news = host.call("exec", {"cmd": "true"})["access"]
    assert news == [{"request": rid, "status": "denied", "target": "api.example.com:443", "reason": "不需要"}]
    r = host.call("request_access", {"target": "api.example.com:443", "why": "再试"})
    assert r["status"] == "denied"


def test_above_ceiling_is_granted_but_not_opened_here(tmp_path):
    g, host, _ = make(tmp_path)
    rid = host.call("request_access", {"target": "hot.lab:9000", "why": "x"})["request"]  # 风险表：r1，不自动批
    seen = seen_card(g.state, "p1", "scope", rid)
    human(g, "grant_scope", {"request": rid, "decision": "approve", "seen": seen}, "g1")
    r = host.call("request_access", {"target": "hot.lab:9000", "why": "x"})
    assert r["status"] == "granted" and r["risk"] == "r1" and "风险上限" in r["detail"]


@pytest.mark.parametrize(
    "args",
    [{"target": "q7.lab:8443"}, {"target": "q7.lab:8443", "why": " "}, {"target": "q7.lab", "why": "x"}],
)
def test_bad_requests_are_rejected(tmp_path, args):
    _, host, aligned = make(tmp_path)
    r = host.call("request_access", args)
    assert r.get("ok") is False and r["code"] == "schema_error" and aligned == []


def test_risk_is_not_self_reported(tmp_path):
    _, host, _ = make(tmp_path)
    r = host.call("request_access", {"target": "api.example.com:443", "why": "x", "risk": "r0"})
    assert r.get("ok") is False and r["code"] == "schema_error"


def test_runtime_off_means_not_enabled(tmp_path):
    g, host, _ = make(tmp_path, cfg=dataclasses.replace(ON, grants_runtime=False))
    r = host.call("request_access", {"target": "q7.lab:8443", "why": "x"})
    assert r.get("ok") is False and r["code"] == "not_enabled"


def test_tool_listed_only_when_given():
    assert "request_access" not in [t["name"] for t in tool_schemas(("exec", "submit", "show"))]
    [t] = [t for t in tool_schemas(("exec", "request_access")) if t["name"] == "request_access"]
    assert t["inputSchema"]["required"] == ["target", "why"]


class HotExec(FakeExec):
    def __init__(self, graph, blobs):
        super().__init__(graph, blobs)
        self.specs = []

    def reconcile(self, sid, spec):
        self.specs.append((sid, spec))
        return {"added": [], "removed": []}


@pytest.mark.parametrize("hot", [True, False])
def test_runner_realigns_the_live_sandbox(tmp_path, hot):
    """会话运行器的 reconcile：按当前 Problem.scope 重编授权交给执行器；grants_hot 关掉时退回租约边界。"""
    from paoding_adapter.session import AdapterConfig, SessionRunner

    g, host, _ = make(tmp_path)
    host.call("request_access", {"target": "q7.lab:8443", "why": "x"})
    ex = HotExec(g, BlobStore(tmp_path / "b2"))
    cfg = AdapterConfig(root=tmp_path / "sessions", judges_cfg=CFG.judges, grants_hot=hot)
    runner = SessionRunner(cfg, g, g, ex.blobs, g.tokens, None, None, ex)
    lid = host.s.lease_id
    runner.live[lid] = {"sandbox_id": "sbx-1", "ws": tmp_path}
    out = runner.reconcile(lid)
    if not hot:
        assert out is None and ex.specs == []
        return
    [(sid, spec)] = ex.specs
    assert sid == "sbx-1" and out == {"added": [], "removed": []}
    assert spec.egress_allow == ("q7.lab:8443",)


def test_prompt_mentions_the_tool_only_when_given():
    from paoding_adapter.package import role_prompt

    plain, on = role_prompt("bootstrap"), role_prompt("bootstrap", access=True)
    assert "request_access" not in plain
    assert "request_access" in on and "没有任何出站权限" in on
    assert on.index("request_access") > on.index("- show：") and on.index("request_access") < on.index("核心概念")
