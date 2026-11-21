"""体质修炼 003 T4-5：改钉可以撤，改回开题时的那一版；除此之外只许往低改，不许升到开题之后才上线的版本。

单独一个文件、单独一个提交：cz 否决 R3 时整个删掉。不录黄金日志（录法只收 repin 道，见 record_goldens.py）。
"""

from __future__ import annotations

import dataclasses

from conftest import HUMAN, Kernel
from test_gongfa_fields import SINAN, body_of
from test_open_lane import lease_solve, open_lane
from test_repin import ARCHIVE, DOWN, LIVE, NEW

from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

NEWER = "d" * 64
WIDE = dataclasses.replace(LIVE, gongfa_archive=(*ARCHIVE, (NEWER, 3, (("solve", "h1.solo@3"),))))
BACK = {"to": {"jie": 2, "digest": NEW}, "reason": "改错了，改回来"}


def test_t4_5_a_repin_can_be_undone_back_to_the_opening_version():
    k = Kernel(WIDE)
    assert open_lane(k, "p1") == "ok"
    assert k.submit(HUMAN, "p1", "repin", DOWN) == "ok"
    assert k.submit(HUMAN, "p1", "repin", BACK) == "ok"  # 撤销：比此刻生效的高，但是开题那一版
    assert [r["to"]["jie"] for r in k.state["problems"]["p1"]["repins"]] == [1, 2]
    assert k.submit(HUMAN, "p1", "repin", BACK) == "conflict"  # 已经改回来了
    first = lease_solve(k, "p1")
    assert body_of(k, "p1", "lease")[-1]["form"] == "h1.solo@2"
    assert k.submit(SINAN, "p1", "release", {"lease": first, "outcome": "nothing"}) == "ok"
    assert state_hash(replay(k.events, apply, empty_state())) == state_hash(k.state)


def test_t4_5_never_lifts_a_task_above_the_version_it_was_opened_under():
    k = Kernel(WIDE)
    assert open_lane(k, "p1") == "ok"
    up = {"to": {"jie": 3, "digest": NEWER}, "reason": "升上去试试"}
    assert k.submit(HUMAN, "p1", "repin", up) == "forbidden_op"  # 开题之后才上线的
    assert k.submit(HUMAN, "p1", "repin", DOWN) == "ok"
    assert k.submit(HUMAN, "p1", "repin", up) == "forbidden_op"
    assert k.state["problems"]["p1"]["gongfa"] == {"jie": 2, "digest": NEW}
