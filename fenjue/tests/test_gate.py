"""原形门与新结局“不及原形”（现行设计第 4 节，第 1 步的 1a）：判定表逐格、噪声底、两个记号、三只金丝雀、
门的输入清单、按档号豁免、量具改动行数这条线。

这里的读数全是编的，只用来走判定函数的每一格；不调模型，也不读任何运行的产出。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from paoding_fenjue import lianhua as lh
from paoding_fenjue import readings, shapes

ROOT = Path(__file__).resolve().parents[2]
TODAY = "2026-11-27"
SHIHUO = {"source": "某系统（演示）", "phenomenon": "按题读仓库", "gap": "读不到题面问的地方", "is_fire": "是"}
CUIYI = {
    "yi": "题面决定读哪里",
    "premise": "题面里有问句",
    "cost": "调用数上升",
    "overlap": "通用勘察",
    "conflict": "无",
    "hypothesis": "按题读且逐条核对",
    "split": "无",
}
TARGET = {"dim": "留出题上的过线数", "kind": "异火", "dir": "up", "target": True}
NATIVE = {"dim": "凭据泄漏数", "kind": "本火", "dir": "down"}
COST = {"dim": "每题花费", "kind": "共有", "dir": "down"}
EMERGENT = {"dim": "结论可回放率", "kind": "新生", "dir": "up", "gate": 1}
ARMS = {"B": "本火", "B1": "本火再跑一遍", "A1": "照搬", "F": "合火", "A0": "原形本身，同一个模型"}
TRIALS_OK = {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}
OPEN = {"state": "可判"}


def cells(both: int, first: int, second: int, neither: int) -> dict[str, int]:
    return dict(zip(lh.CELLS, (both, first, second, neither), strict=True))


def pairs(f_b: tuple[int, int], f_a0: tuple[int, int] | None, f_a1: tuple[int, int] | None = (6, 0), d: int = 4):
    """成对计数：每一对给（只有前者过，只有后者过）；d 是本火对同火对照的不一致题次数，噪声底随它定。"""
    out = {"F_B": cells(20, f_b[0], f_b[1], 10), "B_B1": cells(30, d // 2, d - d // 2, 6)}
    if f_a0 is not None:
        out["F_A0"] = cells(20, f_a0[0], f_a0[1], 10)
    if f_a1 is not None:
        out["F_A1"] = cells(20, f_a1[0], f_a1[1], 10)
    return out


def draft(no: str) -> dict[str, Any]:
    f = copy.deepcopy(shapes.fire("h7.result"))
    f.update(id="h7.result-first", ver=1, lineage={"dossier": no, "from": ["h7.result"]})
    return f


def trialed(
    dims: list[dict[str, Any]],
    yuanxing: dict[str, Any] | None = OPEN,
    no: str = "900",
    arms: dict[str, str] | None = None,
    origin: str | None = None,
    gauge: int | None = 0,
    trials_ok: bool = True,
) -> dict[str, Any]:
    d = lh.cuiyi(lh.new(no, "x", "演示", TODAY, SHIHUO, origin=origin), CUIYI)
    d = lh.ruwei(d, draft(no), "h7.result", arms or ARMS, dims, yuanxing=yuanxing)
    d = lh.approve_design(d, "cz", TODAY)
    trials = {**TRIALS_OK, **({} if trials_ok else {"T2": {"ok": False, "summary": "1 failed"}})}
    return lh.yanti(d, 0, [], trials, "abc1234", gauge_lines=gauge)


GOOD = {"凭据泄漏数": {"B": 0, "F": 0}, "每题花费": {"B": 100, "B1": 104, "F": 102}}
DIMS = [TARGET, NATIVE, COST]


def run(values: dict[str, Any], dims: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
    return lh.ronghuo(trialed(dims or DIMS, **kw), {**GOOD, **values}, jie_now=2)


# ---------------------------------------------------------------- 噪声底


@pytest.mark.parametrize(("d", "m"), [(0, 1), (1, 2), (2, 3), (4, 4), (5, 5), (9, 6), (16, 8), (40, 13)])
def test_noise_floor_is_twice_the_root_rounded_up_and_at_least_one(d, m):
    assert lh.noise_floor(d) == m


# ---------------------------------------------------------------- 判定表逐格（现行设计 4.3）


def test_helian_when_fused_beats_both_sources_and_is_not_below_the_prototype():
    d = run({TARGET["dim"]: {"pairs": pairs(f_b=(8, 1), f_a0=(3, 5), f_a1=(7, 1))}})  # m = 4；对原形净差 −2
    assert d["outcome_proposed"] == "helian" and d["jie_proposed"] == 3
    assert d["yuanxing"]["result"] == "过" and lh.gate_mark(d) is None
    assert d["readings"][0]["verdict"] == "胜" and d["readings"][0]["gate_verdict"] == "不低于原形"


def test_huolian_needs_the_prototype_gate_too():
    dims = [TARGET, NATIVE, EMERGENT]
    values = {TARGET["dim"]: {"pairs": pairs((3, 2), (2, 4))}, EMERGENT["dim"]: {"B": 0, "A1": 0, "F": 1}}
    d = lh.ronghuo(trialed(dims), {"凭据泄漏数": {"B": 0, "F": 0}, **values}, 2)
    assert d["outcome_proposed"] == "huolian" and d["yuanxing"]["result"] == "过"


def test_exactly_at_the_noise_floor_still_passes():
    d = run({TARGET["dim"]: {"pairs": pairs(f_b=(8, 1), f_a0=(1, 5))}})  # 净差 −4，等于 −m：不低于原形减 m
    assert d["outcome_proposed"] == "helian" and d["yuanxing"]["result"] == "过"


def test_below_the_prototype_by_more_than_the_noise_floor_is_not_taken():
    d = run({TARGET["dim"]: {"pairs": pairs(f_b=(8, 1), f_a0=(1, 6))}})  # 净差 −5，m = 4
    assert d["outcome_proposed"] == "buji" and d["jie_proposed"] is None
    assert "buji" not in lh.TAKEN and lh.OUTCOMES["buji"] == "不及原形"
    assert d["yuanxing"]["result"] == "未过" and lh.gate_mark(d) == "原形门未过"
    assert d["yuanxing"]["short"] == [{"dim": TARGET["dim"], "by": 5, "m": 4.0}]  # 差在哪一维、差多少
    assert d["readings"][0]["gate_verdict"] == "不及原形"
    g0 = shapes._read("gongfa.json")
    d, g = lh.jue(d, g0, "cz", TODAY, "buji", [])
    assert d["status"] == "rejected" and g == g0  # 不收：功法不动
    assert "不及原形" in lh.render(d) and "原形门未过" in lh.render(d)


def test_a_wider_noise_floor_widens_the_gate_only_as_the_root():
    """本火很不稳定时门不会放得过宽：16 个不一致，允许差 8，不是 16（P7）。"""
    assert run({TARGET["dim"]: {"pairs": pairs((12, 1), (1, 9), (12, 1), d=16)}})["outcome_proposed"] == "helian"
    assert run({TARGET["dim"]: {"pairs": pairs((12, 1), (1, 10), (12, 1), d=16)}})["outcome_proposed"] == "buji"


def test_binghuo_and_fanshi_come_before_the_gate():
    """本来就不收的不到原形门：并火说的是融合没多出东西，反噬说的是底座退了，诊断不同，分开记。"""
    lost_to_proto = (0, 9)
    d = run({TARGET["dim"]: {"pairs": pairs(f_b=(3, 2), f_a0=lost_to_proto, f_a1=(3, 2))}})  # 没有一维胜出
    assert d["outcome_proposed"] == "binghuo" and "result" not in d["yuanxing"] and lh.gate_mark(d) is None
    d = run({TARGET["dim"]: {"pairs": pairs((1, 7), lost_to_proto)}})  # 异火维对本火退
    assert d["outcome_proposed"] == "binghuo"
    d = run({TARGET["dim"]: {"pairs": pairs((8, 1), lost_to_proto, f_a1=(1, 7))}})  # 异火维对照搬退
    assert d["outcome_proposed"] == "binghuo"
    d = run({TARGET["dim"]: {"pairs": pairs((8, 1), lost_to_proto)}, "凭据泄漏数": {"B": 0, "F": 1}})
    assert d["outcome_proposed"] == "fanshi"
    d = lh.ronghuo(trialed(DIMS, trials_ok=False), {**GOOD, TARGET["dim"]: {"pairs": pairs((8, 1), (5, 5))}}, 2)
    assert d["outcome_proposed"] == "fanshi" and d["outcome_why"] == ["验体没过"]


def test_every_foreign_dim_is_gated_and_scalar_dims_use_their_own_noise_floor():
    other = {"dim": "读得进的语言数", "kind": "异火", "dir": "up"}
    dims = [TARGET, other, NATIVE]
    base = {"凭据泄漏数": {"B": 0, "F": 0}, TARGET["dim"]: {"pairs": pairs((8, 1), (5, 5))}}
    ok = lh.ronghuo(trialed(dims), {**base, other["dim"]: {"B": 10, "B1": 10, "A1": 12, "F": 14, "A0": 14}}, 2)
    assert ok["outcome_proposed"] == "helian" and ok["yuanxing"]["result"] == "过"
    low = lh.ronghuo(trialed(dims), {**base, other["dim"]: {"B": 10, "B1": 11, "A1": 12, "F": 14, "A0": 16}}, 2)
    assert low["outcome_proposed"] == "buji" and [s["dim"] for s in low["yuanxing"]["short"]] == [other["dim"]]
    with pytest.raises(lh.StepError, match="还没有原形臂 A0"):
        lh.ronghuo(trialed(dims), {**base, other["dim"]: {"B": 10, "A1": 12, "F": 14}}, 2)
    with pytest.raises(lh.StepError, match="还没有原形臂 A0"):
        run({TARGET["dim"]: {"pairs": pairs((8, 1), None)}})


# ---------------------------------------------------------------- 两个记号（现行设计 4.4）


@pytest.mark.parametrize(
    "yuanxing",
    [{"state": "未判", "why": "原形适配的六条还不具备"}, None],
    ids=["登记为未判", "没有登记"],
)
def test_an_unjudged_gate_caps_the_outcome_at_helian_and_shows_a_mark(yuanxing):
    dims = [TARGET, NATIVE, EMERGENT]
    values = {
        "凭据泄漏数": {"B": 0, "F": 0},
        TARGET["dim"]: {"pairs": pairs((8, 1), None)},
        EMERGENT["dim"]: {"B": 0, "A1": 0, "F": 1},
    }
    d = lh.ronghuo(trialed(dims, yuanxing=yuanxing), values, 2)
    assert d["outcome_proposed"] == "helian"  # 本来够得上火莲：门没法判，最高合炼
    assert d["yuanxing"]["result"] == "未判" and lh.gate_mark(d) == "原形门未判"
    assert any("原形门未判" in w and "最高合炼" in w for w in d["outcome_why"])
    assert "原形门未判" in lh.render(d).splitlines()[4]  # 记号在炼档最上面的状态行里
    assert readings._dossier_row(d)["gate_mark"] == "原形门未判"  # 也到读端（能力页）


def test_marks_are_the_same_words_on_the_read_side():
    assert readings.GATE_MARKS == lh.MARKS and set(readings.OUTCOMES) == set(lh.OUTCOMES)


def test_the_gate_declaration_is_registered_at_placement_and_cannot_move():
    d = lh.cuiyi(lh.new("900", "x", "演示", TODAY, SHIHUO), CUIYI)
    f = draft("900")
    with pytest.raises(lh.StepError, match="只能是"):
        lh.ruwei(d, f, "h7.result", ARMS, DIMS, yuanxing={"state": "差不多"})
    with pytest.raises(lh.StepError, match="要写原因"):
        lh.ruwei(d, f, "h7.result", ARMS, DIMS, yuanxing={"state": "未判"})
    with pytest.raises(lh.StepError, match="原形臂 A0 是什么"):
        lh.ruwei(d, f, "h7.result", {k: v for k, v in ARMS.items() if k != "A0"}, DIMS, yuanxing=OPEN)
    with pytest.raises(lh.StepError, match="至少登记一个异火维"):
        lh.ruwei(d, f, "h7.result", ARMS, [NATIVE, COST], yuanxing=OPEN)
    with pytest.raises(lh.StepError, match="吸收目标维要是异火维"):
        lh.ruwei(d, f, "h7.result", ARMS, [{**COST, "target": True}])
    placed = lh.ruwei(d, f, "h7.result", ARMS, DIMS, yuanxing={"state": "未判", "why": "原形只能联网运行"})
    assert "| 原形门 | 未判：原形只能联网运行" in lh.render(placed)
    with pytest.raises(lh.StepError, match="不许改口"):  # 跑完发现能判了也不行：改设计、重新登记
        lh.ruwei(placed, f, "h7.result", ARMS, DIMS, yuanxing=OPEN)
    with pytest.raises(lh.StepError, match="原样带上"):
        lh.ruwei(placed, f, "h7.result", ARMS, DIMS)
    again = lh.ruwei(placed, f, "h7.result", ARMS, DIMS, yuanxing={"state": "未判", "why": "原形只能联网运行"})
    assert again["yuanxing"] == placed["yuanxing"]


# ---------------------------------------------------------------- 三只金丝雀（现行设计 9.3）


def test_canary_placebo_is_binghuo():
    """安慰剂：合火与本火完全相同。合火对本火的差落在噪声底里，没有任何一维胜出。"""
    same = pairs(f_b=(2, 2), f_a0=(2, 2), f_a1=(2, 2))
    d = run({TARGET["dim"]: {"pairs": same}, "每题花费": {"B": 100, "B1": 104, "F": 103}})
    assert d["outcome_proposed"] == "binghuo"


def test_canary_regression_is_fanshi():
    """退步：合火被故意削弱一项本火能力。"""
    d = run({TARGET["dim"]: {"pairs": pairs((9, 0), (5, 5))}, "凭据泄漏数": {"B": 0, "F": 2}})
    assert d["outcome_proposed"] == "fanshi"


def test_canary_capped_is_buji():
    """封顶：合火被故意限制，在吸收目标维上明显弱于原形；对本火与照搬都还赢着。"""
    d = run({TARGET["dim"]: {"pairs": pairs(f_b=(9, 0), f_a0=(0, 12), f_a1=(9, 0))}})
    assert d["outcome_proposed"] == "buji"


# ---------------------------------------------------------------- 门的输入清单（现行设计 5.5）


class Watched(dict[str, Any]):
    """记下判定函数读了这一维的哪些栏。"""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.seen: set[str] = set()

    def __getitem__(self, k: str) -> Any:
        self.seen.add(k)
        return super().__getitem__(k)

    def get(self, k: str, default: Any = None) -> Any:  # type: ignore[override]
        self.seen.add(k)
        return super().get(k, default)

    def __contains__(self, k: object) -> bool:
        self.seen.add(str(k))
        return super().__contains__(k)


def test_on_the_target_dim_the_judge_reads_only_the_blind_verdict_counts():
    """吸收目标维上，判定函数只读盲判的成对计数。它读了任何别的栏（各臂的标量、手填的噪声底、臂内部的
    核对标注与工单），这条测试就不过。"""
    d = run({TARGET["dim"]: {"pairs": pairs((8, 1), (1, 6))}})
    watched = Watched(d["readings"][0])
    # 往这一维里塞进各臂内部的东西与一套会翻盘的标量：判定不该看它们
    watched.update({"B": 0, "F": 99, "A0": 0, "A1": 0, "m": 1000, "engine_verified": 40, "open_tickets": 0})
    d["readings"][0] = watched
    outcome, _ = lh.judge(d)
    assert outcome == "buji"
    assert watched.seen <= {"dim", "kind", "pairs", "verdict", "gate_verdict"}, watched.seen


def test_the_target_dim_takes_counts_only_and_nothing_extra_gets_in():
    good = pairs((8, 1), (5, 5))
    with pytest.raises(lh.StepError, match="只收盲判的成对计数"):
        run({TARGET["dim"]: {"B": 20, "F": 30, "A0": 25}})
    with pytest.raises(lh.StepError, match="只收盲判的成对计数"):
        run({TARGET["dim"]: {"pairs": good, "m": 50}})  # 手填噪声底把门放宽：不收
    with pytest.raises(lh.StepError, match="多了"):
        run({TARGET["dim"]: {"pairs": {**good, "F_engine_verified": cells(1, 1, 1, 1)}}})
    with pytest.raises(lh.StepError, match="四格"):
        run({TARGET["dim"]: {"pairs": {**good, "F_A0": {**cells(1, 1, 1, 1), "未解决工单": 0}}}})
    with pytest.raises(lh.StepError, match="非负整数"):
        run({TARGET["dim"]: {"pairs": {**good, "F_A0": cells(1, -1, 1, 1)}}})
    with pytest.raises(lh.StepError, match="非负整数"):
        run({TARGET["dim"]: {"pairs": {**good, "F_A0": cells(1, True, 1, 1)}}})
    with pytest.raises(lh.StepError, match="还缺成对计数"):
        run({TARGET["dim"]: {"pairs": {k: v for k, v in good.items() if k != "B_B1"}}})
    with pytest.raises(lh.StepError, match="多了"):
        run({TARGET["dim"]: {"pairs": good, "tickets": 3}})
    ok = run({TARGET["dim"]: {"pairs": {**good, "F_B": {**good["F_B"], "配上对的题次数": 39}}, "note": "批次 7"}})
    assert ok["outcome_proposed"] == "helian"
    assert "| 合火对原形 | 20 | 5 | 5 | 10 |" in lh.render(ok)


# ---------------------------------------------------------------- 按档号划线


def test_dossier_001_is_exempt_and_passes_as_it_stands():
    """炼档 001 是设门之前手写的，没有原形臂：按档号豁免，不追溯。文件一个字不动，读端照旧给出它的结局，
    没有记号；它在功法里的那团火照旧通过炼档核对（tests/fenjue/test_dossiers.py）。"""
    path = next((ROOT / "docs/design/fenjue/dossiers").glob("001-*.json"))
    d = json.loads(path.read_text(encoding="utf-8"))
    assert not lh.gated(d) and "yuanxing" not in d and lh.gate_mark(d) is None
    row = readings._dossier_row(d)
    assert row["verdict"]["outcome"] == "huolian" and row["gate_mark"] is None and row["gauge_lines_changed"] is None
    assert d["verdict"]["outcome"] in lh.TAKEN
    assert d["dossier"] in {h.get("dossier") for h in shapes.gongfa()["history"]}


def test_the_line_is_a_dossier_number_and_moving_it_back_restores_the_old_rules(monkeypatch):
    assert lh.GATE_FROM == 2
    assert lh.gated({"dossier": "002"}) and lh.gated({"dossier": "137"}) and not lh.gated({"dossier": "001"})
    assert lh.gated({"dossier": "x-9"})  # 读不成数的档号不享受豁免
    dims = [TARGET, NATIVE, EMERGENT]
    values = {
        "凭据泄漏数": {"B": 0, "F": 0},
        TARGET["dim"]: {"B": 20, "B1": 21, "A1": 22, "F": 30, "A0": 60},
        EMERGENT["dim"]: {"B": 0, "A1": 0, "F": 1},
    }
    monkeypatch.setattr(lh, "GATE_FROM", None)
    d = lh.ronghuo(trialed(dims, yuanxing=None), values, 2)
    assert d["outcome_proposed"] == "huolian" and "yuanxing" not in d  # 远低于原形也照收：设门之前就是这样
    monkeypatch.setattr(lh, "GATE_FROM", 901)
    assert lh.ronghuo(trialed(dims, yuanxing=None), values, 2)["outcome_proposed"] == "huolian"


# ---------------------------------------------------------------- 量具改动行数（现行设计 9.4）


def test_gauge_lines_sit_beside_kernel_lines_and_fail_a_self_refined_dossier():
    values = {TARGET["dim"]: {"pairs": pairs((8, 1), (5, 5))}}
    clean = run(values, origin="自炼", gauge=0)
    assert clean["yanti"]["passed"] and clean["gauge_lines_changed"] == 0 and clean["metrics"]["gauge_lines"] == 0
    assert "量具改动行数：**0**" in lh.render(clean) and "| 出身 | 自炼 |" in lh.render(clean)
    dirty = run(values, origin="自炼", gauge=3)
    assert not dirty["yanti"]["passed"] and dirty["outcome_proposed"] == "fanshi"
    assert any("量具改动行数 3" in e for e in dirty["yanti"]["static_errors"])
    by_hand = run(values, origin="手工", gauge=3)  # 手工的照实记，不因此不过：量具的改动本来就单独提
    assert by_hand["yanti"]["passed"] and by_hand["gauge_lines_changed"] == 3
    assert "量具改动行数：**3**（非 0" in lh.render(by_hand)
    assert readings._dossier_row(by_hand)["gauge_lines_changed"] == 3
    unset = run(values, gauge=None)  # 不给就不记：设这条线之前的炼档形状不变
    assert "gauge_lines" not in unset["yanti"] and "gauge_lines_changed" not in unset
    with pytest.raises(lh.StepError, match="出身只能是"):
        lh.new("900", "x", "演示", TODAY, SHIHUO, origin="捡来的")


def test_gauge_paths_are_real_cover_the_judge_itself_and_do_not_overlap_the_kernel():
    assert "fenjue/src/paoding_fenjue/lianhua.py" in lh.GAUGE_PATHS and "scripts/lianhua.py" in lh.GAUGE_PATHS
    missing = {p for p in lh.GAUGE_PATHS if not (ROOT / p).exists()}
    assert missing <= {"liangju/"}  # 引擎之外的量具随第 0 步合入
    for g in lh.GAUGE_PATHS:
        for k in lh.KERNEL_PATHS:
            assert not g.startswith(k) and not k.startswith(g)
    # 炼档自己不在量具路径里：每一步都要写它
    assert not any("docs/design/fenjue/dossiers".startswith(p.rstrip("/")) for p in lh.GAUGE_PATHS)
