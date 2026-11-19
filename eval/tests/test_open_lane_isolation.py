"""开放道永不进评测读数与 G1 对照（open-lane 裁决附加条件 1：写成验收断言，不是注释）。

评测台只跑严格道：清单开出的题一律判官判定；运行记录的终态只有 solved、unsolved、failed；
开放道的 delivered 无论从哪条路来，都进不了记录，更进不了 solved。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from paoding_eval.readings import collect_records
from paoding_eval.record import TERMINALS, Record
from paoding_eval.runner import record_terminal
from paoding_eval.spec import DRYRUN, load

ROOT = Path(__file__).resolve().parents[2]


def test_record_has_no_open_lane_terminal():
    assert "delivered" not in TERMINALS and "accepted" not in TERMINALS
    with pytest.raises(ValueError):
        Record("full", "p", 1, "m", 1.0, "delivered", 0.0, 0, "x")


def test_delivered_never_counts_as_solved():
    assert record_terminal({"closed": True, "terminal": "delivered"}) == "failed"
    assert record_terminal({"closed": True, "terminal": "accepted"}) == "failed"
    assert record_terminal({"closed": True, "terminal": "solved"}) == "solved"
    assert record_terminal({"closed": False, "terminal": None}) == "failed"


@pytest.mark.parametrize("spec", [DRYRUN, load(ROOT / "eval" / "problems.d" / "TEMPLATE.yaml")])
def test_eval_specs_only_open_strict_problems(spec):
    body = spec.open_ops()[-1]["body"]
    assert body["goal"]["accept"] == "judge" and body["goal"]["check"]["judge_id"] in body["judges"]
    assert "self_checks" not in body["goal"]


def test_collect_refuses_a_delivered_record(tmp_path):
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    rec = {
        "mode": "full",
        "problem": "p",
        "run": 1,
        "model": "m",
        "duration_s": 1.0,
        "terminal": "delivered",
        "cost_usd": 0.1,
        "events": 3,
        "log_dir": "r1",
    }
    (run / "record.json").write_text(json.dumps(rec))
    with pytest.raises(ValueError):
        collect_records(tmp_path / "runs", tmp_path / "into")
