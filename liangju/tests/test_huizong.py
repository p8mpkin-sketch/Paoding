"""汇总：过线三条、成对比较与噪声底、按轴分层、不带出任何内容。"""

import argparse
import json

import pytest
from lj_rig import ARMS, CANARY, attempt, make_batch, simple

from liangju import huizong, mangpan, pici
from liangju.common import Refused, read_json, write_json


@pytest.mark.parametrize(("d", "m"), [(0, 1), (1, 2), (2, 3), (4, 4), (9, 6), (16, 8), (17, 9)])
def test_noise_floor(d, m):
    assert huizong.noise_floor(d) == m


def judged(tmp_path, monkeypatch, atts, **batch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    bdir, qpath, jpath = make_batch(tmp_path, atts, **batch)
    a = argparse.Namespace(batch=str(bdir), questions=str(qpath), judge=str(jpath), selfcheck=None, jobs=1)
    assert mangpan.run_judge(a, simple()) == 0
    return bdir, qpath


GOOD, HALF, WRONG = "1: 甲 SENTINEL_ANSWER\n2: 乙", "1: 甲\n2: 只说了一半", "1: 甲\n2: 这条是错的"


def test_pass_needs_all_three_and_pairs_are_counted_per_attempt(tmp_path, monkeypatch):
    atts = [
        attempt("B", "q1", 1, GOOD),
        attempt("B2", "q1", 1, GOOD),  # 两边都过
        attempt("B", "q1", 2, GOOD),
        attempt("B2", "q1", 2, HALF),  # 只有前者过（后者没答到）
        attempt("B", "q2", 1, WRONG),
        attempt("B2", "q2", 1, GOOD),  # 只有后者过（前者不属实）
        attempt("B", "q2", 2, GOOD, cost_usd_milli=101),
        attempt("B2", "q2", 2, GOOD),  # 只有后者过（前者超出上限）
        attempt("B", "q3", 1, None, status="watchdog"),
        attempt("B2", "q3", 1, GOOD, status="over_budget"),  # 都没过
        attempt("B", "q3", 2, GOOD),  # 没有配上对的不进成对比较
    ]
    atts[0].own["engine_items"] = [{"text": "甲 SENTINEL_ANSWER", "verdict": "supported"}]
    atts[4].own["engine_items"] = [
        {"text": "这条是错的", "verdict": "supported"},
        {"text": "甲", "verdict": "unverified"},
    ]
    atts[2].own["timeline_stop"] = True
    bdir, qpath = judged(tmp_path, monkeypatch, atts)
    doc = huizong.build(bdir, qpath)
    pair = doc["成对比较"]["本火对同火对照"]
    assert pair == {
        "两边都过": 1,
        "只有前者过": 1,
        "只有后者过": 2,
        "两边都没过": 1,
        "配上对的题次数": 5,
        "不一致数 d": 3,
        "噪声底 m": 4,
    }
    b = next(x for x in doc["每条臂一组"] if x["臂"] == "B")
    assert b["题次数"] == 6 and b["过线的题次数"] == 3 and b["每次都过线的题数"] == 1
    assert b["三条各自满足的题次数"] == {"答到": 5, "属实": 4, "在预算内完成": 4}
    assert b["子问计数"]["答到"] == 10 and b["抽样核对"] == {"抽了": 10, "成立": 9, "被原文否定": 1, "找不到依据": 0}
    assert b["没完成的题次数"]["看门狗超时"] == 1 and b["花费（毫美元，同一张价表折算）"]["每题次最大值"] == 101
    own = b["只报告、不进门"]
    assert own["因时间线停下的题次数"] == 1 and own["引擎标为已核对而被盲判抽样否定（否定数/抽到数）"] == "1/2"
    b2 = next(x for x in doc["每条臂一组"] if x["臂"] == "B2")
    assert b2["没完成的题次数"]["超出预算"] == 1 and b2["过线的题次数"] == 3
    assert doc["发现与类别"]["发现记录数"] == {
        "部分答到": 1,
        "没答到": 0,
        "被原文否定": 1,
        "找不到依据": 0,
        "没完成或超出预算": 3,
        "合计": 5,
    }
    assert doc["完整性"]["运行期间代码与配置是否改动过"] == "否"
    assert all(r["运行记录里读回的模型标识与登记一致"] for r in doc["逐臂登记"]["各臂"])


def test_plan_cap_overrides_the_runs_own_cap_and_changes_are_reported(tmp_path, monkeypatch):
    atts = [attempt("B", "q1", 1, GOOD, models_seen=["别的模型"]), attempt("B2", "q1", 1, GOOD, gongfa="另一版")]
    caps = {"per_question_usd_milli": 40, "total_usd_milli": None}
    end = {"commit": "c2", "dirty": False, "config_digest": "d1"}
    bdir, qpath = judged(tmp_path, monkeypatch, atts, caps=caps, end=end)
    doc = huizong.build(bdir, qpath)
    assert doc["批次头"]["每题上限的来源"] == "试火计划"
    assert [x["过线的题次数"] for x in doc["每条臂一组"]] == [0, 0]  # 花费 50 超过计划里的 40
    assert doc["完整性"]["运行期间代码与配置是否改动过"].startswith("是")
    assert doc["完整性"]["各题次的功法摘要是否一致"] is False
    assert [r["运行记录里读回的模型标识与登记一致"] for r in doc["逐臂登记"]["各臂"]] == [False, True]


def test_axes_merge_small_cells(tmp_path, monkeypatch):
    qs = [
        {
            "id": f"q{i}",
            "text": "t",
            "subquestions": ["a", "b"],
            "snapshot": str(CANARY / "snapshot"),
            "axes": {"language": "python" if i <= 3 else "go"},
        }
        for i in range(1, 5)
    ]
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    atts = [attempt("B", f"q{i}", 1, GOOD if i != 4 else HALF) for i in range(1, 5)]
    bdir, qpath, jpath = make_batch(tmp_path, atts, questions=qs)
    a = argparse.Namespace(batch=str(bdir), questions=str(qpath), judge=str(jpath), selfcheck=None, jobs=1)
    mangpan.run_judge(a, simple())
    axes = huizong.build(bdir, qpath)["按轴分层（过线题次/题次）"]
    assert axes["语言"]["B"] == {"python": "3/3", "其他": "0/1"}  # 只有一道 go 题：并进「其他」
    assert axes["问法"]["B"] == {"未标": "3/4"}


def test_summary_carries_no_content(tmp_path, monkeypatch):
    """题面、子问、回答原文、路径、发现记录里的自由文字与证据指针，都不进汇总。"""
    atts = [attempt("B", "q1", 1, GOOD), attempt("B2", "q1", 1, WRONG), attempt("B", "q2", 1, HALF)]
    bdir, qpath = judged(tmp_path, monkeypatch, atts)
    assert huizong.main(["--batch", str(bdir), "--questions", str(qpath)]) == 0
    for name in ("summary.json", "summary.md"):
        text = (bdir / name).read_text(encoding="utf-8")
        for banned in (
            "SENTINEL",
            "题面1",
            "子问甲",
            "relay/",
            "config.py",
            "把缺省值说成",
            "只说了一半",
            str(tmp_path),
        ):
            assert banned not in text, (name, banned)
    md = (bdir / "summary.md").read_text(encoding="utf-8")
    assert "## 批次头" in md and "## 成对比较" in md and "盲判三段的版本" in md


def test_unregistered_arm_and_empty_batch_are_refused(tmp_path, monkeypatch):
    bdir, qpath = judged(tmp_path, monkeypatch, [attempt("B", "q1", 1, GOOD)])
    write_json(bdir / "batch.json", {**read_json(bdir / "batch.json"), "arms": {"B2": ARMS["B2"]}})
    with pytest.raises(Refused):
        huizong.build(bdir, qpath)
    assert huizong.main(["--batch", str(tmp_path / "空的"), "--questions", str(qpath)]) == 2


def test_batch_header_registration(tmp_path):
    arms = tmp_path / "arms.json"
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("x: 1\n")
    base = [
        "start",
        "--batch",
        str(tmp_path / "b"),
        "--id",
        "S0-1",
        "--purpose",
        "起点轮",
        "--arms",
        str(arms),
        "--config",
        str(cfg),
        "--set-code",
        "SET-A",
        "--set-source",
        "手出",
    ]
    write_json(arms, {"B": {**ARMS["B"], "model": ""}})
    assert pici.main(base) == 2 and not (tmp_path / "b" / "batch.json").exists()  # 模型栏空着：不登记
    write_json(arms, ARMS)
    assert pici.main(base) == 0 and pici.main(base) == 2  # 一个批次只登记一次
    doc = read_json(tmp_path / "b" / "batch.json")
    assert doc["parallel"] == 4 and doc["runs_per_question"] == 2 and doc["end"] is None
    assert len(doc["start"]["commit"]) == 40 and doc["yuanxing_gate"].startswith("未判")
    assert pici.main(["end", "--batch", str(tmp_path / "b"), "--config", str(cfg)]) == 0
    assert read_json(tmp_path / "b" / "batch.json")["end"]["config_digest"] == doc["start"]["config_digest"]
