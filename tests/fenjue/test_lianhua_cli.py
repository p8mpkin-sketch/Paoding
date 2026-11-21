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
    monkeypatch.setattr(mod, "_git", lambda *a: "abc1234")
    monkeypatch.setattr(mod, "candidate", lambda d: tmp_path / "cand.json")
    return mod, dossiers, pkg


def run(mod, *argv):
    assert mod.main([str(a) for a in argv]) == 0


def test_a_dossier_goes_from_shihuo_to_sanhuo_without_hand_writing(cli, tmp_path, capsys):
    mod, dossiers, pkg = cli
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
    run(mod, "jue", no, "--by", "cz", "--outcome", "huolian", "--condition", "演示", "--date", "2026-11-21")
    g = json.loads((pkg / "gongfa.json").read_text(encoding="utf-8"))
    assert "h7.result-first@1" in g["fires"]["H7"] and g["holdout"]["H7"] == ["h7.result@1"] and g["jie"] == 3
    # 定阶先存档（FJ6）：新功法与新火进了存档，旧的一份不少
    assert (pkg / "archive/fires/h7.result-first@1.json").exists()
    assert len(list((pkg / "archive/gongfa").iterdir())) == 3
    md = (dossiers / f"{no}-result-first.md").read_text(encoding="utf-8")
    d = json.loads((dossiers / f"{no}-result-first.json").read_text(encoding="utf-8"))
    assert md == lh.render(d) and "| 结局 | 火莲 |" in md
    run(mod, "sanhuo", no, "--by", "cz", "--why", "演示散火", "--date", "2026-11-21")
    g = json.loads((pkg / "gongfa.json").read_text(encoding="utf-8"))
    assert "h7.result@1" in g["fires"]["H7"] and g["jie"] == 2 and g["history"][-1]["reverts"] == no
    assert len(list((pkg / "archive/gongfa").iterdir())) == 4  # 散火后的功法也存档；在跑的题仍取得到定阶那一版
    run(mod, "archive")  # 已经存过：不动
    assert len(list((pkg / "archive/gongfa").iterdir())) == 4
    # 手写的首炼档，命令不碰
    with pytest.raises(SystemExit, match="手写"):
        mod.load("001")


def test_the_archive_only_grows(cli):
    """存档只增不改：清单改了内容却没升 ver，存档命令停下。"""
    mod, _, pkg = cli
    p = pkg / "fires" / "h7.result.json"
    f = json.loads(p.read_text(encoding="utf-8"))
    f["params"] = {**f["params"], "偷改": 1}
    p.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="只增不改"):
        mod.main(["archive"])
