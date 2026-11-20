"""体质试炼清单本身的检查（焚决 F1）：表里每一项都还存在；五项各有测试；指名的测试函数在文件里。"""

from __future__ import annotations

import ast

from trials import ROOT, TRIALS, targets


def test_five_pillars_in_order():
    assert list(TRIALS) == ["T1", "T2", "T3", "T4", "T5"]
    assert [v[0] for v in TRIALS.values()] == ["判", "闸", "顶", "账", "证"]


def test_every_entry_exists():
    for n, (_, _, entries) in TRIALS.items():
        assert entries, n
        for e in entries:
            path, _, func = e.partition("::")
            p = ROOT / path
            assert p.exists(), f"{n}: {path} 不存在"
            if func:
                tree = ast.parse(p.read_text(encoding="utf-8"))
                names = {x.name for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)}
                assert func in names, f"{n}: {e} 找不到"


def test_targets_dedupes_and_rejects_unknown():
    assert len(targets([])) == len(set(targets([])))
    try:
        targets(["T9"])
    except SystemExit as e:
        assert "T9" in str(e)
    else:
        raise AssertionError("未知的体质项应当报错")
