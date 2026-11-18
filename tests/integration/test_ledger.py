"""D9 离线：账本投影与代理记录对账测试台。

验收：3.5.5 的 4（代理侧计量与图里账本逐任务一致）、5（重放后账本投影与运行时合计一致）。
跑若干个真实形态的会话（假 CLI，JSON 与 SSE 混合，含被杀的任务），然后：
1. 代理自记 vs 图里 cost 事件：逐任务相等；
2. 关掉图服务、从日志重放：/budget 投影与运行时逐字段相等，与代理合计相等。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "adapter" / "tests"))

from adapter_rig import CFG, graph, lease_bootstrap, rig, upstream  # noqa: E402,F401  fixture

from paoding_adapter.proxy import ledger_diff  # noqa: E402
from paoding_graph.contract import GraphService  # noqa: E402

SHOW = {"tool": "mcp__paoding__show", "input": {"list": "all"}}


def test_ledger_reconciles_and_replays(rig, tmp_path):
    g = rig.graph
    sessions = []
    # 1. bootstrap：三个回合后交 nothing
    lid = lease_bootstrap(g)
    rig.script([SHOW, SHOW, {"tool": "mcp__paoding__submit", "input": {"ops": [], "final": {"outcome": "nothing"}}}])
    sessions.append(rig.run(lid))
    # 2. reason：预留很小，第二个请求被代理拒绝 → budget_exhausted
    out = g.submit(
        "tok-sinan",
        "p1",
        "lease-r",
        [
            {
                "op": "lease",
                "body": {"kind": "reason", "holder": "sn1", "reserve": {"usd_milli": 5, "wall_s": 60}, "ttl_s": 120},
            }
        ],
    )
    rig.script([SHOW, SHOW], resume_steps=[SHOW])
    sessions.append(rig.run(out["results"][0]["id"]))
    # 3. 人给 Hint 触发下一轮 reason，换个模型计价
    g.submit("tok-human", "p1", "h1", [{"op": "hint", "body": {"text": "换个角度"}}])
    rig.upstream.model = "claude-opus-5-5"
    out = g.submit(
        "tok-sinan",
        "p1",
        "lease-r2",
        [
            {
                "op": "lease",
                "body": {"kind": "reason", "holder": "sn1", "reserve": {"usd_milli": 500, "wall_s": 60}, "ttl_s": 120},
            }
        ],
    )
    rig.script([SHOW, {"tool": "mcp__paoding__submit", "input": {"ops": [], "final": {"outcome": "unsolved"}}}])
    sessions.append(rig.run(out["results"][0]["id"]))

    assert [s.release["outcome"] for s in sessions] == ["nothing", "budget_exhausted", "nothing"]
    assert ledger_diff(rig.proxy, g.state) == []
    runtime = g.budget("p1")
    assert runtime["spent"]["usd_milli"] == rig.proxy.global_spent > 0
    assert set(runtime["by_kind"]) == {"bootstrap", "reason"}
    assert {c["model"] for c in g.state["costs"]} == {"claude-sonnet-5-5", "claude-opus-5-5"}

    # 重放：同一日志文件重新打开，即崩溃恢复路径
    g2 = GraphService(tmp_path / "g.sqlite", CFG, g.tokens)
    assert g2.budget("p1") == runtime
    assert g2.state["costs"] == g.state["costs"]
    assert ledger_diff(rig.proxy, g2.state) == []


def test_duplicate_cost_report_counted_once(rig):
    """代理的 cost 提交带幂等键：同一请求重复上报（例如重试）只记一次。"""
    lid = lease_bootstrap(rig.graph)
    rig.proxy.register_task("t", lid, "p1", 1000)
    task = rig.proxy.task("t")
    for _ in range(2):
        rig.graph.submit(
            "tok-adapter",
            "p1",
            f"cost:{lid}:1",
            [
                {
                    "op": "cost",
                    "body": {
                        "task_id": lid,
                        "source": "proxy",
                        "tokens_in": 1,
                        "tokens_cached": 0,
                        "tokens_out": 1,
                        "usd_milli": 7,
                        "wall_s": 0,
                        "price_table": "x",
                    },
                }
            ],
        )
    assert sum(c["usd_milli"] for c in rig.graph.state["costs"]) == 7
    assert task.spent_usd_milli == 0
    diff = ledger_diff(rig.proxy, rig.graph.state)
    assert diff and diff[0] == {"task_id": lid, "proxy": 0, "graph": 7}  # 对账能发现不一致
