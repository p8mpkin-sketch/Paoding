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
