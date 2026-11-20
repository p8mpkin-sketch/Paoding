"""开放道的求解会话（docs/design/open-lane/ §3.2–§3.4）：一个会话做到底，用 deliver 交付；接力；凭据不上卡。

假 CLI 走真的代理、真的工具端点、真的图服务；执行层是进程内替身（adapter_rig.FakeExec）。
"""

import dataclasses
import hashlib

from adapter_rig import Rig, graph, upstream  # noqa: F401  fixture

from paoding_adapter import creds
from paoding_graph.contract import seen_card

EXEC, DELIVER, ACCESS = "mcp__paoding__exec", "mcp__paoding__deliver", "mcp__paoding__request_access"
TOKEN = "ghp_Q7wErTy9UiOp1234aSdF"
STATEMENT = f"用我的令牌 token: {TOKEN} 查一下 api.repo.test:443 上我有几个仓库。"


def open_lane(g, pid="p1", statement=STATEMENT):
    st = statement.encode()
    out = g.submit(
        "tok-human",
        pid,
        f"open-{pid}",
        [
            {
                "op": "register_artifact",
                "body": {
                    "hash": hashlib.sha256(st).hexdigest(),
                    "size": len(st),
                    "media_type": "text/plain",
                    "class": "input",
                },
            },
            {
                "op": "open_problem",
                "body": {
                    "title": "数仓库",
                    "origin": {"statement_ref": "$0", "materials": []},
                    "goal": {"statement": statement, "accept": "open"},
                    "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
                    "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
                    "env": {"base": "basic", "baseline_ref": "base@1"},
                    "judges": [],
                },
            },
        ],
    )
    assert out["ok"], out


def lease_solve(g, pid="p1", key="s"):
    out = g.submit(
        "tok-sinan",
        pid,
        f"lease-{key}",
        [
            {
                "op": "lease",
                "body": {"kind": "solve", "holder": "sn1", "reserve": {"usd_milli": 2000, "wall_s": 600}, "ttl_s": 600},
            }
        ],
    )
    assert out["ok"], out
    return out["results"][0]["id"]


def make(tmp_path, graph, upstream, statement=STATEMENT):  # noqa: F811
    r = Rig(tmp_path, graph, upstream)
    r.statement = statement
    open_lane(graph, statement=statement)
    return r


def terminal(g, pid="p1"):
    """人关题后图服务算出的终态（开放道：有回答或部分完成即 delivered，只有受阻是 unsolved）。"""
    out = g.submit("tok-human", pid, f"close-{pid}", [{"op": "close_problem", "body": {}}])
    assert out["ok"], out
    return g.state["problems"][pid]["terminal"]


def results(rec):
    return [c for e in rec.events if e["type"] == "user" for c in e["message"]["content"]]


