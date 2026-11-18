"""CI 检查器自身的正反样例：确保检查不是空转。"""

import pathlib
import shutil
import sys

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
