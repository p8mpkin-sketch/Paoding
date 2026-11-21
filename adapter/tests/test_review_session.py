"""开放道的复核会话（地图 Q34；open-lane §3.6；体质修炼 002 之后的功法 h1.review）。

假 CLI 走真的代理、真的工具端点、真的图服务。复核会话：拿到交付全文的任务包，工作区是求解会话的副本，
用 exec 重跑、用 review 交回读数；读数不改终态。没交回读数就收尾一轮，再没有就记 nothing，不重派。
"""

import dataclasses

from adapter_rig import Rig, graph, upstream  # noqa: F401  fixture
from test_solve import lease_solve, open_lane, results

EXEC, DELIVER, REVIEW = "mcp__paoding__exec", "mcp__paoding__deliver", "mcp__paoding__review"


def make(tmp_path, graph, upstream):  # noqa: F811
    graph.cfg = dataclasses.replace(graph.cfg, review_open=True)  # 组装根按设置 lanes.review 打开
    r = Rig(tmp_path, graph, upstream)
    r.statement = "算一下 6 乘 7。"
    open_lane(graph, statement=r.statement)
    return r


def deliver(rig, graph):  # noqa: F811
    lid = lease_solve(graph)
    rig.script(
        [
            {"tool": "Write", "input": {"file_path": "calc.py", "content": "print(6*7)\n"}},
            {"tool": EXEC, "input": {"cmd": "python calc.py"}},
            {
                "tool": DELIVER,
                "input": {
                    "outcome": "answered",
                    "answer": "42",
                    "claims": [{"text": "6×7=42", "refs": ["$r1.artifact"]}, {"text": "常识，没跑"}],
                    "self_check": [{"what": "python calc.py 重跑一次", "result": "pass", "refs": ["$r1.artifact"]}],
                },
            },
        ]
    )
    rec = rig.run(lid)
    assert rec.release["outcome"] == "done", rec.release
    (d,) = graph.state["problems"]["p1"]["deliveries"]
    return d["id"]


def lease_verify(graph, did):  # noqa: F811
    body = {
        "kind": "verify",
        "target": did,
        "holder": "sn1",
        "reserve": {"usd_milli": 500, "wall_s": 600},
        "ttl_s": 600,
    }
    out = graph.submit("tok-sinan", "p1", f"lease-v-{did}", [{"op": "lease", "body": body}])
    assert out["ok"], out
    return out["results"][0]["id"]


def test_review_session_reruns_in_a_copy_and_hands_back_readings(tmp_path, graph, upstream):  # noqa: F811
    rig = make(tmp_path, graph, upstream)
    try:
        did = deliver(rig, graph)
        assert {"kind": "verify", "target": did} in graph.work("p1")
        vid = lease_verify(graph, did)
        rig.script(
            [
                {"tool": "Read", "input": {"file_path": "calc.py"}},  # 工作区是求解会话的副本
                {"tool": EXEC, "input": {"cmd": "python calc.py"}},
                {
                    "tool": REVIEW,
                    "input": {
                        "claims": [
                            {"claim": 0, "verdict": "supported", "note": "输出 42", "refs": ["$r1.artifact"]},
                            {"claim": 1, "verdict": "unclear", "note": "没有引用"},
                        ],
                        "reruns": [{"check": 0, "result": "pass", "refs": ["$r1.artifact"]}],
                        "summary": "两条主张，一条有执行输出支撑",
                    },
                },
            ]
        )
        rec = rig.run(vid)
        assert rec.status == "released" and rec.release["outcome"] == "done", rec.release
        sysmd = (tmp_path / "sessions" / vid / "system.md").read_text(encoding="utf-8")
        assert f"要复核的交付 {did}" in sysmd and "- 0：6×7=42" in sysmd and "- 1：常识，没跑" in sysmd
        assert "你是一个智能体的复核会话" in sysmd
        assert (tmp_path / "sessions" / vid / "workspace" / "calc.py").read_text() == "print(6*7)\n"
        (rv,) = graph.state["problems"]["p1"]["reviews"]
        assert rv["delivery"] == did and rv["lease"] == vid
        assert [c["verdict"] for c in rv["claims"]] == ["supported", "unclear"]
        assert graph.state["artifacts"][rv["reruns"][0]["refs"][0]]["class"] == "exec"
        # 复核只给读数：交付仍等人看，不再派复核
        assert graph.work("p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]
        assert graph.state["problems"]["p1"].get("terminal") is None
    finally:
        rig.close()


def test_a_review_session_that_never_reviews_gets_one_closing_round_then_ends(tmp_path, graph, upstream):  # noqa: F811
    rig = make(tmp_path, graph, upstream)
    try:
        did = deliver(rig, graph)
        vid = lease_verify(graph, did)
        rig.script([{"tool": EXEC, "input": {"cmd": "true"}}], resume_steps=[])
        rec = rig.run(vid)
        assert rec.release["outcome"] == "nothing", rec.release
        assert rec.rounds == 2  # 一轮复核、一轮收尾，不接力
        assert "reviews" not in graph.state["problems"]["p1"]
        assert graph.work("p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]  # 不重派
    finally:
        rig.close()


def test_review_tool_fills_in_the_delivery_and_passes_kernel_rejections_back(tmp_path, graph, upstream):  # noqa: F811
    rig = make(tmp_path, graph, upstream)
    try:
        did = deliver(rig, graph)
        vid = lease_verify(graph, did)
        rig.script(
            [
                {
                    "tool": REVIEW,
                    "input": {"claims": [{"claim": 0, "verdict": "supported", "note": "x"}], "summary": "s"},
                },
                {
                    "tool": REVIEW,
                    "input": {
                        "claims": [
                            {"claim": 0, "verdict": "unclear", "note": "没核"},
                            {"claim": 1, "verdict": "unclear", "note": "没核"},
                        ],
                        "summary": "没来得及核",
                    },
                },
            ]
        )
        rec = rig.run(vid)
        assert rec.release["outcome"] == "done"
        (rv,) = graph.state["problems"]["p1"]["reviews"]  # 第一次漏核了一条主张，内核拒、会话改正后重交
        assert rv["delivery"] == did and rv["reruns"] == [] and len(rv["claims"]) == 2
        rej = [r for r in results(rec) if r.get("type") == "tool_result" and "schema_error" in str(r.get("content"))]
        assert rej, "第一次 review 的拒绝码要回到会话"
    finally:
        rig.close()
