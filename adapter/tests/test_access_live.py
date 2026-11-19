"""运行时扩权落到真执行层（设计 docs/design/runtime-grants/ §5、§6；§12 第二步）。需要本机 Docker。

开题零出站的题：会话里 request_access 一个目标。练习道白名单内当场批下、闸门热加，紧接着的 exec 就连得上；
白名单外的等人批，人批的那一刻会话运行器把在跑的沙箱对齐过去，执行容器不重建；撤销后下一次连接失败。
"""

import dataclasses
import hashlib
import threading
import time

import pytest
from adapter_rig import FETCH, PROBE, docker_ok, drig, graph, lease_bootstrap, upstream  # noqa: F401
from test_integration import EXEC, SUBMIT, results

from paoding_adapter.tools import ToolHost
from paoding_graph.contract import load_policy, seen_card

pytestmark = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")
ACCESS = "mcp__paoding__request_access"
POLICY = {
    "version": 1,
    "allow": {"resources": ["net", "workspace"], "net_patterns": ["pdt-*:8080"], "max_risk": "r0"},
    "judge": {"ids": ["exact_match"], "require_sealed": True},
    "budget": {"usd_milli_max": 5000, "wall_s_max": 3600},
    "goal": {"max_attempts_max": 5},
}


def turn_on(drig, practice=False):
    drig.graph.cfg = dataclasses.replace(
        drig.graph.cfg,
        external_resources=frozenset({"net"}),
        grants_runtime=True,
        risk_table=({"resource": "net", "pattern": "pdt-*:8080", "actions": ["connect"], "risk": "r0"},),
        practice=load_policy(POLICY) if practice else None,
    )
    drig.cfg.grants_runtime = lambda: drig.graph.cfg.grants_runtime


def open_zero_egress(svc, pid, lane=None):
    art = {"size": 1, "media_type": "text/plain", "class": "input"}
    origin = {"statement_ref": "$0", "materials": []}
    if lane:
        origin["draft"] = {"record": "$1", "lane": lane}
    body = {
        "title": "取回目标上的取值",
        "origin": origin,
        "goal": {
            "statement": "取回 /value",
            "check": {"judge_id": "exact_match", "sealed": [{"vault": "v", "digest": "d" * 64}]},
            "max_attempts": 3,
            "accept": "judge",
        },
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "basic@1"},
        "judges": ["exact_match"],
    }
    ops = [
        {"op": "register_artifact", "body": {**art, "hash": hashlib.sha256(b"s" + pid.encode()).hexdigest()}},
        {"op": "register_artifact", "body": {**art, "hash": hashlib.sha256(b"r" + pid.encode()).hexdigest()}},
        {"op": "open_problem", "body": body},
    ]
    out = svc.submit("tok-human", pid, f"open-{pid}", ops)
    assert out["ok"], out


def test_practice_grant_is_usable_by_the_next_exec(drig):
    turn_on(drig, practice=True)
    t = drig.target({"value": "v-77"})
    open_zero_egress(drig.graph, "p2", lane="practice")
    lid = lease_bootstrap(drig.graph, "p2")
    drig.script_for(
        "bootstrap",
        [
            {"tool": EXEC, "input": {"cmd": PROBE.format(h=t, p=8080)}},
            {"tool": ACCESS, "input": {"target": f"{t}:8080", "why": "题面给的服务"}},
            {"tool": EXEC, "input": {"cmd": FETCH.format(host=t, path="value")}},
            {"tool": EXEC, "input": {"cmd": PROBE.format(h=t, p=8081)}},
            {"tool": SUBMIT, "input": {"ops": [], "final": {"outcome": "nothing"}}},
        ],
    )
    before, asked, fetched, other = results(drig.run(lid, "p2"))[:4]
    assert before["exit_code"] != 0  # 开题零出站
    assert asked["status"] == "granted" and "detail" not in asked
    assert fetched["exit_code"] == 0 and fetched["output"].strip() == "v-77"
    assert drig.graph.state["artifacts"][fetched["artifact"]]["exec"]["touched"] == [f"net:{t}:8080"]
    assert other["exit_code"] != 0  # 只开写明的端口
    assert drig.sandboxes() == []


def test_human_grant_mid_session_realigns_then_revoke_closes(drig, monkeypatch):
    turn_on(drig)
    t = drig.target({"value": "v-88"})
    open_zero_egress(drig.graph, "p2")
    lid = lease_bootstrap(drig.graph, "p2")
    drig.script_for(
        "bootstrap",
        [
            {"tool": ACCESS, "input": {"target": f"{t}:8080", "why": "题面给的服务"}},
            {"hang": 4},  # 人在这期间批准
            {"tool": EXEC, "input": {"cmd": FETCH.format(host=t, path="value")}},
            {"hang": 4},  # 人在这期间撤销
            {"tool": EXEC, "input": {"cmd": PROBE.format(h=t, p=8080)}},
            {"tool": SUBMIT, "input": {"ops": [], "final": {"outcome": "nothing"}}},
        ],
    )
    order = []
    orig_rec, orig_exec = drig.executor.reconcile, ToolHost._exec
    monkeypatch.setattr(
        drig.executor, "reconcile", lambda sid, spec: order.append(("gate", orig_rec(sid, spec))) or order[-1][1]
    )
    monkeypatch.setitem(ToolHost._TOOLS, "exec", lambda self, a: (order.append(("exec", None)), orig_exec(self, a))[1])
    sandboxes = []

    def human():
        g = drig.graph
        deadline = time.time() + 30
        while not g.state.get("scope_requests") and time.time() < deadline:
            time.sleep(0.05)
        [rid] = g.state["scope_requests"]
        seen = seen_card(g.state, "p2", "scope", rid)
        body = {"request": rid, "decision": "approve", "seen": seen}
        assert g.submit("tok-human", "p2", "g1", [{"op": "grant_scope", "body": body}])["ok"]
        while not any(a["class"] == "exec" for a in g.state["artifacts"].values()) and time.time() < deadline:
            time.sleep(0.05)
        sandboxes.append(drig.sandboxes())
        idx = len(g.state["problems"]["p2"]["scope"]) - 1
        body = {"rule": idx, "reason": "用完了"}
        assert g.submit("tok-human", "p2", "rv1", [{"op": "revoke_scope", "body": body}])["ok"], "revoke"

    th = threading.Thread(target=human)
    th.start()
    asked, fetched, after = results(drig.run(lid, "p2"))[:3]
    th.join()
    assert asked["status"] == "pending"
    assert fetched["exit_code"] == 0 and fetched["output"].strip() == "v-88"
    assert fetched["access"][0]["status"] == "granted"
    # 闸门在人批准的那一刻由会话运行器热加，早于下一次 exec；撤销同样不等 exec
    gates = [o for k, o in order if k == "gate" and (o["added"] or o["removed"])]
    assert gates == [{"added": [t], "removed": []}, {"added": [], "removed": [t]}]
    first_exec = next(i for i, (k, _) in enumerate(order) if k == "exec")
    assert order.index(("gate", gates[0])) < first_exec
    assert after["exit_code"] != 0
    assert len(sandboxes[0]) == 1  # 执行容器没重建
