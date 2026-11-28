"""表项计数：数引擎里写死的四样东西，留一个初值，以后每一步拿它对比（只许减不许加）。

    python -m liangju.biaoxiang                      # 打印现在的计数
    python -m liangju.biaoxiang --write <文件>        # 写成 JSON
    python -m liangju.biaoxiang --check <初值文件>    # 哪一类比初值多了就非零退出

只读源码文件，不 import 引擎，不运行任何引擎代码。数法是固定的（`RULE` 是它的版本号）；改数法要换版本号，
不同版本的计数不放在一起比。

四类：
- 词表条目：`engine/tables/*.json` 里的叶子字符串；加上 `engine/*.py` 里模块级与类级的字符串字面量集合
  （元组、列表、集合、字典，至少两个字符串字面量）里的字符串个数。
- 正则：`engine/*.py` 里以字符串字面量为模式的 `re.` 调用个数。
- 门槛常量：`engine/*.py` 里模块级与类级、赋了数字字面量的名字个数（含数字字面量集合里的每个数）；
  加上 `engine/tables/*.json` 里的叶子数字。
- 提示词里的硬规则：引擎用的提示词（`adapter/prompts/tunshi*.md`）里带约束词的行数。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

from liangju.common import read_json, sha, write_json

ROOT = Path(__file__).resolve().parents[1]
ENGINE = "fenjue/src/paoding_fenjue/engine"
PROMPTS = "adapter/prompts"
RULE = "1"
HARD = re.compile(r"必须|不得|不许|不能|不要|只能|只许|只取|禁止|一律|务必|至多|至少|不超过|严禁")
RE_CALLS = {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
CATEGORIES = ("词表条目", "正则", "门槛常量", "提示词里的硬规则")


def _leaves(doc: Any) -> tuple[int, int]:
    """JSON 里的叶子：(字符串个数, 数字个数)。字典的键不算。"""
    if isinstance(doc, str):
        return 1, 0
    if isinstance(doc, bool) or doc is None:
        return 0, 0
    if isinstance(doc, (int, float)):
        return 0, 1
    items = doc.values() if isinstance(doc, dict) else doc
    s = n = 0
    for x in items:
        a, b = _leaves(x)
        s, n = s + a, n + b
    return s, n


def _literals(node: ast.AST) -> tuple[int, int]:
    """一个字面量表达式里的 (字符串个数, 数字个数)。字典的键也算（词表常以键的形式写）。"""
    s = n = 0
    for x in ast.walk(node):
        if isinstance(x, ast.Constant):
            if isinstance(x.value, str):
                s += 1
            elif isinstance(x.value, (int, float)) and not isinstance(x.value, bool):
                n += 1
    return s, n


def _is_literal(node: ast.AST) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _python(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    words = numbers = regexes = 0
    scopes: list[list[ast.stmt]] = [tree.body] + [c.body for c in tree.body if isinstance(c, ast.ClassDef)]
    for body in scopes:
        for st in body:
            value = st.value if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)) else None
            if value is None:
                continue
            if isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant):
                value = value.operand
            if isinstance(value, ast.Constant):
                if isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
                    numbers += 1
            elif isinstance(value, (ast.Tuple, ast.List, ast.Set, ast.Dict)) and _is_literal(value):
                s, n = _literals(value)
                words += s if s >= 2 else 0
                numbers += n
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re"
            and node.func.attr in RE_CALLS
            and node.args
            and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))
        ):
            regexes += 1
    return {"词表条目": words, "正则": regexes, "门槛常量": numbers}


def count(root: Path = ROOT) -> dict[str, Any]:
    files: dict[str, dict[str, int]] = {}
    for p in sorted((root / ENGINE).glob("*.py")):
        files[p.relative_to(root).as_posix()] = _python(p)
    for p in sorted((root / ENGINE / "tables").glob("*.json")):
        s, n = _leaves(json.loads(p.read_text(encoding="utf-8")))
        files[p.relative_to(root).as_posix()] = {"词表条目": s, "门槛常量": n}
    for p in sorted((root / PROMPTS).glob("tunshi*.md")):
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if HARD.search(ln)]
        files[p.relative_to(root).as_posix()] = {"提示词里的硬规则": len(lines)}
    totals = {c: sum(f.get(c, 0) for f in files.values()) for c in CATEGORIES}
    return {"v": 1, "rule": RULE, "totals": totals, "files": files, "digest": sha({"rule": RULE, "files": files})}


def check(now: dict[str, Any], base: dict[str, Any]) -> list[str]:
    if now["rule"] != base["rule"]:
        return [f"数法的版本不同（现在 {now['rule']}，初值 {base['rule']}）：不能比"]
    return [
        f"{c}：初值 {base['totals'][c]}，现在 {now['totals'][c]}（多了 {now['totals'][c] - base['totals'][c]}）"
        for c in CATEGORIES
        if now["totals"][c] > base["totals"][c]
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="liangju.biaoxiang")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--write")
    ap.add_argument("--check")
    a = ap.parse_args(argv)
    now = count(Path(a.root))
    for c in CATEGORIES:
        print(f"{c}：{now['totals'][c]}")
    if a.write:
        write_json(Path(a.write), now)
    if a.check:
        grown = check(now, read_json(Path(a.check)))
        for line in grown:
            print(f"表项增加了 —— {line}", file=sys.stderr)
        return 1 if grown else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
