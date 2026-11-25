"""巡查的清扫钩子（scripts/stack.py 的 Stack._sweep 与 Stack._lease_ended_s）。

钩子里有两段：原有的孤儿清扫（属主进程已死的），和执行层按租约标签的回收。两段互不牵连——
新回收出错不耽误原有清扫，也不抛给巡查循环（循环里还有过期回收与预算检查）；原有清扫出的环境故障照旧抛。
“这个租约在本实例账上结束多久了”由组装层答，执行层不读事件账。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "adapter" / "tests"))

import stack  # noqa: E402
from adapter_rig import graph, lease_bootstrap, rig, upstream  # noqa: E402,F401  fixture
from stack import Stack, StackConfig  # noqa: E402


class Exec:
    """执行层的替身：只记 reclaim 被怎么叫的。"""

    def __init__(self, fault: Exception | None = None):
        self.fault, self.seen = fault, []

    def reclaim(self, lease_ended, grace_s):
        self.seen.append((lease_ended, grace_s))
        if self.fault:
            raise self.fault
        return ["pd-b"]


def hook(ex: Exec, grace: float = 60.0) -> SimpleNamespace:
    me = SimpleNamespace(executor=ex, cfg=SimpleNamespace(reclaim_grace_s=grace))
    me._lease_ended_s = lambda lid: None
    return me


def test_the_hook_runs_both_and_passes_the_configured_grace(monkeypatch):
    monkeypatch.setattr(stack, "sweep_orphans", lambda: ["pd-a"])
    ex = Exec()
    me = hook(ex, grace=7.5)
    assert Stack._sweep(me) == ["pd-a", "pd-b"]
    assert ex.seen == [(me._lease_ended_s, 7.5)]


def test_the_grace_is_a_config_item_and_defaults_to_a_minute(tmp_path):
    assert StackConfig.load(tmp_path).reclaim_grace_s == 60.0
    (tmp_path / "config.yaml").write_text("reclaim_grace_s: 5\n")
    assert StackConfig.load(tmp_path).reclaim_grace_s == 5.0


def test_a_fault_in_the_new_reclaim_does_not_touch_the_old_sweep(monkeypatch, caplog):
    monkeypatch.setattr(stack, "sweep_orphans", lambda: ["pd-a"])
    with caplog.at_level(logging.ERROR):
        assert Stack._sweep(hook(Exec(RuntimeError("回收里的缺陷")))) == ["pd-a"]  # 不抛：巡查照常
    assert any("按租约标签回收出错" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("fault", [OSError("docker 不在"), subprocess.TimeoutExpired(["docker"], 120)])
def test_a_fault_in_the_old_sweep_still_surfaces_but_the_reclaim_has_run(monkeypatch, fault):
    def boom():
        raise fault

    monkeypatch.setattr(stack, "sweep_orphans", boom)
    ex = Exec()
    with pytest.raises(type(fault)):  # 与改动前一样交给巡查循环去记
        Stack._sweep(hook(ex))
    assert len(ex.seen) == 1  # 原有清扫挂了，按租约回收照做


def test_lease_ended_answers_from_this_instances_books(rig, graph, monkeypatch):  # noqa: F811
    me = SimpleNamespace(graph=graph, _lease_end_ts={})
    assert Stack._lease_ended_s(me, "l_404") is None  # 账上查不到（别的实例的租约、编造的标签）
    lid = lease_bootstrap(graph)
    assert Stack._lease_ended_s(me, lid) is None  # 仍在途
    out = graph.submit("tok-sinan", "p1", "rel", [{"op": "release", "body": {"lease": lid, "outcome": "nothing"}}])
    assert out["ok"], out
    l = graph.state["leases"][lid]
    (ev,) = graph.events("p1", l["ended_seq"] - 1, limit=1, upto=l["ended_seq"])
    monkeypatch.setattr(stack.time, "time", lambda: (ev["ts"] + 42_500) / 1000)
    assert Stack._lease_ended_s(me, lid) == 42.5  # 已结束：离结束那条事件多少秒
    monkeypatch.setattr(stack.time, "time", lambda: (ev["ts"] + 90_000) / 1000)
    assert Stack._lease_ended_s(me, lid) == 90.0 and me._lease_end_ts == {lid: ev["ts"]}  # 结束时刻只查一次
