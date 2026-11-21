"""常设留出（焚决 F5，docs/design/fenjue/04-evolution.md §5）：上一团火不删，新题按题号哈希以小比例分给它。

- 分配是题号的纯函数，按火位加盐；比例与留出的火都算进功法摘要，所以开题事件里的摘要加题号就能复算分到哪边；
- 留出的火顶替功法里出身（lineage.from）提到它的那一团，别的火不动；
- 读端 arm_of 只对开在今天这套功法之下的题给出臂名，别的功法与焚决之前的题给 None。
"""

from __future__ import annotations

import copy
import json

import pytest

from paoding_fenjue import shapes
from paoding_fenjue.contract import arm_of, gongfa, holdout_permille, in_holdout, params

PIDS = [f"kt-{i:04d}" for i in range(4000)]


def test_the_previous_fire_of_dossier_001_is_in_the_standing_holdout():
    g = gongfa()
    assert g["holdout"] == {"H6": ["h6.activity@1"]}
    assert shapes.stand_ins("H6") == {"h6.activity-ledger": shapes.fire("h6.activity")}


def test_allocation_is_deterministic_and_near_the_ratio():
    picked = [p for p in PIDS if in_holdout(p, "H6")]
    assert picked == [p for p in PIDS if in_holdout(p, "H6")]  # 纯函数
    share = len(picked) / len(PIDS)
    assert abs(share - holdout_permille() / 1000) < 0.015
    assert not any(in_holdout(p, "H1") for p in PIDS)  # 没有留出的火位从不分


def test_a_held_out_problem_gets_the_previous_fire_and_only_that_one():
    held = next(p for p in PIDS if in_holdout(p, "H6"))
    main = next(p for p in PIDS if not in_holdout(p, "H6"))
    assert params("H6", "h6.activity-ledger", held)["ledger_roles"] == []  # h6.activity：#115 原样，不入账
    assert params("H6", "h6.activity-ledger", main)["ledger_roles"] == ["solve"]
    assert params("H6", "h6.activity-ledger")["ledger_roles"] == ["solve"]  # 不给题号即生效的那团
    assert params("H6", "h6.workbench", held) == params("H6", "h6.workbench")  # 同火位别的火不动
    assert [f["id"] for f in shapes.active("H6", held)] == ["h6.workbench", "h6.activity", "h6.pd"]


def test_the_arm_is_readable_from_the_log():
    g = gongfa()
    held = next(p for p in PIDS if in_holdout(p, "H6"))
    stamp = {"jie": g["jie"], "digest": g["digest"]}
    assert arm_of({"id": held, "gongfa": stamp}, "H6") == "holdout"
    assert arm_of({"id": "p1", "gongfa": stamp}, "H6") == ("holdout" if in_holdout("p1", "H6") else "main")
    assert arm_of({"id": held, "gongfa": {"jie": 1, "digest": "0" * 64}}, "H6") is None  # 别的功法
    assert arm_of({"id": held}, "H6") is None  # 焚决之前


def test_ratio_and_holdout_are_in_the_gongfa_digest():
    g = {k: v for k, v in gongfa().items() if k != "digest"}
    base = shapes.gongfa_digest(g)
    assert shapes.gongfa_digest({**g, "holdout_permille": g["holdout_permille"] + 1}) != base
    assert shapes.gongfa_digest({**g, "holdout": {}}) != base


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda g: g["holdout"].update({"H6": ["h6.workbench@1"]}), "顶替了 0 团"),
        (lambda g: g.update({"holdout_permille": 1001}), "holdout_permille"),
        (lambda g: g["holdout"].update({"H6": ["h6.activity@9"]}), "与清单不符"),
    ],
)
def test_a_malformed_holdout_is_refused(monkeypatch, change, message):
    g = json.loads(json.dumps(shapes._read("gongfa.json")))
    change(g)
    real = shapes._read
    monkeypatch.setattr(shapes, "_read", lambda name: copy.deepcopy(g) if name == "gongfa.json" else real(name))
    shapes.gongfa.cache_clear()
    try:
        with pytest.raises(ValueError, match=message):
            shapes.gongfa()
    finally:
        monkeypatch.undo()
        shapes.gongfa.cache_clear()
