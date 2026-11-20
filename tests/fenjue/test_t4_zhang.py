"""回放不变式 R1（焚决 F1，docs/design/fenjue/04-evolution.md §6）：冻结的黄金日志逐份重放，
终态哈希、各前缀哈希、各题 /work 与状态视图的摘要、读数视图 problems 的摘要都与录制时相同。

黄金日志由 record_goldens.py 截自既有内核测试的测试台，按道分文件；冻结后只许新增文件，不许改。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from record_goldens import LANES, digest

from paoding_graph import views
from paoding_graph import work as wk
from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

GOLDENS = Path(__file__).parent / "goldens"
FILES = sorted(GOLDENS.glob("*.json"))
CASES = [
    pytest.param(f, i, id=f"{f.stem}-{i}")
    for f in FILES
    for i in range(len(json.loads(f.read_text(encoding="utf-8"))["logs"]))
]


def test_every_lane_is_frozen():
    assert {f.stem for f in FILES} == set(LANES.values())


@pytest.mark.parametrize(("path", "n"), CASES)
def test_golden_log_replays_byte_for_byte(path: Path, n: int):
    g = json.loads(path.read_text(encoding="utf-8"))["logs"][n]
    evs = g["events"]
    s = replay(evs, apply, empty_state())
    assert state_hash(s) == g["state_hash"], g["from"]
    for cut, h in g["prefix_hashes"].items():
        assert state_hash(replay(evs[: int(cut)], apply, empty_state())) == h, (g["from"], cut)
    for pid, v in g["views"].items():
        assert digest(wk.work(s, pid)) == v["work"], (g["from"], pid)
        assert digest(views.status(s, pid)) == v["status"], (g["from"], pid)
    assert digest(views.problems(s)) == g["problems"], g["from"]
