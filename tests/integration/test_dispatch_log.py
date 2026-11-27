"""调度循环收回会话记录时逐条记日志（scripts/stack.py 的 collect_logged）。

cz 2026-11-26 真系统：一个会话起沙箱失败，日志里没有一行。原因之一是调度循环在“有会话在途就等”的那一处
收回了记录却没有接返回值；会话几乎总是在这段等待里结束，所以“会话结束”一行（正常结束的也一样）经常没有。
现在循环里收回记录只走 collect_logged 一个口子。
"""

from __future__ import annotations

import inspect
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "adapter" / "tests"))

from adapter_rig import graph, rig, upstream  # noqa: E402,F401  fixture
from stack import Stack, collect_logged  # noqa: E402

from paoding_sinan.contract import Sinan, SinanConfig  # noqa: E402


class Runner:
    """会话后端的替身：等放行再结束，正常返回一条记录，或者抛出（会话线程崩了）。"""

    def __init__(self, crash: bool):
        self.crash, self.go = crash, threading.Event()

    def run(self, pid, lid, *, statement):
        assert self.go.wait(10)
        if self.crash:
            raise RuntimeError("会话线程炸了")
        return SimpleNamespace(status="released", release={"outcome": "nothing"})


@pytest.mark.parametrize("crash", [False, True])
def test_a_record_collected_while_waiting_is_logged(rig, graph, caplog, crash):  # noqa: F811
    runner = Runner(crash)
    sinan = Sinan(SinanConfig(token="tok-sinan", ttl_s=600, max_sessions=1), graph, graph, rig.blobs, runner)
    L = logging.getLogger("paoding.test.sinan")
    try:
        r = sinan.dispatch("p1")
        assert "started" in r, r
        with caplog.at_level(logging.INFO, logger=L.name):
            assert collect_logged(sinan, L, "p1", 0) == [] and caplog.records == []  # 循环顶上：还在途，没有可记的
            assert sinan.in_flight()
            threading.Timer(0.2, runner.go.set).start()
            (done,) = collect_logged(sinan, L, "p1", 10)  # 循环底下：等到它结束——收回的这一条要记
        (line,) = [rec.getMessage() for rec in caplog.records]
        assert line.startswith(f"p1 bootstrap 会话结束：租约 {r['lease']}，")
        if crash:
            assert done["status"] == "crashed" and "crashed，release=None（RuntimeError: 会话线程炸了）" in line
        else:
            assert done["status"] == "released" and line.endswith("released，release=nothing")
        assert caplog.records[0].lease_id == r["lease"] and caplog.records[0].problem_id == "p1"
        assert collect_logged(sinan, L, "p1", 0) == []  # 下一圈：已经收过、记过，不重复
    finally:
        runner.go.set()
        sinan.close()


def test_the_dispatch_loop_collects_only_through_the_logging_door():
    """调度循环里不能再有直接调 sinan.collect 的地方（那样收走的记录就不进日志）。"""
    src = inspect.getsource(Stack._sinan_loop)
    assert "sinan.collect(" not in src and src.count("collect_logged(sinan, L, pid") == 3
