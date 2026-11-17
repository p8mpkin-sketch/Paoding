"""红线 3：内核与组件目录零领域词。领域词只允许出现在判官配置与锦囊里。

用法：python ci/check_domain_words.py [根目录]
扫描 COMPONENTS 下的源码（排除 tests/ 与判官配置目录 judges.d/），命中即非零退出。
"""
from __future__ import annotations

import pathlib
import re
import sys

COMPONENTS = ("pd", "graph", "adapter", "executor", "judgebox", "watchdog", "eval")
EXCLUDED_PARTS = {"tests", "judges.d", "kits", "__pycache__"}
SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".json"}


def load_words(path: pathlib.Path) -> list[str]:
    return [w.strip().lower() for w in path.read_text(encoding="utf-8").splitlines()
            if w.strip() and not w.lstrip().startswith("#")]


def scan(root: pathlib.Path, words: list[str]) -> list[tuple[str, int, str]]:
    pattern = re.compile(r"(?<![a-z0-9_])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9_])",
                         re.IGNORECASE)
    hits = []
    for comp in COMPONENTS:
        for f in sorted((root / comp).rglob("*")):
            if not f.is_file() or f.suffix not in SUFFIXES:
                continue
            if EXCLUDED_PARTS & set(f.relative_to(root).parts):
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = pattern.search(line)
                if m:
                    hits.append((str(f.relative_to(root)), n, m.group(1)))
    return hits


def main(argv: list[str]) -> int:
    root = pathlib.Path(argv[1] if len(argv) > 1 else ".").resolve()
    hits = scan(root, load_words(root / "ci" / "domain-words.txt"))
    for path, n, w in hits:
        print(f"{path}:{n}: 领域词 {w!r}")
    if hits:
        print(f"红线 3：{len(hits)} 处领域词。领域知识只允许出现在判官配置与锦囊里。")
        return 1
    print("红线 3：组件代码零领域词。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
