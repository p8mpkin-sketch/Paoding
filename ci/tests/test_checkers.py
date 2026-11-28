"""CI 检查器自身的正反样例：确保检查不是空转。"""

import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ci"))

import check_deps  # noqa: E402
import check_domain_words  # noqa: E402


def _tree(tmp: pathlib.Path) -> pathlib.Path:
    (tmp / "ci").mkdir()
    shutil.copy(ROOT / "ci" / "domain-words.txt", tmp / "ci" / "domain-words.txt")
    for c in check_deps.ALLOWED:
        (tmp / c / "src" / f"paoding_{c}").mkdir(parents=True)
    return tmp


def test_repo_is_clean():
    assert check_domain_words.main(["x", str(ROOT)]) == 0
    assert check_deps.main(["x", str(ROOT)]) == 0


def test_domain_word_caught(tmp_path):
    root = _tree(tmp_path)
    (root / "graph" / "src" / "paoding_graph" / "bad.py").write_text("MODE = 'CTF'\n")
    hits = check_domain_words.scan(root, check_domain_words.load_words(root / "ci" / "domain-words.txt"))
    assert [h[2].lower() for h in hits] == ["ctf"]


def test_domain_word_allowed_in_judge_config(tmp_path):
    root = _tree(tmp_path)
    d = root / "judgebox" / "judges.d"
    d.mkdir()
    (d / "x.yaml").write_text("note: lean\n")
    assert check_domain_words.scan(root, check_domain_words.load_words(root / "ci" / "domain-words.txt")) == []


def test_domain_word_caught_in_web(tmp_path):
    root = _tree(tmp_path)
    (root / "web" / "src").mkdir(parents=True)
    (root / "web" / "src" / "bad.tsx").write_text("export const mode = 'ctf';\n")
    (root / "web" / "node_modules" / "dep").mkdir(parents=True)
    (root / "web" / "node_modules" / "dep" / "index.ts").write_text("// payload\n")
    (root / "web" / "tests").mkdir()
    (root / "web" / "tests" / "corpus.ts").write_text("// payload\n")
    hits = check_domain_words.scan(root, check_domain_words.load_words(root / "ci" / "domain-words.txt"))
    assert [(h[0], h[2].lower()) for h in hits] == [("web/src/bad.tsx", "ctf")]


def test_word_boundary(tmp_path):
    root = _tree(tmp_path)
    (root / "graph" / "src" / "paoding_graph" / "ok.py").write_text("clean = 1  # leaning\n")
    assert check_domain_words.scan(root, check_domain_words.load_words(root / "ci" / "domain-words.txt")) == []


def test_internal_import_caught(tmp_path):
    root = _tree(tmp_path)
    (root / "pd" / "src" / "paoding_pd" / "x.py").write_text("from paoding_graph.reducer import apply\n")
    assert any("只许经" in e for e in check_deps.check(root))


def test_reverse_direction_caught(tmp_path):
    root = _tree(tmp_path)
    (root / "graph" / "src" / "paoding_graph" / "x.py").write_text("import paoding_adapter.contract\n")
    assert any("不在允许的依赖方向里" in e for e in check_deps.check(root))


def test_fire_code_cannot_open_sockets(tmp_path):
    root = _tree(tmp_path)
    (root / "fenjue" / "src" / "paoding_fenjue" / "x.py").write_text(
        "import socket\nfrom urllib.request import urlopen\n"
    )
    errs = check_deps.check(root)
    assert sum("体质内部不可达" in e for e in errs) == 2
    (root / "fenjue" / "src" / "paoding_fenjue" / "x.py").write_text(
        "from paoding_graph.contract import canonicalize\n"
    )
    assert check_deps.check(root) == []


def test_contract_import_allowed(tmp_path):
    root = _tree(tmp_path)
    (root / "pd" / "src" / "paoding_pd" / "x.py").write_text("from paoding_graph.contract import Event\n")
    assert check_deps.check(root) == []


