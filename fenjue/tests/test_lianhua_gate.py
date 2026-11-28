"""原形门（docs/design/fenjue/03-huolian.md §3.1–§3.3）：新结局「不及原形」、两个记号、吸收目标维的输入、
量具改动行数、三只金丝雀，以及按档号划的那条线。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from paoding_fenjue import lianhua as lh
from paoding_fenjue import shapes

ROOT = Path(__file__).resolve().parents[2]
TODAY = "2026-11-28"
TARGET = "留出题上的过线数"
SAME = {"both": 30, "first": 3, "second": 3, "neither": 4}  # 两条相同的臂；不一致 6 个题次，噪声底 5
AHEAD = {"both": 24, "first": 12, "second": 1, "neither": 3}  # 前者（合火）明显强：领先 11
BEHIND = {"both": 24, "first": 1, "second": 12, "neither": 3}  # 前者明显弱：落后 11


def dossier(no: str = "900", *, a0: bool = True, a1: bool = True, parity: str | None = "equal") -> dict:
    """走到验体通过的一份炼档：一个吸收目标维、一个新生维、一个本火维、一个共有维。"""
    f = copy.deepcopy(shapes.fire("h7.result"))
    f.update(id="h7.result-first", ver=1, lineage={"dossier": no, "from": ["h7.result"]})
    d = lh.new(no, "x", "演示", TODAY, {"source": "s", "phenomenon": "p", "gap": "g", "is_fire": "是"})
    d = lh.cuiyi(d, dict.fromkeys(lh.CUIYI[:7], "写了"))
    arms = {"B": "本火", "B1": "本火再跑一遍", "F": "合火"}
    arms |= {"A1": "异火单炼"} if a1 else {}
    arms |= {"A0": "原形"} if a0 else {}
    readings = [
        {"dim": TARGET, "kind": "异火", "dir": "up", "target": True, "n": 40},
        {"dim": "新性质", "kind": "新生", "dir": "up", "gate": 1},
        {"dim": "凭据泄漏数", "kind": "本火", "dir": "down"},
        {"dim": "每题次花费", "kind": "共有", "dir": "down"},
    ]
    why = {"class": parity, **({"reason": "写明的原因"} if parity != "equal" else {})} if parity else None
    d = lh.ruwei(d, f, "h7.result", arms, readings, parity=why)
    d = lh.approve_design(d, "cz", TODAY)
    return lh.yanti(d, 0, [], {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}, "abc1234", measure_lines=0)


def values(*, fb=SAME, fa1=SAME, fa0=SAME, bb=SAME, new=1, leaks=0, cost=100) -> dict:
    pairs = {"B:B1": bb, "F:B": fb}
    pairs |= {"F:A1": fa1} if fa1 else {}
    pairs |= {"F:A0": fa0} if fa0 else {}
    return {
        TARGET: {"pairs": pairs},
        "新性质": {"B": 0, "A1": 0, "F": new},
        "凭据泄漏数": {"B": 0, "A1": 0, "F": leaks},
        "每题次花费": {"B": 100, "B1": 104, "A1": 100, "F": cost},
    }


def run(d: dict, v: dict) -> dict:
    return lh.ronghuo(d, v, jie_now=2)


# ---------------------------------------------------------------- 判定表，逐格

# 原来的四种结局各一种读数；原形门三种状态各一种读数。十二格每格一个期望。
BASE = {
    "huolian": {},  # 新生维达门槛，有异火单炼臂
    "helian": {"new": 0.5, "fb": AHEAD, "fa1": AHEAD},  # 新生维没达门槛，目标维上胜过两个来源
    "binghuo": {"new": 0.5},  # 不退，但没有一维胜出
    "fanshi": {"leaks": 1},  # 本火维退步
}
GATES = {"passed": {"fa0": SAME}, "failed": {"fa0": BEHIND}, "unjudged": {"fa0": None}}
TABLE = {
    ("huolian", "passed"): "huolian",
    ("huolian", "failed"): "buji",
    ("huolian", "unjudged"): "helian",  # 原形门未判：结局最高合炼
    ("helian", "passed"): "helian",
    ("helian", "failed"): "buji",
    ("helian", "unjudged"): "helian",
    ("binghuo", "passed"): "binghuo",
    ("binghuo", "failed"): "binghuo",  # 本来就不收：并火与不及原形分开记，诊断不同
    ("binghuo", "unjudged"): "binghuo",
    ("fanshi", "passed"): "fanshi",
    ("fanshi", "failed"): "fanshi",
    ("fanshi", "unjudged"): "fanshi",
}


@pytest.mark.parametrize(("base", "gate"), sorted(TABLE))
def test_decision_table_cell_by_cell(base, gate):
    d = run(dossier(), values(**{**BASE[base], **GATES[gate]}))
    assert d["outcome_proposed"] == TABLE[base, gate], d["outcome_why"]
    assert d["yuanxing_gate"]["state"] == gate
    assert (d["jie_proposed"] is not None) == (TABLE[base, gate] in lh.TAKEN)
    assert "buji" not in lh.TAKEN and lh.OUTCOMES["buji"] == "不及原形"


def test_below_the_prototype_says_which_dimension_and_by_how_much():
    d = run(dossier(), values(fa0=BEHIND))
    assert d["yuanxing_gate"] == {"state": "failed", "why": [f"{TARGET}：合火比原形落后 11 个题次，超过噪声底 5"]}
    assert any("本来够得上火莲" in w and "不及原形" in w for w in d["outcome_why"])
    md = lh.render(d)
    assert "原形门未过" in md and "| F 对 A° | 24 | 1 | 12 | 3 | 5 | 未过 |" in md and "结局提议：**不及原形**" in md
    d2, g = lh.jue(d, shapes._read("gongfa.json"), "cz", TODAY, "buji", [])
    assert d2["status"] == "rejected" and g == shapes._read("gongfa.json")  # 不收：功法不动


@pytest.mark.parametrize(("discordant", "m"), [(0, 1), (1, 2), (4, 4), (6, 5), (9, 6), (16, 8), (40, 13)])
def test_noise_floor(discordant, m):
    assert lh.noise_floor(discordant) == m


def test_the_gate_is_exactly_at_the_noise_floor():
    """「只有原形过」减「只有合火过」不超过 m 才算过门：等于 m 过，多 1 个题次就不过。对 B 的退与胜同理。"""
    at = {"both": 28, "first": 1, "second": 6, "neither": 5}  # 落后 5，等于噪声底
    over = {"both": 28, "first": 1, "second": 7, "neither": 4}  # 落后 6
    assert run(dossier(), values(fa0=at))["yuanxing_gate"]["state"] == "passed"
    assert run(dossier(), values(fa0=over))["yuanxing_gate"]["state"] == "failed"
    assert run(dossier(), values(fb=at))["readings"][0]["verdict"] == "不退"
    d = run(dossier(), values(fb=over))
    assert d["readings"][0]["verdict"] == "退" and d["outcome_proposed"] == "binghuo"
    lead = {"both": 28, "first": 7, "second": 1, "neither": 4}  # 领先 6
    assert run(dossier(), values(new=0.5, fb=lead, fa1=lead))["outcome_proposed"] == "helian"
    assert run(dossier(), values(new=0.5, fb=lead, fa1=SAME))["outcome_proposed"] == "binghuo"  # 要两边都胜


def test_too_few_matched_runs_is_only_a_flag():
    """配上对的题次数少于预登记的样本量：不算胜，门不判；退步照记。"""
    few = {"both": 10, "first": 12, "second": 0, "neither": 0}
    d = run(dossier(), values(new=0.5, fb=few, fa1=few, fa0=few))
    assert d["outcome_proposed"] == "binghuo" and d["yuanxing_gate"]["state"] == "unjudged"
    assert d["readings"][0]["verdict"] == "不退（样本不足，只作旗帜）"
    few_behind = {"both": 10, "first": 0, "second": 12, "neither": 0}
    assert run(dossier(), values(fb=few_behind))["outcome_proposed"] == "binghuo"


def test_other_alien_dimensions_may_not_fall_below_the_prototype_either():
    d = dossier()
    d["readings"].append({"dim": "执行到可见的延迟", "kind": "异火", "dir": "down"})
    slow = {"执行到可见的延迟": {"B": 60, "B1": 61, "A1": 3, "F": 3.5, "A0": 1}}
    d = run(d, {**values(), **slow})
    assert d["outcome_proposed"] == "buji" and "执行到可见的延迟" in d["yuanxing_gate"]["why"][0]


# ---------------------------------------------------------------- 条件不对等与两个记号


@pytest.mark.parametrize(
    ("parity", "waiver", "fa0", "state", "outcome"),
    [
        ("equal", False, SAME, "passed", "huolian"),
        ("equal", False, BEHIND, "failed", "buji"),
        ("ours_or_neutral", False, BEHIND, "failed", "buji"),  # 输了照样不收
        ("ours_or_neutral", False, AHEAD, "passed", "huolian"),  # 赢了只作旗帜，不改变结局
        ("theirs", False, BEHIND, "failed", "buji"),  # 没有豁免：门照判
        ("theirs", True, BEHIND, "unjudged", "helian"),  # 有豁免：门降为参考，结局最高合炼
        ("theirs", True, SAME, "unjudged", "helian"),
        (None, False, SAME, "unjudged", "helian"),  # 入位时没有登记对等声明
        (None, False, BEHIND, "failed", "buji"),  # 没登记不是输了也收的理由
    ],
)
def test_unequal_conditions(parity, waiver, fa0, state, outcome):
    d = dossier(parity=parity)
    if waiver:
        d["status"] = "placed"
        d = lh.approve_design(d, "cz", TODAY, waive_gate="原形绑定一个我们用不了的模型")
        d["status"] = "trialed"
    d = run(d, values(fa0=fa0))
    assert (d["yuanxing_gate"]["state"], d["outcome_proposed"]) == (state, outcome), d["outcome_why"]
    if parity == "ours_or_neutral" and state == "passed":
        assert "只作旗帜" in d["yuanxing_gate"]["why"][0]
    if waiver:
        assert "豁免" in d["yuanxing_gate"]["why"][0] and "写下豁免" in lh.render(d)


def test_no_prototype_arm_or_no_target_dimension_leaves_the_gate_unjudged():
    d = run(dossier(a0=False), values(fa0=None))
    assert d["yuanxing_gate"]["state"] == "unjudged" and d["outcome_proposed"] == "helian"
    assert "原形门未判" in lh.render(d) and "原形门未判：结局最高合炼" in d["outcome_why"]
    plain = dossier()
    plain["readings"] = [r for r in plain["readings"] if not r.get("target")]
    v = {k: x for k, x in values().items() if k != TARGET}
    d = run(plain, v)
    assert d["yuanxing_gate"]["state"] == "unjudged" and d["outcome_proposed"] == "helian"


def test_parity_is_declared_at_placement_and_cannot_move():
    d = dossier(parity="ours_or_neutral")
    again = copy.deepcopy(d)
    again["status"] = "placed"
    f, arms, readings = again["fire"], again["arms"], [dict(r) for r in again["readings"]]
    with pytest.raises(lh.StepError, match="对等声明已经写下"):
        lh.ruwei(again, f, "h7.result", arms, readings, parity={"class": "equal"})
    fresh = lh.cuiyi(lh.new("900", "x", "x", TODAY, d["shihuo"]), d["cuiyi"])
    with pytest.raises(lh.StepError, match="写明原因"):
        lh.ruwei(fresh, f, "h7.result", arms, readings, parity={"class": "theirs"})
    with pytest.raises(lh.StepError, match="归类只取"):
        lh.ruwei(fresh, f, "h7.result", arms, readings, parity={"class": "差不多"})
    with pytest.raises(lh.StepError, match="豁免由 cz"):
        lh.ruwei(fresh, f, "h7.result", arms, readings, parity={"class": "equal", "waiver": "自己写的"})
    d["status"] = "placed"
    with pytest.raises(lh.StepError, match="才谈得上豁免"):
        lh.approve_design(d, "cz", TODAY, waive_gate="想降为参考")


def test_target_dimension_must_be_alien_and_carry_a_sample_size():
    d = dossier()
    fresh = lh.cuiyi(lh.new("900", "x", "x", TODAY, d["shihuo"]), d["cuiyi"])
    with pytest.raises(lh.StepError, match="要是异火维"):
        lh.ruwei(fresh, d["fire"], "h7.result", d["arms"], [{"dim": "x", "kind": "共有", "dir": "up", "target": True}])
    with pytest.raises(lh.StepError, match="样本量"):
        lh.ruwei(fresh, d["fire"], "h7.result", d["arms"], [{"dim": "x", "kind": "异火", "dir": "up", "target": True}])


# ---------------------------------------------------------------- 门的输入清单


class Spy(dict):
    """记下被读过的键。"""

    read: set[str]

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self.read.add(k)
        return super().get(k, default)

    def __contains__(self, k):
        self.read.add(k)
        return super().__contains__(k)


def test_the_gate_reads_only_paired_counts_on_the_target_dimension():
    """判定函数在吸收目标维上只读成对比较的四格计数（由盲判的产出与花费记录算出）与预登记的栏。

    往这一维里塞各臂自己报的数、引擎内部的读数，值都与四格计数唱反调：结局不变，而且这些栏一个都没被读过。"""
    d = dossier()
    d["readings"][0]["pairs"] = values(fa0=BEHIND)[TARGET]["pairs"]
    for r, v in zip(d["readings"][1:], list(values().values())[1:], strict=True):
        r.update(v)
    honest = copy.deepcopy(d)
    d["readings"][0].update(
        {"F": 40, "A0": 0, "B": 0, "A1": 0, "B1": 0, "m": 99, "verified_share": 1.0, "engine_items": 12, "own": {}}
    )
    spy = Spy(d["readings"][0])
    spy.read = set()
    d["readings"][0] = spy
    outcome, why = lh.judge(d)
    assert (outcome, why) == lh.judge(honest) and outcome == "buji"
    allowed = {*lh.TARGET_INPUTS, "verdict"}  # verdict 是判定函数自己刚写下的判，写理由时读回来
    assert spy.read <= allowed, spy.read - allowed
    assert spy.read & {"pairs", "target"} == {"pairs", "target"}


def test_the_target_dimension_cannot_be_filled_by_hand_with_an_arms_own_number():
    for bad in ({"F": 30}, {"A0": 12}, {"m": 20}, {"n": 4}):
        with pytest.raises(lh.StepError, match="只能填成对比较"):
            run(dossier(), {**values(), TARGET: {"pairs": values()[TARGET]["pairs"], **bad}})
    with pytest.raises(lh.StepError, match="成对比较只有"):
        run(dossier(), {**values(), TARGET: {"pairs": {**values()[TARGET]["pairs"], "F:X": SAME}}})
    with pytest.raises(lh.StepError, match="四格计数"):
        run(dossier(), values(fa0={"both": 1, "first": -1, "second": 0, "neither": 0}))
    with pytest.raises(lh.StepError, match="F:B 与 B:B1"):
        run(dossier(), {**values(), TARGET: {"pairs": {"F:A0": SAME}}})


# ---------------------------------------------------------------- 三只金丝雀


def test_three_canaries_are_judged_right():
    got = {name: lh._judge(copy.deepcopy(d), gate=True)[0] for name, d, _ in lh.canaries()}
    assert got == {"安慰剂": "binghuo", "退步": "fanshi", "封顶": "buji"}
    assert [want for _, _, want in lh.canaries()] == ["binghuo", "fanshi", "buji"]
    assert lh.misjudged_canaries() == []


@pytest.mark.parametrize(
    ("part", "broken", "wrong"),
    [
        ("noise_floor", lambda d: 99, "封顶"),  # 噪声底被放得过宽：看不出合火弱于原形
        ("_behind", lambda c: -99, "安慰剂"),  # 抖动被当成领先：两条相同的臂判出了胜
    ],
)
def test_a_judge_that_gets_a_canary_wrong_refuses_to_give_an_outcome(monkeypatch, part, broken, wrong):
    monkeypatch.setattr(lh, part, broken)
    assert wrong in lh.misjudged_canaries()
    with pytest.raises(lh.StepError, match="金丝雀判错了"):
        run(dossier(), values())


def test_a_judge_that_ignores_native_regressions_is_caught_too(monkeypatch):
    monkeypatch.setattr(lh, "_num", lambda x: 0.0 if isinstance(x, (int, float)) else None)
    assert "退步" in lh.misjudged_canaries()


# ---------------------------------------------------------------- 量具改动行数


def test_a_refinement_that_touches_the_measuring_tools_fails_the_trial():
    d = dossier()
    d["status"] = "design_approved"
    d = lh.yanti(d, 0, [], {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}, "abc1234", measure_lines=3)
    assert d["yanti"]["passed"] is False and d["measure_lines_changed"] == 3 and d["metrics"]["measure_lines"] == 3
    assert "量具改动行数：**3**（非 0" in lh.render(d)
    d = run(d, values())
    assert d["outcome_proposed"] == "fanshi" and "量具改动行数 3" in d["outcome_why"][0]


def test_measure_paths_exist_and_are_apart_from_the_kernel():
    for rel in lh.MEASURE_PATHS:
        assert (ROOT / rel).exists(), f"量具路径 {rel} 不在了：改了名就改这张表"
        assert not rel.startswith(lh.KERNEL_PATHS) and not any(k.startswith(rel) for k in lh.KERNEL_PATHS)
    assert "fenjue/src/paoding_fenjue/lianhua.py" in lh.MEASURE_PATHS  # 判定函数自己在线内


# ---------------------------------------------------------------- 按档号划的线


def test_the_line_is_drawn_by_dossier_number(monkeypatch):
    assert lh.YUANXING_GATE_FROM == "002"
    assert not lh.gated({"dossier": "001"}) and lh.gated({"dossier": "002"}) and lh.gated({"dossier": "017"})
    monkeypatch.setattr(lh, "YUANXING_GATE_FROM", None)
    assert not lh.gated({"dossier": "002"}) and not lh.gated({"dossier": "999"})


def test_a_dossier_before_the_line_is_judged_as_before():
    """划线之前的档号：同样的读数按旧规则判。没有原形臂照样可以是火莲，目标维的标记不起作用，量具行数只记不判。"""
    old = dossier("001", a0=False, parity=None)
    assert old["yanti"]["passed"] is True
    v = values(fa0=None)
    v[TARGET] = {"B": 20, "B1": 21, "A1": 20, "F": 20}
    d = run(old, v)
    assert d["outcome_proposed"] == "huolian" and "yuanxing_gate" not in d
    assert "原形门" not in lh.render(d) and "原形门" not in "".join(d["outcome_why"])
    old = dossier("001", a0=False, parity=None)
    old["status"] = "design_approved"
    old = lh.yanti(old, 0, [], {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}, "abc1234", measure_lines=3)
    assert old["yanti"]["passed"] is True


def test_setting_the_line_back_restores_todays_behaviour(monkeypatch):
    """把线调回去：同一份炼档、同一组读数，结局就是今天的判法给的那个（test_lianhua.py 整个文件也在这个设置下跑）。"""
    v = values(fa0=None)
    v[TARGET] = {"B": 20, "B1": 21, "A1": 20, "F": 20}
    monkeypatch.setattr(lh, "YUANXING_GATE_FROM", None)
    d = run(dossier("900", a0=False, parity=None), v)
    assert d["outcome_proposed"] == "huolian" and "yuanxing_gate" not in d
    assert [r["verdict"] for r in d["readings"]] == ["不退", "达门槛", "不退", "不退"]
