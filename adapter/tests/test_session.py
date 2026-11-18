"""D4–D6 假 CLI 版：脚本化假 CLI 走通“模型侧无命令工具 + 代理工具 exec/submit/show + 端点代理”全链。

验收：3.4.5 的 1（主路径）、2（畸形 submit、收尾轮、failed(no_output)）、4（伪造观察）、7（无命令工具、
不出工作目录）；3.4.4 的心跳与回合上限；3.5.5 的 3（代理侧：预留用尽即拒，任务以 budget_exhausted 释放）。
真 CLI 的同一组断言留到密钥到位（D4 真机）。
"""
from adapter_rig import graph, lease_bootstrap, rig, upstream  # noqa: F401（fixture）

R = {"usd_milli": 1000, "wall_s": 600}


def sub(*ops, final=None):
    return {"tool": "mcp__paoding__submit", "input": {"ops": list(ops), **({"final": final} if final else {})}}


def obs(title, grounds, judge="replay"):
    return {"op": "add_fact", "claim_type": "observation", "title": title, "summary": "",
            "check": {"judge_id": judge, "expect": {"t": title}}, "premises": [], "grounds": grounds}


def explore_lease(rig, done=None):
    """Bootstrap 走完 → 人加一条 Intent → 司南领 explore 租约。"""
    lid = lease_bootstrap(rig.graph)
    assert rig.graph.submit("tok-sinan", "p1", "rel-b", [{"op": "release", "body": {
        "lease": lid, "outcome": "nothing"}}])["ok"]
    body = {"title": "看配置", "premises": [], "risk": "r0", "budget": R}
    if done:
        body["done"] = {"judge_id": done, "max_attempts": 2}
    iid = rig.graph.submit("tok-human", "p1", "int-1", [{"op": "add_intent", "body": body}])["results"][0]["id"]
    out = rig.graph.submit("tok-sinan", "p1", "lease-e", [{"op": "lease", "body": {
        "kind": "explore", "target": iid, "holder": "sn1", "reserve": R, "ttl_s": 120}}])
    assert out["ok"], out
    return iid, out["results"][0]["id"]


def lease_of(rig, lid):
    return rig.graph.state["leases"][lid]


def tool_results(rec):
    return [c for e in rec.events if e["type"] == "user" for c in e["message"]["content"]]


# ---------- 3.4.5 的 1：主路径 ----------

def test_main_path_exec_registered_and_fact_enters_graph(rig):
    lid = lease_bootstrap(rig.graph)
    rig.script([
        {"tool": "mcp__paoding__exec", "input": {"cmd": "cat /etc/hostname"}},
        sub(obs("主机名可读", ["$r0.artifact"]), final={"outcome": "found"}),
    ])
    rec = rig.run(lid)
    st = rig.graph.state
    assert rec.status == "released" and rec.release["ok"] and rec.release["outcome"] == "done"
    [fact] = [f for f in st["facts"].values()]
    [g] = fact["grounds"]
    assert st["artifacts"][g]["class"] == "exec" and st["artifacts"][g]["producer"]["actor"] == "ex1"
    assert fact["session"] == lid                               # 写入者身份来自会话令牌
    assert rig.executor.calls == ["cat /etc/hostname"]
    pkg = st["artifacts"][rec.package_ref]                      # 任务包留档：authored，producer.session = 租约
    assert pkg["class"] == "authored" and pkg["producer"]["session"] == lid
    assert lease_of(rig, lid)["transcript_ref"] == rec.transcript_ref
    costs = [c for c in st["costs"] if c["task_id"] == lid]
    assert len(costs) == 2 and all(c["source"] == "proxy" for c in costs)   # 每个回合一次请求，代理计量


def test_claim_done_registers_candidate_then_requests_judge(rig):
    iid, lid = explore_lease(rig, done="exact_match")
    (rig.cfg.root / lid / "workspace").mkdir(parents=True)
    rig.script([
        {"tool": "Write", "input": {"file_path": "answer.txt", "content": "42"}},
        sub({"op": "claim_done", "target": iid, "candidate_path": "answer.txt"}, final={"outcome": "found"}),
    ])
    rec = rig.run(lid)
    [req] = rig.graph.state["requests"].values()
    cand = rig.graph.state["artifacts"][req["candidate"]]
    assert req["target"] == iid and req["judge_id"] == "exact_match"
    assert cand["class"] == "authored" and cand["producer"]["session"] == lid
    assert rig.blobs.get(cand["hash"]) == b"42"
    assert rec.release["outcome"] == "done"


