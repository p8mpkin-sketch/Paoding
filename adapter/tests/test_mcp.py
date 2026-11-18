"""工具端点的协议面：initialize / tools/list / tools/call，以及会话隔离。"""

import http.client
import json

from adapter_rig import graph, lease_bootstrap, rig, upstream  # noqa: F401  fixture

from paoding_adapter.tools import Session, ToolHost


def rpc(base, path, msg):
    host, port = base.split("//")[1].split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=5)
    c.request(
        "POST",
        path,
        body=json.dumps(msg),
        headers={"content-type": "application/json", "accept": "application/json, text/event-stream"},
    )
    r = c.getresponse()
    data = r.read()
    return r.status, (json.loads(data) if data else None)


def _host(rig, role="bootstrap", tools=("exec", "submit", "show")):
    lid = lease_bootstrap(rig.graph)
    tok = rig.graph.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": role})
    ws = rig.tmp / "ws"
    ws.mkdir(exist_ok=True)
    return ToolHost(Session("p1", lid, role, tok, ws, tools, "sb"), rig.graph, rig.graph, rig.blobs, rig.executor)


def test_protocol_roundtrip(rig):
    url = rig.endpoint.mount(_host(rig))
    path = "/" + url.split("/", 3)[3]
    st, init = rpc(
        rig.endpoint.base,
        path,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert st == 200 and init["result"]["capabilities"]["tools"] is not None
    assert rpc(rig.endpoint.base, path, {"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
    _, tl = rpc(rig.endpoint.base, path, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in tl["result"]["tools"]]
    assert names == ["exec", "submit", "show"]
    assert all(t["inputSchema"]["type"] == "object" for t in tl["result"]["tools"])
    _, call = rpc(
        rig.endpoint.base,
        path,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "exec", "arguments": {"cmd": "uname"}}},
    )
    out = call["result"]["structuredContent"]
    assert out["artifact"].startswith("a_") and out["exit_code"] == 0 and not call["result"]["isError"]
    assert json.loads(call["result"]["content"][0]["text"]) == out


def test_unknown_session_and_unmount(rig):
    url = rig.endpoint.mount(_host(rig))
    path = "/" + url.split("/", 3)[3]
    rig.endpoint.unmount(url)
    _, out = rpc(rig.endpoint.base, path, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert out["error"]["code"] == -32001
    _, out = rpc(rig.endpoint.base, "/mcp/guess", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "error" in out


def test_tool_not_granted_is_error(rig):
    url = rig.endpoint.mount(_host(rig, role="reason", tools=("submit", "show")))
    path = "/" + url.split("/", 3)[3]
    _, tl = rpc(rig.endpoint.base, path, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [t["name"] for t in tl["result"]["tools"]] == ["submit", "show"]
    _, call = rpc(
        rig.endpoint.base,
        path,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "exec", "arguments": {"cmd": "id"}}},
    )
    assert call["result"]["isError"] and call["result"]["structuredContent"]["code"] == "forbidden_op"
    assert rig.executor.calls == []


def test_show_reads_artifact_range_same_problem_only(rig):
    h = _host(rig)
    r = h.call("exec", {"cmd": "seq 1 100"})
    full = h.call("show", {"artifact": r["artifact"]})
    part = h.call("show", {"artifact": r["artifact"], "range": [2, 5]})
    assert part["text"] == full["text"][2:5] and part["range"] == [2, 5]
    from adapter_rig import open_problem

    open_problem(rig.graph, pid="p2")
    foreign = rig.put_input(b"p2 only", pid="p2")
    assert h.call("show", {"artifact": foreign})["code"] == "unknown_ref"
    assert h.call("show", {"list": "budget"})["cap"]["usd_milli"] == 5000


def test_show_refuses_judge_output_that_read_the_vault(rig):
    """3.3.5-9：读过保密库的判官输出不向会话开放；没碰保密库的判官输出照常可读。"""
    rig.graph.tokens.issue({"kind": "judge", "id": "jr1"}, "tok-judge")
    h = _host(rig)
    ids = {}
    for name, touched in (("sealed", ["vault:answer"]), ("plain", [])):
        data = f"judge output {name}".encode()
        prov = {
            "sandbox_id": "builtin",
            "base": "builtin",
            "baseline_ref": "builtin",
            "tool": "exact_match",
            "command": "exact_match",
            "cwd": "",
            "exit_code": 1,
            "touched": touched,
            "started_at": 1,
            "ended_at": 2,
            "truncated": False,
        }
        out = rig.graph.submit(
            "tok-judge",
            "p1",
            f"jo-{name}",
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": rig.blobs.put(data),
                        "size": len(data),
                        "media_type": "text/plain",
                        "class": "judge",
                        "exec": prov,
                    },
                }
            ],
        )
        assert out["ok"], out
        ids[name] = out["results"][0]["id"]
    assert h.call("show", {"artifact": ids["sealed"]})["code"] == "forbidden_op"
    assert h.call("show", {"artifact": ids["plain"]})["text"] == "judge output plain"


