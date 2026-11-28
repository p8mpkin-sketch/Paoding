"""炼化命令（scripts/lianhua.py，焚决 F5）：在一份炼档目录与功法的副本上，把识火到散火的每条命令走一遍。

跑体质试炼与 git 的那几处换成假的（它们各自在 trials.py 与 CI 里测）；这里测的是命令把每一步写进了 JSON、
.md 由 JSON 生成、定阶改了功法、散火改了回来。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from paoding_fenjue import lianhua as lh

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("lianhua_cli", ROOT / "scripts" / "lianhua.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dossiers = tmp_path / "dossiers"
    shutil.copytree(ROOT / "docs/design/fenjue/dossiers", dossiers)
    for extra in dossiers.glob("[0-9][0-9][0-9]-*"):  # 这里的断言按“仓库里只有记录 001”写的：之后开的记录不带进来
        if not extra.name.startswith("001-"):
            extra.unlink()
    pkg = tmp_path / "pkg"
    shutil.copytree(ROOT / "fenjue/src/paoding_fenjue/fires", pkg / "fires")
    shutil.copytree(ROOT / "fenjue/src/paoding_fenjue/archive", pkg / "archive")
    shutil.copy(ROOT / "fenjue/src/paoding_fenjue/gongfa.json", pkg / "gongfa.json")
    monkeypatch.setattr(mod, "DOSSIERS", dossiers)
    monkeypatch.setattr(mod, "PKG", pkg)
    monkeypatch.setattr(mod, "GONGFA", pkg / "gongfa.json")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_run", lambda cmd, g: (True, "12 passed"))
    monkeypatch.setattr(mod, "kernel_lines", lambda base: 0)
    monkeypatch.setattr(mod, "measure_lines", lambda base: 0)
    monkeypatch.setattr(mod, "_git", lambda *a: "abc1234")
    monkeypatch.setattr(mod, "candidate", lambda d: tmp_path / "cand.json")
    return mod, dossiers, pkg


def run(mod, *argv):
    assert mod.main([str(a) for a in argv]) == 0


def test_a_dossier_goes_from_shihuo_to_sanhuo_without_hand_writing(cli, tmp_path, capsys, monkeypatch):
    mod, dossiers, pkg = cli
    monkeypatch.setattr(lh, "YUANXING_GATE_FROM", None)  # 这一条走的是命令本身，写在原形门之前；门的走法见下一条
    run(mod, "new", "result-first", "--title", "结论先行", "--source", "演示", "--phenomenon", "结论先于过程",
        "--gap", "结果页先列过程", "--is-fire", "是：一类呈现做法", "--date", "2026-11-21")  # fmt: skip
    no = "002"
    assert (dossiers / f"{no}-result-first.json").exists()
    run(mod, "cuiyi", no, "--yi", "结论先行", "--premise", "结论可信", "--cost", "过程折叠", "--overlap", "H7",
        "--conflict", "T5", "--hypothesis", "结论先行且一键到留档", "--split", "无", "--masked", "成立")  # fmt: skip
    f = json.loads((pkg / "fires" / "h7.result.json").read_text(encoding="utf-8"))
    f.update(id="h7.result-first", ver=1, lineage={"dossier": no, "from": ["h7.result"]})
    (tmp_path / "draft.json").write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    reading = {
        "dim": "结论可追率",
        "kind": "新生",
        "dir": "up",
        "gate": 1,
        "test": "fenjue/tests/test_lianhua.py::test_walk",
    }
    run(mod, "ruwei", no, "--fire", tmp_path / "draft.json", "--replaces", "h7.result", "--arm", "B=原样",
        "--arm", "A1=只挪结论", "--arm", "F=合火", "--reading", json.dumps(reading, ensure_ascii=False))  # fmt: skip
    assert (pkg / "fires" / "h7.result-first.json").exists()  # 清单草稿进包，还不在功法里
    assert "h7.result-first@1" not in json.dumps(json.loads((pkg / "gongfa.json").read_text(encoding="utf-8")))
    assert mod.main(["yanti", no]) == 2  # 设计还没裁：做不了
    run(mod, "approve", no, "--by", "cz", "--date", "2026-11-21")
    run(mod, "yanti", no)
    run(mod, "ronghuo", no, "--set", "结论可追率:B=0", "--set", "结论可追率:A1=0", "--run-tests")
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    assert d["status"] == "readings_ready" and d["outcome_proposed"] == "huolian"
    run(mod, "status")
    assert "下一步：jue" in capsys.readouterr().out
    kept = len(list((pkg / "archive/gongfa").iterdir()))  # 已存档的功法版本数（随本火修订增长，不写死）
    run(mod, "jue", no, "--by", "cz", "--outcome", "huolian", "--condition", "演示", "--date", "2026-11-21")
    g = json.loads((pkg / "gongfa.json").read_text(encoding="utf-8"))
    assert "h7.result-first@1" in g["fires"]["H7"] and g["holdout"]["H7"] == ["h7.result@1"] and g["jie"] == 3
    # 定阶先存档（FJ6）：新功法与新火进了存档，旧的一份不少
    assert (pkg / "archive/fires/h7.result-first@1.json").exists()
    # 每定一阶存两份：主功法，与由它推出的分析实例功法（13 §2；分析实例开的题锁在后者上）
    assert len(list((pkg / "archive/gongfa").iterdir())) == kept + 2
    e = json.loads((pkg / "gongfa.engine.json").read_text(encoding="utf-8"))
    assert e["variant"] == "engine" and e["jie"] == 3 and e["fires"]["H7"] == g["fires"]["H7"]
    assert "h1.tunshi@2" in e["fires"]["H1"] and "h3.tunshi-tools@1" in e["fires"]["H3"]
    md = (dossiers / f"{no}-result-first.md").read_text(encoding="utf-8")
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    assert md == lh.render(d) and "| 结局 | 火莲 |" in md
    run(mod, "sanhuo", no, "--by", "cz", "--why", "演示散火", "--date", "2026-11-21")
    g = json.loads((pkg / "gongfa.json").read_text(encoding="utf-8"))
    assert "h7.result@1" in g["fires"]["H7"] and g["jie"] == 2 and g["history"][-1]["reverts"] == no
    assert len(list((pkg / "archive/gongfa").iterdir())) == kept + 4  # 散火后的两份也存档；在跑的题仍取得到定阶那一版
    e = json.loads((pkg / "gongfa.engine.json").read_text(encoding="utf-8"))
    assert e["jie"] == 2 and e["fires"]["H7"] == g["fires"]["H7"]
    run(mod, "archive")  # 已经存过：不动
    assert len(list((pkg / "archive/gongfa").iterdir())) == kept + 4
    # 手写的首炼档，命令不碰
    with pytest.raises(SystemExit, match="手写"):
        mod.load("001")


def test_the_commands_carry_the_prototype_gate(cli, tmp_path, monkeypatch):
    """过了划线的炼档（03 §3.1）：入位时登记原形臂、对等声明与吸收目标维；验体数出量具改动行数；融火时目标维
    只收成对比较的四格计数；合火在目标维上明显弱于原形，结局提议是不及原形，裁决后不收、功法不动。"""
    mod, dossiers, pkg = cli
    g0 = (pkg / "gongfa.json").read_text(encoding="utf-8")
    run(mod, "new", "result-first", "--title", "结论先行", "--source", "演示", "--phenomenon", "结论先于过程",
        "--gap", "结果页先列过程", "--is-fire", "是：一类呈现做法", "--date", "2026-11-28")  # fmt: skip
    no = "002"
    run(mod, "cuiyi", no, "--yi", "结论先行", "--premise", "结论可信", "--cost", "过程折叠", "--overlap", "H7",
        "--conflict", "T5", "--hypothesis", "结论先行且一键到留档", "--split", "无", "--masked", "成立")  # fmt: skip
    f = json.loads((pkg / "fires" / "h7.result.json").read_text(encoding="utf-8"))
    f.update(id="h7.result-first", ver=1, lineage={"dossier": no, "from": ["h7.result"]})
    (tmp_path / "draft.json").write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    readings = [
        {"dim": "留出题上的过线数", "kind": "异火", "dir": "up", "target": True, "n": 40},
        {"dim": "结论可追率", "kind": "新生", "dir": "up", "gate": 1},
    ]
    (tmp_path / "readings.json").write_text(json.dumps(readings, ensure_ascii=False), encoding="utf-8")
    run(mod, "ruwei", no, "--fire", tmp_path / "draft.json", "--replaces", "h7.result", "--arm", "B=原样",
        "--arm", "B1=原样再跑一遍", "--arm", "A1=只挪结论", "--arm", "F=合火", "--arm", "A0=原形",
        "--readings", tmp_path / "readings.json", "--parity", "equal")  # fmt: skip
    assert mod.main(["approve", no, "--by", "cz", "--waive-gate", "想降为参考"]) == 2  # 登记的是对等：谈不上豁免
    run(mod, "approve", no, "--by", "cz", "--date", "2026-11-28")
    monkeypatch.setattr(mod, "measure_lines", lambda base: 2)
    run(mod, "yanti", no)
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    assert d["yanti"]["passed"] is False and d["measure_lines_changed"] == 2  # 夹带了量具的改动：验体不过
    monkeypatch.setattr(mod, "measure_lines", lambda base: 0)
    run(mod, "yanti", no)
    same = {"both": 30, "first": 3, "second": 3, "neither": 4}
    behind = {"both": 24, "first": 1, "second": 12, "neither": 3}
    pairs = {"B:B1": same, "F:B": same, "F:A1": same, "F:A0": behind}
    values = {"留出题上的过线数": {"pairs": pairs}, "结论可追率": {"B": 0, "A1": 0, "F": 1}}
    (tmp_path / "values.json").write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    assert mod.main(["ronghuo", no, "--values", str(tmp_path / "values.json"), "--set", "留出题上的过线数:F=40"]) == 2
    run(mod, "ronghuo", no, "--values", tmp_path / "values.json")
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    assert d["outcome_proposed"] == "buji" and d["jie_proposed"] is None and d["yuanxing_gate"]["state"] == "failed"
    run(mod, "jue", no, "--by", "cz", "--outcome", "buji", "--date", "2026-11-28")
    md = (dossiers / f"{no}-result-first.md").read_text(encoding="utf-8")
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    assert md == lh.render(d) and "| 结局 | 不及原形 |" in md and "原形门未过" in md and "| 原形臂的条件 | 对等 |" in md
    assert d["status"] == "rejected" and (pkg / "gongfa.json").read_text(encoding="utf-8") == g0


def test_the_commands_carry_the_trial_plan_and_record(cli, tmp_path):
    """划线之后的炼档（03 §4、§5）：设计裁决之前登记试火计划；融火只收试火记录，手填被拒；
    定阶要给同一份记录，人给的结局高于系统判出的被拒。"""
    mod, dossiers, pkg = cli
    no = "003"
    run(mod, "new", "result-first", "--no", no, "--title", "结论先行", "--source", "演示",
        "--phenomenon", "结论先于过程", "--gap", "结果页先列过程", "--is-fire", "是：一类呈现做法",
        "--date", "2026-11-28", "--origin", "自炼")  # fmt: skip
    run(mod, "cuiyi", no, "--yi", "结论先行", "--premise", "结论可信", "--cost", "过程折叠", "--overlap", "H7",
        "--conflict", "T5", "--hypothesis", "结论先行且一键到留档", "--split", "无", "--masked", "成立")  # fmt: skip
    f = json.loads((pkg / "fires" / "h7.result.json").read_text(encoding="utf-8"))
    f.update(id="h7.result-first", ver=1, lineage={"dossier": no, "from": ["h7.result"]})
    (tmp_path / "draft.json").write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    readings = [
        {"dim": "留出题上的过线数", "kind": "异火", "dir": "up", "target": True, "n": 4},
        {"dim": "结论可追率", "kind": "新生", "dir": "up", "gate": 1},
    ]
    (tmp_path / "readings.json").write_text(json.dumps(readings, ensure_ascii=False), encoding="utf-8")
    run(mod, "ruwei", no, "--fire", tmp_path / "draft.json", "--replaces", "h7.result", "--arm", "B=原样",
        "--arm", "B1=原样再跑一遍", "--arm", "F=合火", "--readings", tmp_path / "readings.json",
        "--parity", "equal")  # fmt: skip
    assert mod.main(["approve", no, "--by", "cz"]) == 2  # 还没有登记试火计划
    arm = {
        "model": "m-main",
        "version": "v1",
        "endpoint": "proxy",
        "sampling": {},
        "meter": "ledger",
        "price_table": "t@1",
    }
    plan = {
        "dossier": no,
        "arms": {a: {"what": a, **arm} for a in ("B", "B1", "F")},
        "judge": {
            "model": "",
            "version": "v1",
            "prompts": "p@1",
            "sample": {"per_sub": 2, "max": 8},
            "seconds_per_item": 60,
        },  # fmt: skip
        "questions": {"set": "S1", "digest": "q" * 64, "source": "手出", "count": 2, "runs": 2},
        "trial_segment": {"batch": "T0-1", "median_cost_usd_milli": 10, "median_seconds": 60},
        "caps": {"per_item_usd_milli": 30, "total_usd_milli": 30 * 2 * 3 * 2},
        "seed": "s1",
    }
    (tmp_path / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert mod.main(["plan", no, "--file", str(tmp_path / "plan.json")]) == 2  # 盲判的模型栏空着
    plan["judge"]["model"] = "m-judge"
    (tmp_path / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    run(mod, "plan", no, "--file", tmp_path / "plan.json")
    run(mod, "approve", no, "--by", "cz", "--date", "2026-11-28")
    run(mod, "yanti", no)
    items = [
        {"arm": a, "q": q, "run": n, "passed": True, "cost_usd_milli": 10, "task": f"{a}{q}{n}", "log_head": "h"}
        for a in plan["arms"] for q in ("q1", "q2") for n in (1, 2)
    ]  # fmt: skip
    from paoding_fenjue import shihuo

    record = {
        "plan_hash": shihuo.digest(plan), "purpose": "判定", "status": "complete",
        "arms": {a: {"digest": "d", "model": "m-main", "version": "v1"} for a in plan["arms"]},
        "questions": {"set": "S1", "digest": "q" * 64},
        "judge": {"model": "m-judge", "version": "v1", "prompts": "p@1"},
        "items": items, "readings": {"结论可追率": {"B": 0, "F": 1}}, "cost": {"total_usd_milli": 120},
    }  # fmt: skip
    (tmp_path / "record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    assert mod.main(["ronghuo", no, "--set", "结论可追率:F=1"]) == 2  # 手填的入口关掉了
    run(mod, "ronghuo", no, "--record", tmp_path / "record.json")
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    assert d["outcome_proposed"] == "helian" and d["yuanxing_gate"]["state"] == "unjudged"  # 没有原形臂：最高合炼
    assert mod.main(["jue", no, "--by", "cz", "--outcome", "helian"]) == 2  # 没给记录
    assert mod.main(["jue", no, "--by", "cz", "--outcome", "huolian", "--record", str(tmp_path / "record.json")]) == 2
    run(
        mod,
        "jue",
        no,
        "--by",
        "cz",
        "--outcome",
        "helian",
        "--record",
        tmp_path / "record.json",
        "--date",
        "2026-11-28",
    )
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    md = (dossiers / f"{no}-result-first.md").read_text(encoding="utf-8")
    assert d["status"] == "adopted" and d["verdict"]["system"] == "helian" and md == lh.render(d)
    assert "试火计划（登记之后不能改" in md and "读数出自试火记录" in md and "| 系统判出的结局 | 合炼 |" in md


def test_the_archive_only_grows(cli):
    """存档只增不改：清单改了内容却没升 ver，存档命令停下。"""
    mod, _, pkg = cli
    p = pkg / "fires" / "h7.result.json"
    f = json.loads(p.read_text(encoding="utf-8"))
    f["params"] = {**f["params"], "偷改": 1}
    p.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="只增不改"):
        mod.main(["archive"])