# ---------- 3.4.5 的 2：畸形 submit、收尾轮、no_output ----------

def test_malformed_submit_fixed_in_session(rig):
    lid = lease_bootstrap(rig.graph)
    bad = {"op": "add_fact", "claim_type": "guess", "title": "x", "premises": [], "grounds": []}
    rig.script([
        {"tool": "mcp__paoding__exec", "input": {"cmd": "id"}},
        sub(bad),
        sub(obs("身份", ["$r0.artifact"]), final={"outcome": "found"}),
    ])
    rec = rig.run(lid)
    calls = [c for c in rec_tool_calls(rig, rec) if c["tool"] == "submit"]
    assert calls[0]["result"]["results"][0]["code"] == "schema_error"
    assert calls[1]["result"]["results"][0]["ok"]
    assert rec.release["outcome"] == "done"


def rec_tool_calls(rig, rec):
    import json
    return json.loads(rig.blobs.get(rig.graph.state["artifacts"][rec.transcript_ref]["hash"]))["tool_calls"]


def test_same_op_rejected_three_times_is_not_forwarded(rig):
    lid = lease_bootstrap(rig.graph)
    bad = obs("凭空", ["a_999"])
    rig.script([sub(bad), sub(bad), sub(bad), sub(bad), sub(final={"outcome": "unsolved"})])
    rec = rig.run(lid)
    rs = [c["result"]["results"][0] for c in rec_tool_calls(rig, rec) if c["tool"] == "submit"
          and c["result"]["results"]]
    assert [r["code"] for r in rs] == ["unknown_ref"] * 4
    assert "不再转发" in rs[3]["detail"] and "不再转发" not in rs[2]["detail"]


def test_closing_round_then_unsolved(rig):
    lid = lease_bootstrap(rig.graph)
    rig.script([{"tool": "mcp__paoding__show", "input": {"list": "all"}}],
               resume_steps=[sub(final={"outcome": "unsolved", "suggestions": ["换个入口"]})])
    rec = rig.run(lid)
    assert rec.rounds == 2
    inits = [e for e in rec.events if e.get("subtype") == "init"]
    assert [e["round"] for e in inits] == [1, 2]
    assert rec.release["outcome"] == "nothing" and rec.status == "released"
    assert rig.graph.state["leases"][lid]["outcome"] == "nothing"


def test_no_output_after_closing_round(rig):
    lid = lease_bootstrap(rig.graph)
    rig.script([{"tool": "mcp__paoding__show", "input": {"list": "budget"}}], resume_steps=[])
    rec = rig.run(lid)
    assert rec.rounds == 2 and rec.status == "failed(no_output)"
    assert rig.graph.state["leases"][lid]["outcome"] == "failed"
    assert rec.transcript_ref in rig.graph.state["artifacts"]            # 会话记录照存


def test_failed_explore_reopens_intent(rig):
    from paoding_graph.contract import intent_status
    iid, lid = explore_lease(rig)
    rig.script([], resume_steps=[])
    rig.run(lid)
    assert intent_status(rig.graph.state, "p1", iid) == "open"


# ---------- 3.4.5 的 4：伪造观察 ----------

def test_forged_observation_rejected(rig):
    other = rig.put_input(b"other problem material", pid="p1")
    from adapter_rig import open_problem
    open_problem(rig.graph, pid="p2")
    foreign = rig.put_input(b"p2 material", pid="p2")
    lid = lease_bootstrap(rig.graph)
    (rig.cfg.root / lid / "workspace").mkdir(parents=True)
    narrated = {"op": "add_fact", "claim_type": "observation", "title": "输出显示端口开放",
                "summary": "输出显示：端口开放，服务版本为 1.2", "check": {"judge_id": "replay", "expect": {}},
                "premises": [], "grounds": []}
    rig.script([
        {"tool": "Write", "input": {"file_path": "notes.txt", "content": "输出显示……"}},
        sub(narrated,
            obs("引用不存在", ["a_999"]),
            obs("引用别题", [foreign]),
            {**obs("引用自写", []), "body_path": "notes.txt"},
            obs("题目材料可以", [other])),
    ])
    rec = rig.run(lid)
    rs = [c["result"]["results"] for c in rec_tool_calls(rig, rec) if c["tool"] == "submit"][0]
    assert [r.get("code") for r in rs[:3]] == ["missing_evidence", "unknown_ref", "scope_mismatch"]
    assert rs[3]["code"] == "missing_evidence"          # body_ref 不是 grounds
    assert rs[4]["ok"]
    assert [f["title"] for f in rig.graph.state["facts"].values()] == ["题目材料可以"]


