"""表项计数：数法固定，只读源码，初值可比。"""

import json
import shutil

import lj_rig  # noqa: F401  把仓库根放进导入路径
import pytest

from liangju import biaoxiang
from liangju.common import read_json


def tree(tmp, extra=""):
    eng = tmp / biaoxiang.ENGINE
    (eng / "tables").mkdir(parents=True)
    (tmp / biaoxiang.PROMPTS).mkdir(parents=True)
    (eng / "a.py").write_text(
        "import re\n"
        'WORDS = {"怎么", "如何", "how"}\n'
        'ONE = ("只有一个",)\n'
        "THETA = 0.2\n"
        "NEG = -3\n"
        'WEIGHTS = {"lex": 0.35, "doc": 0.20}\n'
        'NAME = "不是门槛"\n'
        "class Limits:\n"
        "    cap: int = 85\n"
        "    share: float = 0.5\n"
        '    label: str = "x"\n'
        'PAT = re.compile(r"\\d+")\n'
        "def f(s, p):\n"
        "    local = 7\n"
        '    return re.search("a|b", s) or re.sub(p, "", s)\n' + extra,
        encoding="utf-8",
    )
    (eng / "tables" / "t.json").write_text(
        json.dumps({"k": ["甲", "乙", 3], "on": True, "x": {"y": 0.5}}), encoding="utf-8"
    )
    (tmp / biaoxiang.PROMPTS / "tunshi-x.md").write_text(
        "你必须这样。\n随便写。\n至多三条，不得多写。\n", encoding="utf-8"
    )
    (tmp / biaoxiang.PROMPTS / "solve.md").write_text("必须\n", encoding="utf-8")  # 不是引擎的提示词：不数
    return tmp


def test_counting_rule(tmp_path):
    got = biaoxiang.count(tree(tmp_path))
    # 词表：WORDS 3 + WEIGHTS 的两个键 2 + 表里 2 = 7（只有一个字符串的元组不算词表）
    # 正则：compile 与 search 两处字面量模式（模式是变量的 re.sub 不数）
    # 门槛：THETA、NEG、WEIGHTS 的两个值、cap、share = 6，加表里的 3 与 0.5 = 8（函数里的局部量不数，布尔不数）
    assert got["totals"] == {"词表条目": 7, "正则": 2, "门槛常量": 8, "提示词里的硬规则": 2}
    assert got["rule"] == biaoxiang.RULE and len(got["digest"]) == 64


def test_check_reports_growth_only(tmp_path):
    base = biaoxiang.count(tree(tmp_path / "a"))
    more = biaoxiang.count(tree(tmp_path / "b", 'EXTRA = 9\nMORE = {"x", "y"}\n'))
    assert biaoxiang.check(base, base) == [] and biaoxiang.check(base, more) == []  # 少了不报
    grown = biaoxiang.check(more, base)
    assert len(grown) == 2 and "门槛常量" in grown[1] and "多了 1" in grown[1]
    assert "不能比" in biaoxiang.check({**more, "rule": "2"}, base)[0]


def test_committed_baseline_is_readable_and_uses_the_current_rule():
    base = read_json(biaoxiang.ROOT / "liangju" / "baseline" / "biaoxiang.json")
    assert base["rule"] == biaoxiang.RULE and set(base["totals"]) == set(biaoxiang.CATEGORIES)
    assert biaoxiang.main(["--root", str(biaoxiang.ROOT)]) == 0


BASELINE = biaoxiang.ROOT / "liangju" / "baseline" / "biaoxiang.json"
CI_STEP = "python -m liangju.biaoxiang --check liangju/baseline/biaoxiang.json"


def test_ci_runs_the_check_against_the_committed_baseline():
    """持续集成里有这一步，不带条件（推送与合并请求都跑），对的是仓库里那份初值文件。"""
    ci = (biaoxiang.ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    step = next(b for b in ci.split("      - name: ") if CI_STEP in b)
    assert "if:" not in step and "continue-on-error" not in ci
    assert biaoxiang.main(["--check", str(BASELINE)]) == 0  # 现在的仓库对初值：不红


@pytest.mark.parametrize(
    ("where", "added", "category"),
    [
        ("engine", 'LIANGJU_SELFTEST_WORDS = {"多出来的词", "又一个"}\n', "词表条目"),
        ("engine", 'import re\nLIANGJU_SELFTEST_PAT = re.compile(r"多出来的正则")\n', "正则"),
        ("engine", "LIANGJU_SELFTEST_THETA = 0.42\n", "门槛常量"),
        ("prompt", "\n你必须多守一条规矩。\n", "提示词里的硬规则"),
    ],
)
def test_ci_step_goes_red_when_any_category_grows(tmp_path, capsys, where, added, category):
    """变红的自测：把引擎与提示词原样抄一份，往里加一条，同一条命令就非零退出，并说出是哪一类多了。"""
    for rel in (biaoxiang.ENGINE, biaoxiang.PROMPTS):
        shutil.copytree(biaoxiang.ROOT / rel, tmp_path / rel)
    assert biaoxiang.main(["--root", str(tmp_path), "--check", str(BASELINE)]) == 0
    if where == "engine":
        (tmp_path / biaoxiang.ENGINE / "liangju_selftest_extra.py").write_text(added, encoding="utf-8")
    else:
        f = sorted((tmp_path / biaoxiang.PROMPTS).glob("tunshi*.md"))[0]
        f.write_text(f.read_text(encoding="utf-8") + added, encoding="utf-8")
    capsys.readouterr()
    assert biaoxiang.main(["--root", str(tmp_path), "--check", str(BASELINE)]) == 1
    err = capsys.readouterr().err
    assert "表项增加了" in err and category in err