def test_coverage_summary_groups_files_by_component(tmp_path, capsys, monkeypatch):
    import json

    import coverage_by_component as cbc

    f = lambda n, c, b=0, cb=0: {
        "summary": {
            "num_statements": n,
            "covered_lines": c,
            "num_branches": b,  # noqa: E731
            "covered_branches": cb,
        }
    }
    report = {
        "files": {
            "graph/src/paoding_graph/a.py": f(100, 90, 10, 5),
            "graph/src/paoding_graph/b.py": f(100, 70),
            "scripts/stack.py": f(50, 25),
            "zzz/x.py": f(10, 10),
        }
    }
    comps = cbc.by_component(report)
    assert comps["graph"] == {"files": 2, "statements": 200, "covered": 160, "branches": 10, "covered_branches": 5}
    table = cbc.rows(comps)
    assert [r[0] for r in table] == ["graph", "scripts", "zzz", "合计"]
    assert table[0][3:] == ("80.0%", "50.0%") and table[1][3:] == ("50.0%", "—") and table[-1][2:4] == (260, "75.0%")
    p = tmp_path / "coverage.json"
    p.write_text(json.dumps(report))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert cbc.main([str(p)]) == 0
    assert "graph" in capsys.readouterr().out and "| graph | 2 | 200 | 80.0% | 50.0% |" in summary.read_text()
    assert cbc.main([str(tmp_path / "missing.json")]) == 2


def test_docker_skip_caught(tmp_path):
    import check_no_skips

    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite><testcase classname="a" name="ok"/>'
        '<testcase classname="a" name="iso"><skipped message="需要 Docker（全栈）"/></testcase>'
        '<testcase classname="a" name="bash"><skipped message="需要 bash"/></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    assert [h.split(" ")[0] for h in check_no_skips.docker_skips(str(xml))] == ["a::iso"]
    assert check_no_skips.main(["x", str(xml)]) == 1


def test_no_docker_skip_passes(tmp_path):
    import check_no_skips

    xml = tmp_path / "j.xml"
    xml.write_text('<testsuites><testsuite><testcase classname="a" name="ok"/></testsuite></testsuites>')
    assert check_no_skips.main(["x", str(xml)]) == 0


# ---------------------------------------------------------------- 引擎之外的量具（liangju/）


def test_tools_are_one_way(tmp_path):
    root = _tree(tmp_path)
    (root / "liangju").mkdir()
    (root / "liangju" / "ok.py").write_text("import json\nfrom liangju import common\n")
    assert check_deps.check(root) == []
    (root / "fenjue" / "src" / "paoding_fenjue" / "bad.py").write_text("from liangju import mangpan\n")
    (root / "liangju" / "bad.py").write_text("from paoding_fenjue.contract import gongfa\n")
    errs = check_deps.check(root)
    assert len(errs) == 2 and "不许 import 量具" in errs[0] and "量具不许 import 组件" in errs[1]


TABLES = "fenjue/src/paoding_fenjue/lianhua.py"
SEED = (
    "fenjue/src/paoding_fenjue/engine/a.py",  # 被量：引擎
    "fenjue/src/paoding_fenjue/engine/checks.py",  # 量具：检验代码
    "fenjue/src/paoding_fenjue/engine/tables/t.json",  # 量具（可随引擎）：表
    "fenjue/tests/engine_fixtures/r.json",  # 量具（可随引擎）：录音
    "adapter/prompts/tunshi.md",  # 被量：提示词
    "adapter/config/prices.yaml",  # 量具：价表
    "graph/src/k.py",  # 体质
    "scripts/lianhua.py",  # 量具：炼化命令
    "scripts/run.py",  # 被量：组装脚本
    "liangju/x.py",  # 量具
    "eval/src/e.py",  # 量具：评测台
    "ci/check_liangju.py",  # 量具：这条检查自己
    "docs/a.md",  # 其他
)