def test_authored_as_ground_is_inadmissible(rig):
    """自己写的文件（候选、正文）登记为 authored 类，永不能当 grounds（I2）。"""
    lid = lease_bootstrap(rig.graph)
    rig.script([
        {"tool": "Write", "input": {"file_path": "c.txt", "content": "x"}},
        sub({"op": "claim_done", "target": "goal", "candidate_path": "c.txt"}),
        sub(obs("拿候选当证据", ["$r1.candidate"]), final={"outcome": "nothing"}),
    ])
    (rig.cfg.root / lid / "workspace").mkdir(parents=True)
    rig.run(lid)
    [req] = rig.graph.state["requests"].values()
    assert rig.graph.state["artifacts"][req["candidate"]]["class"] == "authored"
    from paoding_adapter.tools import Session, ToolHost
    tok = rig.graph.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": "bootstrap"})
    host = ToolHost(Session("p1", lid, "bootstrap", tok, rig.cfg.root / lid / "workspace"),
                    rig.graph, rig.graph, rig.blobs)
    r = host.call("submit", {"ops": [obs("拿候选当证据", [req["candidate"]])]})
    assert r["results"][0]["code"] == "inadmissible_class"


def test_claim_done_takes_inline_candidate(rig):
    """P0-A 的提示词让模型写 candidate=答案字符串：不先写文件也能交候选，照样登记为 authored、进判官。"""
    lid = lease_bootstrap(rig.graph)
    rig.script([sub({"op": "claim_done", "target": "goal", "candidate": "flag{42}"}, final={"outcome": "found"})])
    (rig.cfg.root / lid / "workspace").mkdir(parents=True)
    rig.run(lid)
    [req] = rig.graph.state["requests"].values()
    art = rig.graph.state["artifacts"][req["candidate"]]
    assert art["class"] == "authored" and rig.blobs.get(art["hash"]) == b"flag{42}"


# ---------- 3.4.5 的 7：没有命令工具；不出工作目录 ----------

