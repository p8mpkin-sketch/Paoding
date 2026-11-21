"""炼化六步的数据操作（焚决 F5）：一份演示炼档从识火走到定阶，再散火；每一步的守门都试一遍。"""

from __future__ import annotations

import copy

import pytest

from paoding_fenjue import lianhua as lh
from paoding_fenjue import shapes

TODAY = "2026-11-21"
SHIHUO = {"source": "某系统的结果页（演示）", "phenomenon": "结论先行", "gap": "结果页先列过程", "is_fire": "是"}
CUIYI = {
    "yi": "结论先于过程呈现",
    "premise": "结论可信",
    "cost": "过程被折叠",
    "overlap": "H7 结果页",
    "conflict": "T5：结论不能脱离证据",
    "hypothesis": "结论先行且每条结论一键到执行留档",
    "split": "无",
}


def draft() -> dict:
    f = copy.deepcopy(shapes.fire("h7.result"))
    f.update(id="h7.result-first", ver=1, lineage={"dossier": "999", "from": ["h7.result"]})
    return f


READINGS = [
    {"dim": "结论可追率", "kind": "新生", "dir": "up", "gate": 1, "test": "fenjue/tests/test_lianhua.py::test_walk"},
    {"dim": "金丝雀泄漏数", "kind": "本火", "dir": "down"},
    {"dim": "每次交付花费", "kind": "共有", "dir": "down"},
]
ARMS = {"B": "结果页原样", "A1": "只把结论挪到最前", "F": "结论先行加一键到留档", "B1": "B 再跑一遍"}
TRIALS_OK = {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}


def placed() -> dict:
    d = lh.new("999", "result-first", "结论先行", TODAY, SHIHUO)
    d = lh.cuiyi(d, CUIYI)
    return lh.ruwei(d, draft(), "h7.result", ARMS, READINGS)


def trialed(ok: bool = True, kernel: int = 0) -> dict:
    d = lh.approve_design(placed(), "cz", TODAY)
    trials = {**TRIALS_OK, **({} if ok else {"T2": {"ok": False, "summary": "1 failed"}})}
    return lh.yanti(d, kernel, [], trials, "abc1234")


VALUES = {
    "结论可追率": {"B": 0, "A1": 0, "F": 1},
    "金丝雀泄漏数": {"B": 0, "A1": 0, "F": 0},
    "每次交付花费": {"B": 100, "B1": 104, "A1": 101, "F": 102},
}


def test_walk():
    d = trialed()
    d = lh.ronghuo(d, VALUES, jie_now=2)
    assert d["outcome_proposed"] == "huolian" and d["jie_proposed"] == 3
    assert [r["verdict"] for r in d["readings"]] == ["达门槛", "不退", "不退"]
    assert d["readings"][2]["m"] == 4  # 噪声底取 |B − B′|
    g0 = shapes._read("gongfa.json")
    d, g = lh.jue(d, g0, "cz", TODAY, "huolian", ["演示"])
    assert d["status"] == "adopted" and d["verdict"]["jie"] == 3
    assert "h7.result-first@1" in g["fires"]["H7"] and "h7.result@1" not in g["fires"]["H7"]
    assert g["holdout"]["H7"] == ["h7.result@1"]  # 上一团火进常设留出
    assert g["jie"] == 3 and g["history"][-1] == {
        "jie": 3,
        "change": "结论先行（炼档 999）",
        "dossier": "999",
        "replaces": "h7.result@1",
    }
    d2, g2 = lh.sanhuo(d, g, "cz", TODAY, "留出对照上交付率跌破门槛（演示）")
    assert d2["status"] == "reverted" and d2["reverts"][0]["back_to"] == "h7.result@1"
    assert g2["fires"]["H7"] == g0["fires"]["H7"] and "H7" not in g2["holdout"]
    assert g2["jie"] == 2 and g2["history"][-1]["reverts"] == "999"  # 降阶，不抹升阶记录
    assert len(g2["history"]) == len(g0["history"]) + 2
    md = lh.render(d2)
    assert all(
        f"## {s}" in md
        for s in ("一、识火", "二、萃意", "三、入位", "四、验体", "五、融火", "六、裁决", "七、散火记录")
    )
    assert "火莲" in md and "留出对照上交付率跌破门槛" in md