def _git(repo: pathlib.Path, *args: str) -> str:
    import subprocess

    cmd = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp: pathlib.Path) -> tuple[pathlib.Path, str]:
    """一个小仓库：量具表用真的那一份（判定函数那个文件原样抄过来），其余每个区放一个文件。"""
    _git(tmp, "init", "-q")
    for rel in SEED:
        f = tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("1\n")
    (tmp / TABLES).write_text((ROOT / TABLES).read_text(encoding="utf-8"), encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-qm", "base")
    return tmp, _git(tmp, "rev-parse", "HEAD")


def _change(repo: pathlib.Path, base: str, *paths: str) -> tuple[bool, list[str]]:
    """从基线起只改这几个文件（各改成两行），回这条检查怎么说。"""
    import check_liangju

    _git(repo, "checkout", "-q", "-B", "try", base)
    for rel in paths:
        with (repo / rel).open("a", encoding="utf-8") as f:
            f.write("# 假改动\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "x")
    return check_liangju.check(base, "HEAD", str(repo))


ENGINE = "fenjue/src/paoding_fenjue/engine/a.py"


def test_tools_and_what_they_measure_do_not_change_together(tmp_path):
    repo, base = _repo(tmp_path)
    assert _change(repo, base, "liangju/x.py", "docs/a.md") == (True, [])
    touched, errs = _change(repo, base, "liangju/x.py", "adapter/prompts/tunshi.md", ENGINE, "graph/src/k.py")
    assert touched and errs == [
        "adapter/prompts/tunshi.md（被量）：改了 1 行",
        f"{ENGINE}（被量）：改了 1 行",
        "graph/src/k.py（体质）：改了 1 行",
        "adapter/prompts/tunshi.md：摘要变了",
    ]


@pytest.mark.parametrize(
    "tool",
    [
        "liangju/x.py",
        "fenjue/src/paoding_fenjue/engine/checks.py",  # 检验代码
        "ci/check_liangju.py",  # 这条检查自己：改它按改量具来审
        TABLES,  # 判定函数与量具表
        "scripts/lianhua.py",
        "adapter/config/prices.yaml",  # 价表
        "eval/src/e.py",  # 评测台
    ],
)
def test_every_measuring_tool_refuses_to_travel_with_the_engine(tmp_path, tool):
    """量具表里的每一类，加上引擎的改动：都拒绝。数行数的表与这条检查认的是同一批路径。"""
    repo, base = _repo(tmp_path)
    assert _change(repo, base, tool) == (True, [])
    assert _change(repo, base, tool, ENGINE) == (True, [f"{ENGINE}（被量）：改了 1 行"])
    assert _change(repo, base, tool, "scripts/run.py") == (True, ["scripts/run.py（被量）：改了 1 行"])


def test_measuring_tools_may_change_together(tmp_path):
    """量具加量具不拒绝：量具目录加检验代码，加表、加录音，都是量具自己的改动。"""
    repo, base = _repo(tmp_path)
    both = (
        "liangju/x.py",
        "fenjue/src/paoding_fenjue/engine/checks.py",
        "fenjue/src/paoding_fenjue/engine/tables/t.json",
    )
    assert _change(repo, base, *both, "fenjue/tests/engine_fixtures/r.json") == (True, [])


@pytest.mark.parametrize(
    "tool", ["fenjue/src/paoding_fenjue/engine/tables/t.json", "fenjue/tests/engine_fixtures/r.json"]
)
def test_the_listed_exceptions_may_travel_with_the_engine_and_nothing_else_may(tmp_path, tool):
    """表与录音可以跟引擎同一个改动（理由写在 MEASURE_WITH_ENGINE 里）：只碰了它们时这条检查不启动。
    同一个改动里再带上别的量具，就照常拒绝。"""
    repo, base = _repo(tmp_path)
    assert _change(repo, base, tool, ENGINE) == (False, [])
    assert _change(repo, base, tool, ENGINE, "liangju/x.py") == (True, [f"{ENGINE}（被量）：改了 1 行"])


def test_engine_only_change_is_not_checked(tmp_path):
    repo, base = _repo(tmp_path)
    assert _change(repo, base, ENGINE) == (False, [])


def test_the_checker_and_the_line_count_read_one_table():
    """「量具」只有一个定义：这条检查从判定函数那个文件里读出来的表，就是验体数行数用的那一张；例外都在表内，
    各有理由；体质表也是同一张。"""
    import check_liangju

    from paoding_fenjue import lianhua

    measure, with_engine, kernel = check_liangju.tables((ROOT / TABLES).read_text(encoding="utf-8"))
    assert measure == lianhua.MEASURE_PATHS and kernel == lianhua.KERNEL_PATHS
    assert with_engine == tuple(lianhua.MEASURE_WITH_ENGINE) and set(with_engine) < set(measure)
    assert all(len(why) > 10 for why in lianhua.MEASURE_WITH_ENGINE.values())
    assert "ci/check_liangju.py" in measure and "ci/check_liangju.py" not in with_engine
    for rel in (*measure, *kernel, *check_liangju.MEASURED):
        assert (ROOT / rel).exists(), f"{rel} 不在了：改了名就改表"


# 每个顶层目录与单独的文件各在哪一区。新添的东西没归类、或者落进了这张表没写的区，这里就红。
ZONE_MAP = {
    ".github/": {"其他"},
    ".gitignore": {"其他"},
    "LICENSE": {"其他"},
    "README.md": {"其他"},
    "pyproject.toml": {"其他"},
    "uv.lock": {"其他"},
    "docs/": {"其他"},
    "web/": {"其他"},
    "problems/": {"其他"},
    "liangju/": {"量具"},  # 引擎之外的量具
    "eval/": {"量具"},  # 评测台
    "judgebox/": {"体质"},  # 判官
    "graph/": {"体质", "其他"},  # src 是体质；测试与说明是其他
    "executor/": {"体质", "其他"},
    "qicao/": {"体质", "其他"},
    "watchdog/": {"体质", "其他"},
    "pd/": {"被量", "其他"},  # src 是被量的；测试与说明是其他
    "sinan/": {"被量", "其他"},
    "tongjian/": {"被量", "其他"},
    "shuku/": {"被量", "其他"},
    "scripts/": {"被量", "量具"},  # 组装脚本是被量的；炼化命令是量具
    "ci/": {"量具", "其他"},  # 守量具这条线的检查是量具；别的检查是其他
    "tests/": {"量具", "量具（可随引擎）", "其他"},  # 体质试炼的清单；黄金日志；其余测试
    "adapter/": {"体质", "被量", "量具", "量具（可随引擎）", "其他"},  # 代理与钥匙环；适配层与提示词；价表；黄金日志
    "fenjue/": {"被量", "量具", "量具（可随引擎）", "其他"},  # 引擎与功法；判定、检验、Schema；表与录音
}
# 单独点名的文件
ZONE_FILES = {
    "fenjue/src/paoding_fenjue/lianhua.py": "量具",  # 判定函数与量具表
    "fenjue/src/paoding_fenjue/readings.py": "量具",
    "fenjue/src/paoding_fenjue/shapes.py": "量具",  # 留出份额的规则：一道题落进哪条臂
    "fenjue/src/paoding_fenjue/tables.py": "量具",
    "fenjue/src/paoding_fenjue/engine/checks.py": "量具",
    "fenjue/src/paoding_fenjue/engine/schema.py": "量具",
    "fenjue/src/paoding_fenjue/engine/sections.py": "量具",
    "fenjue/src/paoding_fenjue/engine/schemas/essence.schema.json": "量具",
    "fenjue/src/paoding_fenjue/engine/tables/vocab.json": "量具（可随引擎）",
    "fenjue/src/paoding_fenjue/engine/run.py": "被量",
    "fenjue/src/paoding_fenjue/gongfa.json": "被量",
    "scripts/lianhua.py": "量具",
    "scripts/run.py": "被量",
    "adapter/config/prices.yaml": "量具",  # 价表：决定「在预算内完成」怎么判
    "adapter/prompts/tunshi.md": "被量",
    "adapter/src/paoding_adapter/proxy.py": "体质",
    "adapter/src/paoding_adapter/session.py": "被量",
    "tests/fenjue/trials.py": "量具",
    "ci/check_liangju.py": "量具",  # 这条检查自己
    "ci/check_deps.py": "其他",
    "eval/src/paoding_eval/harness.py": "量具",
}


def test_every_file_in_the_repository_belongs_to_exactly_one_zone():
    import check_liangju

    measure, with_engine, kernel = check_liangju.tables((ROOT / TABLES).read_text(encoding="utf-8"))
    files = _git(ROOT, "ls-files").splitlines()
    zones = {f: check_liangju.zone(f, measure, with_engine, kernel) for f in files}
    assert [f for f, z in zones.items() if z is None] == [], (
        "这些文件没有归区：在量具表或 ci/check_liangju.py 里给它一个"
    )
    assert set(zones.values()) <= set(check_liangju.ZONES)
    by_top: dict[str, set[str]] = {}
    for f, z in zones.items():
        by_top.setdefault(f.split("/")[0] + ("/" if "/" in f else ""), set()).add(str(z))
    assert by_top == ZONE_MAP
    for f, z in ZONE_FILES.items():
        assert f in zones, f"{f} 不在了"
        assert zones[f] == z, f
    assert check_liangju.zone("新目录/x.py", measure, with_engine, kernel) is None
    assert check_liangju.zone("fenjue/新目录/x.py", measure, with_engine, kernel) is None
