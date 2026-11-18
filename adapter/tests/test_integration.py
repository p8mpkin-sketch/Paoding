"""adapter 集成：假 CLI 经端点代理与工具端点，落到真的执行层（Docker）与真的图服务。全程没有真模型、没有真密钥。

验收：3.4.5 的 1（exec 的输出由执行层在容器外采集登记，submit 的论断进图）、7（会话没有命令工具）；
3.5.5 的 3（预算穿透：执行容器里没有密钥、连不到模型端点；任务结束后容器已销毁、任务令牌作废）；
3.6.4 的 2（r0 Intent 的容器里没有 r1 规则放行的通路）、4（执行容器一侧）；8 KB 回显截断与 show 按区间读全文。
"""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from adapter_rig import (FETCH, PROBE, docker_ok, drig, graph, lease_bootstrap, open_net_problem,  # noqa: F401
                         upstream)

pytestmark = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")
R = {"usd_milli": 1000, "wall_s": 600}
EXEC, SUBMIT, SHOW = "mcp__paoding__exec", "mcp__paoding__submit", "mcp__paoding__show"


def sub(*ops, final=None):
    return {"tool": SUBMIT, "input": {"ops": list(ops), **({"final": final} if final else {})}}


def obs(title, grounds, **check):
    return {"op": "add_fact", "claim_type": "observation", "title": title, "summary": "",
            "check": {"judge_id": "replay", "expect": {"exit_code": 0}, **check}, "premises": [], "grounds": grounds}


def results(rec):
    return [json.loads(c["content"]) if c["content"].startswith("{") else c["content"]
            for e in rec.events if e["type"] == "user" for c in e["message"]["content"]]


def explore(drig, pid, risk="r0", approve=False):
    lid = lease_bootstrap(drig.graph, pid)
    assert drig.graph.submit("tok-sinan", pid, "rel-b", [{"op": "release", "body": {"lease": lid, "outcome": "nothing"}}])["ok"]
    iid = drig.graph.submit("tok-human", pid, "int-1", [{"op": "add_intent", "body": {
        "title": "取值", "premises": [], "risk": risk, "budget": R}}])["results"][0]["id"]
    if approve:
        assert drig.graph.submit("tok-human", pid, "ap-1", [{"op": "approve", "body": {"intent": iid, "decision": "approve"}}])["ok"]
    out = drig.graph.submit("tok-sinan", pid, "lease-e", [{"op": "lease", "body": {
        "kind": "explore", "target": iid, "holder": "sn1", "reserve": R, "ttl_s": 120}}])
    assert out["ok"], out
    return iid, out["results"][0]["id"]


def test_main_path_real_collection_and_teardown(drig):
    """3.4.5 的 1：命令在执行容器里跑，输出由执行层在容器外采集并用自己的令牌登记；论断引用它进图。"""
    t = drig.target({"value": "v-1234", "index": "hello"})
    open_net_problem(drig.graph, "p2", [(t, "r0")])
    lid = lease_bootstrap(drig.graph, "p2")
    drig.script_for("bootstrap", [
        {"tool": EXEC, "input": {"cmd": FETCH.format(host=t, path="index")}},
        sub(obs("目标可达，首页有内容", ["$r0.artifact"]), final={"outcome": "found"}),
    ])
    seen = []
    orig = drig.executor.exec
    drig.executor.exec = lambda *a, **k: (seen.append(drig.sandboxes()), orig(*a, **k))[1]
    rec = drig.run(lid, "p2")
    st = drig.graph.state
    assert rec.status == "released" and rec.release == {"outcome": "done", "ok": True, "results": rec.release["results"]}
    assert len(seen) == 1 and len(seen[0]) == 1                  # 会话期间恰好一个沙箱
    assert drig.sandboxes() == [] and drig.executor.sandboxes() == []   # 任务结束后容器已销毁（3.5.5 的 3）
    r0 = results(rec)[0]
    assert r0["exit_code"] == 0 and r0["output"] == "hello\n" and r0["truncated"] is False
    art = st["artifacts"][r0["artifact"]]
    assert art["class"] == "exec" and art["producer"] == {"actor": "ex1"}      # 登记方是执行层，不是会话
    assert art["exec"]["command"] == FETCH.format(host=t, path="index") and art["exec"]["exit_code"] == 0
    assert art["exec"]["base"] == "python:3.12-slim" and art["exec"]["sandbox_id"] == seen[0][0]
    assert drig.blobs.get(art["hash"]) == b"hello\n"
    [fact] = st["facts"].values()
    assert fact["grounds"] == [r0["artifact"]] and fact["session"] == lid
    costs = [c for c in st["costs"] if c["task_id"] == lid]
    assert len(costs) == 2 and all(c["source"] == "proxy" for c in costs)