def test_steps_go_in_order():
    d = lh.new("999", "x", "x", TODAY, SHIHUO)
    with pytest.raises(lh.StepError, match="之后做"):
        lh.yanti(d, 0, [], TRIALS_OK, "x")
    with pytest.raises(lh.StepError, match="萃意还缺"):
        lh.ruwei(lh.cuiyi(d, {"yi": "只写了一栏"}), draft(), "h7.result", ARMS, READINGS)
    with pytest.raises(lh.StepError, match="不开档"):
        lh.new("999", "x", "x", TODAY, {**SHIHUO, "is_fire": "否：只是多一个按钮"})


def test_preregistered_readings_cannot_move():
    d = placed()
    d["status"] = "distilled"  # 假装回到入位之前再登记一次
    moved = [{**READINGS[0], "gate": 0.5}, *READINGS[1:]]
    with pytest.raises(lh.StepError, match="不能改"):
        lh.ruwei(d, draft(), "h7.result", ARMS, moved)
    with pytest.raises(lh.StepError, match="没有预登记"):
        lh.ronghuo(trialed(), {"新加的一维": {"F": 1}}, 2)


def test_placement_checks():
    d = lh.cuiyi(lh.new("999", "x", "x", TODAY, SHIHUO), CUIYI)
    with pytest.raises(lh.StepError, match="lineage.from"):
        lh.ruwei(d, draft(), "h7.other", ARMS, READINGS)
    with pytest.raises(lh.StepError, match="门槛"):
        lh.ruwei(d, draft(), "h7.result", ARMS, [{"dim": "x", "kind": "新生", "dir": "up"}])


@pytest.mark.parametrize(
    ("change", "outcome"),
    [
        ({}, "huolian"),
        ({"金丝雀泄漏数": {"B": 0, "A1": 0, "F": 1}}, "fanshi"),  # 本火维退：反噬
        ({"每次交付花费": {"B": 100, "B1": 104, "A1": 101, "F": 120}}, "binghuo"),  # 共有维退：不收
        ({"结论可追率": {"B": 0, "A1": 0, "F": 0.5}}, "binghuo"),  # 新生维没达门槛、也没有一维胜出
        (
            {"结论可追率": {"B": 0, "A1": 0, "F": 0.5}, "每次交付花费": {"B": 100, "B1": 101, "A1": 101, "F": 90}},
            "helian",
        ),
    ],
)
def test_outcomes_follow_03(change, outcome):
    d = lh.ronghuo(trialed(), {**VALUES, **change}, 2)
    assert d["outcome_proposed"] == outcome, d["outcome_why"]
    assert (d["jie_proposed"] is not None) == (outcome in lh.TAKEN)


def test_failed_trials_are_backlash_and_no_a1_caps_at_helian():
    assert lh.ronghuo(trialed(ok=False), VALUES, 2)["outcome_proposed"] == "fanshi"
    d = lh.approve_design(placed(), "cz", TODAY)
    d["arms"] = {k: v for k, v in d["arms"].items() if k != "A1"}
    d = lh.ronghuo(lh.yanti(d, 0, [], TRIALS_OK, "x"), VALUES, 2)
    assert d["outcome_proposed"] == "helian" and any("FJ8" in w for w in d["outcome_why"])


def test_a_rejected_fire_leaves_the_gongfa_alone():
    g0 = shapes._read("gongfa.json")
    d = lh.ronghuo(trialed(), VALUES, 2)
    d, g = lh.jue(d, g0, "cz", TODAY, "binghuo", [])
    assert d["status"] == "rejected" and g == g0


def test_the_candidate_gongfa_is_valid():
    """验体用 install 造候选功法：新火装进火位、上一团进留出，品阶不动，已有的留出照旧。"""
    g, old = lh.install(shapes._read("gongfa.json"), placed())
    assert old == "h7.result@1" and g["jie"] == shapes._read("gongfa.json")["jie"]
    assert g["holdout"]["H7"] == ["h7.result@1"] and g["holdout"]["H6"] == ["h6.activity@1"]