def test_solve_runs_to_a_delivery_with_exec_evidence(tmp_path, graph, upstream):  # noqa: F811
    rig = make(tmp_path, graph, upstream, "算一下 6 乘 7。")
    try:
        lid = lease_solve(graph)
        rig.script(
            [
                {"tool": "Write", "input": {"file_path": "NOTES.md", "content": "计划：乘一下\n"}},
                {"tool": EXEC, "input": {"cmd": "python -c 'print(6*7)'"}},
                {
                    "tool": DELIVER,
                    "input": {
                        "outcome": "answered",
                        "answer": "42",
                        "claims": [{"text": "6×7=42", "refs": ["$r1.artifact"]}, {"text": "常识，没跑"}],
                        "self_check": [{"what": "重跑一次", "result": "pass", "refs": ["$r1.artifact"]}],
                    },
                },
            ]
        )
        rec = rig.run(lid)
        assert rec.status == "released" and rec.release["outcome"] == "done", rec.release
        p = graph.state["problems"]["p1"]
        (d,) = p["deliveries"]
        assert d["outcome"] == "answered" and d["lease"] == lid
        assert graph.state["artifacts"][d["answer"]]["class"] == "authored"
        assert graph.state["artifacts"][d["claims"][0]["refs"][0]]["class"] == "exec"
        assert d["claims"][1]["refs"] == []  # 没有依据的主张允许存在，读端标“无留档支撑”
        assert graph.work("p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]
        assert terminal(graph) == "delivered"
    finally:
        rig.close()


def test_own_writing_is_not_evidence(tmp_path, graph, upstream):  # noqa: F811
    """部分交付不作假：会话自己写的东西（authored）不能当主张的依据，内核拒，会话收到原因；人给的材料可以。"""
    rig = make(tmp_path, graph, upstream, "找出原因。")
    try:
        lid = lease_solve(graph)
        aid = rig.put_input(b"x")  # 人给的材料（input 类）可以当依据
        rig.script(
            [
                {"tool": "Write", "input": {"file_path": "mine.txt", "content": "我觉得是配置"}},
                {
                    "tool": DELIVER,
                    "input": {
                        "outcome": "partial",
                        "answer_path": "mine.txt",
                        "claims": [{"text": "配置错了", "refs": [aid]}],
                    },
                },
                {  # 拿自己那份答案当另一条主张的依据：不收
                    "tool": DELIVER,
                    "input": {
                        "outcome": "answered",
                        "answer": "是配置",
                        "claims": [{"text": "见上次答案", "refs": ["$r1.answer"]}],
                    },
                },
            ]
        )
        rec = rig.run(lid)
        assert rec.release["outcome"] == "done"
        (d,) = graph.state["problems"]["p1"]["deliveries"]
        assert d["claims"][0]["refs"] == [aid] and d["outcome"] == "partial"
        assert graph.state["artifacts"][d["answer"]]["class"] == "authored"
        assert "inadmissible_class" in str(results(rec))
        assert terminal(graph) == "delivered"  # 部分完成也算交付，但界面写“部分完成”
    finally:
        rig.close()


def test_blocked_must_say_what_it_needs(tmp_path, graph, upstream):  # noqa: F811
    """受阻诚实收尾：不写需要人提供什么就不收；写了就收，任务转人（why=blocked），关题终态是 unsolved。"""
    rig = make(tmp_path, graph, upstream, "登录内网看报表。")
    try:
        lid = lease_solve(graph)
        rig.script(
            [
                {"tool": DELIVER, "input": {"outcome": "blocked", "unverified": ["报表内容"]}},
                {
                    "tool": DELIVER,
                    "input": {"outcome": "blocked", "needs": ["内网地址与访问批准"], "unverified": ["报表内容"]},
                },
            ]
        )
        rec = rig.run(lid)
        out = results(rec)
        assert any("needs" in str(c) and "schema_error" in str(c) for c in out)
        (d,) = graph.state["problems"]["p1"]["deliveries"]
        assert d["outcome"] == "blocked" and "answer" not in d and d["needs"] == ["内网地址与访问批准"]
        assert graph.work("p1") == [{"kind": "human", "target": "p1", "why": "blocked"}]
        assert terminal(graph) == "unsolved"  # 只有受阻的交付：不算已交付
    finally:
        rig.close()


def test_relay_carries_the_workspace(tmp_path, graph, upstream):  # noqa: F811
    """没交付就结束的会话：下一个求解会话从它的工作区（含 NOTES.md）接着做。"""
    rig = make(tmp_path, graph, upstream, "写一份长报告。")
    try:
        lid = lease_solve(graph)
        rig.script([{"tool": "Write", "input": {"file_path": "NOTES.md", "content": "做到第 3 节\n"}}])
        rec = rig.run(lid)
        assert rec.release["outcome"] == "nothing" and not graph.state["problems"]["p1"].get("deliveries")
        assert graph.work("p1") == [{"kind": "solve"}]
        lid2 = lease_solve(graph, key="s2")
        rig.script([{"tool": "Read", "input": {"file_path": "NOTES.md"}}])
        rec2 = rig.run(lid2)
        assert "做到第 3 节" in str(results(rec2))
    finally:
        rig.close()


def test_credential_never_reaches_the_card_or_the_delivery(tmp_path, graph, upstream):  # noqa: F811
    """正文带凭据（裁决附加条件 3）：扩权申请的理由里出现凭据就遮盖后再送审，地址里带凭据直接不收；交付里也遮。"""
    assert creds.found(STATEMENT) == (TOKEN,)
    rig = make(tmp_path, graph, upstream)
    rig.cfg.grants_runtime = lambda: True  # 运行时扩权开着（设置层缺省）才有 request_access
    graph.cfg = dataclasses.replace(graph.cfg, grants_runtime=True)
    try:
        lid = lease_solve(graph)
        rig.script(
            [
                {"tool": ACCESS, "input": {"target": f"{TOKEN}@api.repo.test:443", "why": "查仓库"}},
                {"tool": ACCESS, "input": {"target": "api.repo.test:443", "why": f"用 {TOKEN} 调接口数仓库"}},
                {
                    "tool": DELIVER,
                    "input": {
                        "outcome": "blocked",
                        "needs": [f"批准 api.repo.test:443（我会带上 {TOKEN}）"],
                        "unverified": ["仓库数"],
                    },
                },
            ]
        )
        rec = rig.run(lid)
        out = str(results(rec))
        assert "target 里带着原话里的凭据" in out
        st = graph.state
        (req,) = st["scope_requests"].values()
        assert TOKEN not in req["why"] and creds.MASK in req["why"]
        assert req["rules"][0]["pattern"] == "api.repo.test:443"
        (d,) = st["problems"]["p1"]["deliveries"]
        assert TOKEN not in str(d) and creds.MASK in d["needs"][0]
        # 开题零出站：没批之前范围里只有工作区
        assert [r["resource"] for r in st["problems"]["p1"]["scope"]] == ["workspace"]
        # 扩权卡（人审批时看的那张）与写进事件账的申请、交付里都没有凭据。任务包与会话记录照实留着原话
        # （模型要拿原话里的凭据去用），它们不上卡、不出站
        assert TOKEN not in str(seen_card(st, "p1", "scope", req["id"]))
        evs = [e for e in graph.events("p1") if e["kind"] in ("request_scope", "deliver")]
        assert len(evs) == 2 and TOKEN not in str(evs)
    finally:
        rig.close()


def test_credential_shapes():
    t = "密码：hunter2pass，api_key=sk-abcdefghijklmnop，地址 https://bob:s3cretpw@h.test/x，Bearer abcdefgh12345"
    got = set(creds.found(t))
    assert {"hunter2pass", "sk-abcdefghijklmnop", "s3cretpw", "abcdefgh12345"} <= got
    assert creds.found("帮我调研一下主流的智能体框架。") == ()
    assert creds.mask("x sk-abcdefghijklmnop y", ("sk-abcdefghijklmnop",)) == (f"x {creds.MASK} y", True)


def test_closing_round_asks_for_a_delivery_before_relaying(tmp_path, graph, upstream):  # noqa: F811
    """没交付就要结束：收尾轮先请它交付（做到哪交到哪）或留好笔记接力；这里它交了部分完成。"""
    rig = make(tmp_path, graph, upstream, "写一份长报告。")
    try:
        lid = lease_solve(graph)
        rig.script(
            [{"tool": "Write", "input": {"file_path": "report.md", "content": "第 1 节\n"}}],
            resume_steps=[
                {
                    "tool": DELIVER,
                    "input": {"outcome": "partial", "answer_path": "report.md", "unverified": ["第 2、3 节没写"]},
                }
            ],
        )
        rec = rig.run(lid)
        assert rec.release["outcome"] == "done"
        (d,) = graph.state["problems"]["p1"]["deliveries"]
        assert d["outcome"] == "partial" and d["unverified"] == ["第 2、3 节没写"]
    finally:
        rig.close()


def test_open_brief_carries_follow_ups_and_the_last_delivery():
    """追问之后的一轮（地图 Q31）：简报里有上一轮交付的结局与未验证项、人的追问全文（最后一条是这一轮的）。"""
    from paoding_adapter.package import open_brief

    p = {
        "title": "t",
        "origin": {"statement_ref": "a_1", "materials": []},
        "goal": {"statement": "查清楚 X", "accept": "open"},
        "scope": [],
        "deliveries": [
            {"id": "d_5", "seq": 5, "outcome": "partial", "answer": "a_4", "unverified": ["第二来源"], "needs": []}
        ],
        "follow_ups": [{"id": "u_7", "seq": 7, "text": "把第二来源也核对一下", "after_delivery": "d_5"}],
    }
    brief = open_brief({"problems": {"p1": p}}, "p1", "原话")
    assert "人的追问" in brief and "- 把第二来源也核对一下" in brief
    assert '"outcome":"partial"' in brief.replace(" ", "") and "第二来源" in brief
    p.pop("follow_ups")
    assert "人的追问" not in open_brief({"problems": {"p1": p}}, "p1", "原话")  # 没有追问时与旧版一致
