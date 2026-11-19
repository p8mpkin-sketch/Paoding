"""跨组件依赖只许走契约接口，方向单向（EDR-001 D-4；规格 §2.1）。

规则：
1. 组件 A 只能 import 组件 B 的 `paoding_B.contract`（或其子模块），不得 import B 的内部模块。
2. A → B 必须在 ALLOWED 表里。graph 不依赖任何组件。
"""

from __future__ import annotations

import ast
import pathlib
import sys

ALLOWED: dict[str, set[str]] = {
    "graph": set(),
    "executor": {"graph"},
    "judgebox": {"graph", "executor"},
    "adapter": {"graph", "executor"},
    "watchdog": {"graph"},
    "pd": {"graph"},
    "eval": {"graph", "adapter", "executor", "tongjian"},
    "sinan": {"graph", "adapter"},
    "tongjian": {"graph"},
}


def imports(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module))
    return out


def check(root: pathlib.Path) -> list[str]:
    errors = []
    for comp, allowed in ALLOWED.items():
        for f in sorted((root / comp).rglob("*.py")):
            for line, mod in imports(f):
                head = mod.split(".")[0]
                if not head.startswith("paoding_"):
                    continue
                target = head.removeprefix("paoding_")
                if target == comp:
                    continue
                where = f"{f.relative_to(root)}:{line}"
                if target not in allowed:
                    errors.append(f"{where}: {comp} → {target} 不在允许的依赖方向里")
                elif mod.split(".")[1:2] != ["contract"]:
                    errors.append(f"{where}: 只许经 paoding_{target}.contract 访问，实际 import {mod}")
    return errors


def main(argv: list[str]) -> int:
    root = pathlib.Path(argv[1] if len(argv) > 1 else ".").resolve()
    errors = check(root)
    print("\n".join(errors) if errors else "依赖方向：全部经契约接口，方向单向。")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