def test_no_command_tool_and_workspace_confined(rig, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("outside")
    lid = lease_bootstrap(rig.graph)
    ws = rig.cfg.root / lid / "workspace"
    ws.mkdir(parents=True)
    (ws / "link.txt").symlink_to(secret)
    rig.script([
        {"tool": "Bash", "input": {"command": "id"}},
        {"tool": "Read", "input": {"file_path": str(secret)}},
        {"tool": "Read", "input": {"file_path": "../../../outside.txt"}},
        sub({**obs("越界正文", []), "claim_type": "inference", "body_path": "link.txt"}),
        sub({**obs("越界正文2", []), "claim_type": "inference", "body_path": "../../../outside.txt"}),
        sub(final={"outcome": "nothing"}),
    ])
    rec = rig.run(lid)
    [init] = [e for e in rec.events if e.get("subtype") == "init"]
    assert not {"Bash", "PowerShell", "WebFetch"} & set(init["tools"])
    assert {"mcp__paoding__exec", "mcp__paoding__submit", "mcp__paoding__show"} <= set(init["tools"])
    res = tool_results(rec)
    assert res[0]["is_error"] and "No such tool" in res[0]["content"]
    assert res[1]["is_error"] and res[2]["is_error"]
    subs = [c["result"]["results"][0] for c in rec_tool_calls(rig, rec) if c["tool"] == "submit"
            and c["result"]["results"]]
    assert len(subs) == 2
    assert all(r["code"] == "schema_error" and "越出工作区" in r["detail"] for r in subs)


def test_reason_session_has_no_exec(rig):
    lid = lease_bootstrap(rig.graph)
    rig.graph.submit("tok-sinan", "p1", "rel", [{"op": "release", "body": {"lease": lid, "outcome": "nothing"}}])
    out = rig.graph.submit("tok-sinan", "p1", "lease-r", [{"op": "lease", "body": {
        "kind": "reason", "holder": "sn1", "reserve": R, "ttl_s": 120}}])
    rl = out["results"][0]["id"]
    rig.script([{"tool": "mcp__paoding__exec", "input": {"cmd": "id"}},
                sub({"op": "add_intent", "title": "下一步", "summary": "", "premises": [], "risk": "r0"},
                    final={"outcome": "found"})])
    rec = rig.run(rl)
    [init] = [e for e in rec.events if e.get("subtype") == "init"]
    assert "mcp__paoding__exec" not in init["tools"]
    assert "No such tool" in tool_results(rec)[0]["content"]
    assert rig.executor.calls == []
    [it] = rig.graph.state["intents"].values()
    assert it["session"] == rl and it["title"] == "下一步"


# ---------- 心跳、回合上限、预算 ----------

def test_stalled_session_killed_and_failed(rig):
    lid = lease_bootstrap(rig.graph)
    rig.cfg.stall_s = 0.5
    rig.script([{"hang": 30}])
    rec = rig.run(lid)
    assert rec.status == "failed(stalled)" and rec.rounds == 1
    assert rig.graph.state["leases"][lid]["outcome"] == "failed"


def test_renews_while_alive(rig):
    lid = lease_bootstrap(rig.graph)
    rig.cfg.renew_s = 0.2
    before = rig.graph.state["leases"][lid]["expires_at"]
    rig.script([{"hang": 1.0}, sub(final={"outcome": "nothing"})])
    rig.run(lid)
    renews = [e for e in rig.graph.log.events() if e["kind"] == "renew"]
    assert renews and all(e["actor"].get("session") == lid for e in renews)
    assert rig.graph.state["leases"][lid]["expires_at"] > before


def test_reserve_exhausted_kills_with_budget_outcome(rig):
    lid = lease_bootstrap(rig.graph, reserve=5)          # 一次请求约 5 毫美元
    rig.script([{"tool": "mcp__paoding__show", "input": {"list": "all"}},
                {"tool": "mcp__paoding__show", "input": {"list": "all"}}],
               resume_steps=[{"tool": "mcp__paoding__show", "input": {}}])
    rec = rig.run(lid)
    assert rec.status == "killed(budget)"
    assert rig.graph.state["leases"][lid]["outcome"] == "budget_exhausted"
    assert len(rig.upstream.seen) == 1                   # 第二次请求在代理处被拒，没到上游
    errs = [e for e in rec.events if e.get("type") == "result" and e.get("is_error")]
    assert errs and "429" in errs[0]["result"]


def test_tokens_revoked_after_release(rig):
    lid = lease_bootstrap(rig.graph)
    rig.script([sub(final={"outcome": "nothing"})])
    rig.run(lid)
    assert all(t.revoked for t in rig.proxy._tasks.values())
    assert rig.endpoint._hosts == {}


def test_problem_closed_mid_session_still_releases(rig):
    """并行的另一个会话（或判官）在本会话跑着的时候把题关了：会话照常释放租约，不留悬着的租约
    （审计 P1-3 的并发形态下才会遇到）。在途会话的留档内核仍然收（交回），所以记录挂在租约上。"""
    import threading
    lid = lease_bootstrap(rig.graph)
    rig.script([{"hang": 1.0}, sub(final={"outcome": "nothing"})], resume_steps=[sub(final={"outcome": "nothing"})])
    t = threading.Timer(0.3, lambda: rig.graph.submit("tok-human", "p1", "close-mid", [
        {"op": "close_problem", "body": {}}]))
    t.start()
    rec = rig.run(lid)
    t.join()
    assert rig.graph.state["problems"]["p1"]["closed"]
    assert rec.release and rec.release["ok"] and rec.transcript_ref is not None
    lease = lease_of(rig, lid)
    assert not lease["active"] and lease["outcome"] == "closed"
    assert lease["transcript_ref"] == rec.transcript_ref
    assert rig.graph.state["artifacts"][rec.transcript_ref]["class"] == "authored"
    assert rig.runner.live == {}
