"""组装根的端到端（离线）：哮天犬 + Adapter 会话运行器 + 假 CLI + 端点代理 + 图服务。

这里是唯一同时 import adapter 与 watchdog 的地方，相当于组装根；组件之间仍只经契约（TaskControl 是结构化接口）。
验收：3.5.5 的 4（越过软线出现收尾轮并带回部分结果；越过硬顶进程被杀、租约释放、会话记录保存到被杀之前）；
3.4.5 的 3（Adapter 不续租时租约到期，哮天犬回收）。
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "adapter" / "tests"))

from adapter_rig import graph, lease_bootstrap, rig, upstream  # noqa: E402,F401  fixture
from paoding_watchdog.contract import DogConfig, Watchdog  # noqa: E402


def sub(final):
    return {"tool": "mcp__paoding__submit", "input": {"ops": [], "final": final}}


def run_with_dog(rig, lid, steps, resume_steps=(), until=lambda r: False, interval=0.1):
    rig.graph.tokens.issue({"kind": "watchdog", "id": "wd"}, "tok-wd")
    dog = Watchdog(DogConfig(token="tok-wd"), rig.graph, rig.graph, rig.runner,
                   clock=lambda: rig.graph._ts())
    rig.script(steps, resume_steps)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("rec", rig.run(lid)))
    t.start()
    reports = []
    while t.is_alive():
        reports.append(dog.tick())
        time.sleep(interval)
    return out["rec"], reports


def test_soft_line_triggers_closing_round(rig):
    rig.upstream.usage = {"input_tokens": 500, "output_tokens": 0}   # 每次请求 1 毫美元
    lid = lease_bootstrap(rig.graph, reserve=21)             # 软线 18.9：第 19 次请求后越过，收尾轮再花 1
    show = {"tool": "mcp__paoding__show", "input": {"list": "all"}}
    rec, reports = run_with_dog(rig, lid, [show] * 19 + [{"hang": 20}],
                                resume_steps=[sub({"outcome": "unsolved", "suggestions": ["换个入口"]})])
    assert sum(lid in r.soft for r in reports) == 1
    assert rec.rounds == 2 and any(e.get("subtype") == "interrupted" for e in rec.events)
    assert rec.status == "released" and rec.release["outcome"] == "nothing"   # 收尾轮带回结论
    lease = rig.graph.state["leases"][lid]
    assert lease["transcript_ref"] == rec.transcript_ref
    [rel] = [e for e in rig.graph.log.events() if e["kind"] == "release"]
    assert rel["body"]["suggestions"] == ["换个入口"]


def test_hard_line_kills_and_saves_record(rig):
    lid = lease_bootstrap(rig.graph, reserve=5)
    show = {"tool": "mcp__paoding__show", "input": {"list": "all"}}
    rec, reports = run_with_dog(rig, lid, [show, {"hang": 20}], resume_steps=[{"hang": 20}])
    assert any((lid, "budget") in r.killed for r in reports)
    assert rec.status == "killed(budget)"
    lease = rig.graph.state["leases"][lid]
    assert lease["outcome"] == "budget_exhausted" and lease["transcript_ref"] == rec.transcript_ref
    assert any(e.get("type") == "assistant" for e in rec.events)          # 会话记录保存到被杀之前
    assert rig.executor.destroyed == ["sb-test"]