# ---------- 入参不合形状是 schema_error；本组件的缺陷不伪装成入参错误（审计 P1-4） ----------

JUNK = [None, True, 0, -3, 2.5, 10**30, "", "x", "a\x00b", "../../etc/passwd", [], [1, "a"], {}, {"k": [1]}, [[]]]


def test_malformed_tool_args_are_schema_errors_never_raise(rig):
    import random

    host = _host(rig)
    rng = random.Random(20261118)
    keys = [
        "op",
        "title",
        "summary",
        "claim_type",
        "premises",
        "grounds",
        "body_path",
        "check",
        "risk",
        "done",
        "budget_hint",
        "target",
        "candidate_path",
        "judge_id",
        "intent",
        "reason",
        "tmp_id",
        "needs_scope",
    ]
    kinds = ["add_fact", "add_intent", "abandon_intent", "claim_done", "request_judge", "nope", 3]
    codes = set()
    for _ in range(400):
        op = {k: rng.choice(JUNK) for k in rng.sample(keys, rng.randint(0, 6))}
        op["op"] = rng.choice(kinds)
        if rng.random() < 0.3:
            op["check"] = {k: rng.choice(JUNK) for k in rng.sample(["judge_id", "expect", "spec_path", "x"], 2)}
        if rng.random() < 0.3:
            op["done"] = {k: rng.choice(JUNK) for k in rng.sample(["judge_id", "max_attempts", "spec_path"], 2)}
        args = rng.choice(
            [
                {
                    "ops": [op],
                    "final": rng.choice(
                        [None, 3, {"outcome": rng.choice(JUNK[5:9] + ["nothing"]), "excluded_paths": rng.choice(JUNK)}]
                    ),
                },
                {"ops": rng.choice(JUNK)},
            ]
        )
        out = host.call("submit", args)
        for r in out.get("results", [out]):
            if r.get("ok") is False:
                codes.add(r["code"])
        out = host.call(
            "show", {k: rng.choice(JUNK) for k in rng.sample(["id", "artifact", "range", "list", "layer"], 2)}
        )
        assert isinstance(out, dict)
        out = host.call("exec", {k: rng.choice(JUNK) for k in rng.sample(["cmd", "timeout_s", "cwd"], 2)})
        assert isinstance(out, dict)
    assert "schema_error" in codes


def test_tool_host_defect_is_not_reported_as_schema_error(rig, capsys):
    """宿主内部的 KeyError（这里人为注入）不再变成给模型看的 schema_error；工具端点报内部错误并留栈。"""
    import pytest

    host = _host(rig)

    def broken(nid):
        raise KeyError("judge_snapshot")

    host._registered_judge = broken
    with pytest.raises(KeyError):
        host.call("submit", {"ops": [{"op": "request_judge", "target": "goal"}]})
    url = rig.endpoint.mount(host)
    path = "/" + url.split("/", 3)[3]
    st, out = rpc(
        rig.endpoint.base,
        path,
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "submit", "arguments": {"ops": [{"op": "request_judge", "target": "goal", "x": 1}]}},
        },
    )
    assert st == 200 and out["error"]["code"] == -32603 and "KeyError" in out["error"]["message"]
    assert "Traceback" in capsys.readouterr().err


def test_add_fact_carries_a_control_from_workspace_files(rig):
    """对照判据（§3.3.3）：control.input_paths 里的工作区文件登记为 authored 类，填进 check.control.inputs。"""
    h = _host(rig)
    ground = h.call("exec", {"cmd": "uname"})["artifact"]
    (h.s.workspace / "probe.sh").write_text("probe $(cat /workspace/inputs/1 2>/dev/null)\n")
    (h.s.workspace / "bogus.txt").write_text("target=bogus\n")
    op = {
        "op": "add_fact",
        "claim_type": "observation",
        "title": "目标在线",
        "check": {
            "judge_id": "replay",
            "spec_path": "probe.sh",
            "expect": {},
            "control": {"input_paths": ["bogus.txt"]},
        },
        "premises": [],
        "grounds": [ground],
    }
    out = h.call("submit", {"ops": [op]})
    assert out["results"][0]["ok"], out
    f = rig.graph.state["facts"][out["results"][0]["id"]]
    [inp] = f["check"]["control"]["inputs"]
    a = rig.graph.state["artifacts"][inp]
    assert a["class"] == "authored" and rig.blobs.get(a["hash"]) == b"target=bogus\n"
    bad = {**op, "check": {**op["check"], "control": {"paths": ["bogus.txt"]}}}
    assert h.call("submit", {"ops": [bad]})["results"][0]["code"] == "schema_error"