def test_budget_penetration_from_exec_container(drig, upstream):  # noqa: F811
    """3.5.5 的 3、3.6.4 的 4：执行容器里没有任何密钥，连不到端点代理、假上游与外网；任务结束后令牌作废。"""
    t = drig.target({"value": "v"})
    open_net_problem(drig.graph, "p2", [(t, "r0")])
    lid = lease_bootstrap(drig.graph, "p2")
    proxy_port = int(drig.proxy.url.rsplit(":", 1)[1])
    up_port = int(upstream.url.rsplit(":", 1)[1])
    drig.script_for("bootstrap", [
        {"tool": EXEC, "input": {"cmd": "env; cat /proc/1/environ | tr '\\0' '\\n'; ls -la /workspace /tmp"}},
        {"tool": EXEC, "input": {"cmd": PROBE.format(h="172.17.0.1", p=proxy_port)}},
        {"tool": EXEC, "input": {"cmd": PROBE.format(h="172.17.0.1", p=up_port)}},
        {"tool": EXEC, "input": {"cmd": PROBE.format(h="1.1.1.1", p=443)}},
        {"tool": EXEC, "input": {"cmd": PROBE.format(h=t, p=8080)}},
        sub(final={"outcome": "nothing"}),
    ])
    tokens = []
    orig = drig.proxy.register_task
    drig.proxy.register_task = lambda tok, *a, **k: (tokens.append(tok), orig(tok, *a, **k))[1]
    rec = drig.run(lid, "p2")
    env, proxy, up, internet, target = results(rec)[:5]
    assert all(w not in env["output"] for w in ("ANTHROPIC", "sk-fake-upstream", "tok-", "pdt-", tokens[0]))
    assert proxy["exit_code"] != 0 and up["exit_code"] != 0 and internet["exit_code"] != 0
    assert target["exit_code"] == 0                              # 只有授权范围内的目标连得上
    assert rec.status == "released" and drig.sandboxes() == []
    req = urllib.request.Request(drig.proxy.url + "/v1/messages", data=b'{"model":"m","messages":[]}', method="POST",
                                 headers={"x-api-key": tokens[0], "content-type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401                                   # 任务结束后令牌作废


def test_r0_intent_sandbox_has_no_r1_route(drig):
    """3.6.4 的 2：能力按风险注入。r0 Intent 的容器连不到 r1 规则放行的目标；r1 Intent 的容器连得到。"""
    a, b = drig.target({"value": "a"}), drig.target({"value": "b"})
    open_net_problem(drig.graph, "p2", [(a, "r0"), (b, "r1")])
    _, lid = explore(drig, "p2", "r0")
    steps = [{"tool": EXEC, "input": {"cmd": PROBE.format(h=a, p=8080)}},
             {"tool": EXEC, "input": {"cmd": PROBE.format(h=b, p=8080)}}, sub(final={"outcome": "nothing"})]
    drig.script_for("explore", steps)
    low = results(drig.run(lid, "p2"))
    assert low[0]["exit_code"] == 0 and low[1]["exit_code"] != 0
    open_net_problem(drig.graph, "p3", [(a, "r0"), (b, "r1")])
    _, lid = explore(drig, "p3", "r1")
    high = results(drig.run(lid, "p3"))
    assert high[0]["exit_code"] == 0 and high[1]["exit_code"] == 0


def test_reason_session_launches_no_sandbox(drig):
    t = drig.target({"value": "v"})
    open_net_problem(drig.graph, "p2", [(t, "r0")])
    lid = lease_bootstrap(drig.graph, "p2")
    drig.graph.submit("tok-sinan", "p2", "rel-b", [{"op": "release", "body": {"lease": lid, "outcome": "nothing"}}])
    out = drig.graph.submit("tok-sinan", "p2", "lease-r", [{"op": "lease", "body": {
        "kind": "reason", "holder": "sn1", "reserve": R, "ttl_s": 120}}])
    assert out["ok"], out
    launched = []
    orig = drig.executor.launch
    drig.executor.launch = lambda *a, **k: (launched.append(a), orig(*a, **k))[1]
    drig.script_for("reason", [
        {"tool": EXEC, "input": {"cmd": "id"}},                  # 3.4.5 的 7：reason 没有 exec
        {"tool": "Bash", "input": {"command": "id"}},            # 也没有任何内置命令工具
        sub({"op": "add_intent", "title": "取回 /value", "premises": [], "risk": "r0"}, final={"outcome": "found"}),
    ])
    rec = drig.run(out["results"][0]["id"], "p2")
    r = results(rec)
    assert "No such tool" in r[0] and "No such tool" in r[1]
    assert launched == [] and rec.status == "released"
    assert len(drig.graph.state["intents"]) == 1


def test_echo_truncated_full_text_via_show(drig):
    """§3.4.2：回显超过 8 KB 只回头尾，全文在 Blob 里，用 show 按区间读。"""
    t = drig.target({"value": "v"})
    open_net_problem(drig.graph, "p2", [(t, "r0")])
    lid = lease_bootstrap(drig.graph, "p2")
    drig.script_for("bootstrap", [
        {"tool": EXEC, "input": {"cmd": "python -c \"print('HEAD' + 'x'*30000 + 'TAIL')\""}},
        {"tool": SHOW, "input": {"artifact": "$r0.artifact", "range": [0, 8]}},
        {"tool": SHOW, "input": {"artifact": "$r0.artifact", "range": [30000, 30009]}},
        sub(final={"outcome": "nothing"}),
    ])
    ex, head, tail = results(drig.run(lid, "p2"))[:3]
    assert ex["truncated"] is True and len(ex["output"].encode()) < 8 * 1024 + 200
    assert ex["output"].startswith("HEAD") and ex["output"].rstrip().endswith("TAIL") and "省略" in ex["output"]
    assert head["text"] == "HEADxxxx" and head["size"] == 30009 and tail["text"] == "xxxxTAIL\n"


def test_kill_mid_session_destroys_sandbox_and_releases(drig):
    """3.5.5 的 4 的执行层一半：任务被叫停时进程树终止、执行容器销毁、租约释放、会话记录保存到被杀之前。"""
    t = drig.target({"value": "v"})
    open_net_problem(drig.graph, "p2", [(t, "r0")])
    lid = lease_bootstrap(drig.graph, "p2")
    drig.script_for("bootstrap", [{"tool": EXEC, "input": {"cmd": "echo started"}}, {"hang": 30}])
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("rec", drig.run(lid, "p2")))
    th.start()
    deadline = time.time() + 30
    while time.time() < deadline and not any(a["class"] == "exec" for a in drig.graph.state["artifacts"].values()):
        time.sleep(0.1)
    assert len(drig.sandboxes()) == 1
    drig.runner.kill(lid, "budget")
    th.join(30)
    rec = out["rec"]
    assert rec.status == "killed(budget)" and drig.sandboxes() == []
    lease = drig.graph.state["leases"][lid]
    assert not lease["active"] and lease["outcome"] == "budget_exhausted" and lease["transcript_ref"] == rec.transcript_ref
    transcript = json.loads(drig.blobs.get(drig.graph.state["artifacts"][rec.transcript_ref]["hash"]))
    assert transcript["tool_calls"][0]["result"]["output"] == "started\n"


def test_written_file_is_real_exec_record_but_says_what_it_read(drig):
    """3.2.5 的 2 第五种形态的前半：写假文件再读出，得到的确实是一条真 exec 记录，命令行如实写着读的是哪个文件；
    它不在洁净环境里（重放失败见 judgebox 的测试）。自己写的文件直接当证据则被拒。"""
    t = drig.target({"value": "v"})
    open_net_problem(drig.graph, "p2", [(t, "r0")])
    lid = lease_bootstrap(drig.graph, "p2")
    drig.script_for("bootstrap", [
        {"tool": "Write", "input": {"file_path": "proof.txt", "content": "value=forged"}},
        {"tool": EXEC, "input": {"cmd": "cat /workspace/proof.txt"}},
        sub({"op": "add_fact", "claim_type": "observation", "title": "输出显示取值为 forged", "summary": "",
             "check": {"judge_id": "replay", "expect": {"stdout_contains": "forged"}, "spec_path": "proof.txt"},
             "premises": [], "grounds": []}),
        sub(obs("读到了取值", ["$r1.artifact"]), final={"outcome": "found"}),
    ])
    r = results(drig.run(lid, "p2"))
    assert r[1]["output"] == "value=forged"
    assert r[2]["results"][0]["code"] == "missing_evidence"      # 没有可采信的证据根
    assert r[3]["results"][0]["ok"]
    art = drig.graph.state["artifacts"][r[1]["artifact"]]
    assert art["exec"]["command"] == "cat /workspace/proof.txt" and art["class"] == "exec"
