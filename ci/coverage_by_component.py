"""按组件汇总测试覆盖率（P2-3 第 4 项）。本脚本只显示；总覆盖率的门槛在 CI 的 pytest 步骤（--cov-fail-under）。

用法：
    uv run pytest --cov --cov-report=json:coverage.json
    python ci/coverage_by_component.py coverage.json [--markdown]

组件 = 仓库顶层目录（pd、graph、adapter、executor、judgebox、watchdog、eval、sinan），另加 scripts（组装根）。
行覆盖率 = 执行到的语句 ÷ 语句数；分支覆盖率在 coverage.json 带分支数据时给出。
在 GitHub Actions 里（有 GITHUB_STEP_SUMMARY）另把 Markdown 表写进任务摘要。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

ORDER = ("graph", "adapter", "executor", "judgebox", "sinan", "watchdog", "pd", "eval", "scripts")


def by_component(report: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path, f in report.get("files", {}).items():
        comp = pathlib.PurePosixPath(path.replace("\\", "/")).parts[0]
        s, acc = (
            f["summary"],
            out.setdefault(comp, {"files": 0, "statements": 0, "covered": 0, "branches": 0, "covered_branches": 0}),
        )
        acc["files"] += 1
        acc["statements"] += s["num_statements"]
        acc["covered"] += s["covered_lines"]
        acc["branches"] += s.get("num_branches", 0)
        acc["covered_branches"] += s.get("covered_branches", 0)
    return out


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "—"


def rows(comps: dict[str, dict]) -> list[tuple]:
    names = [c for c in ORDER if c in comps] + sorted(set(comps) - set(ORDER))
    out = [
        (
            n,
            comps[n]["files"],
            comps[n]["statements"],
            pct(comps[n]["covered"], comps[n]["statements"]),
            pct(comps[n]["covered_branches"], comps[n]["branches"]),
        )
        for n in names
    ]
    tot = {
        k: sum(c[k] for c in comps.values()) for k in ("files", "statements", "covered", "branches", "covered_branches")
    }
    out.append(
        (
            "合计",
            tot["files"],
            tot["statements"],
            pct(tot["covered"], tot["statements"]),
            pct(tot["covered_branches"], tot["branches"]),
        )
    )
    return out


def text(table: list[tuple]) -> str:
    head = ("组件", "文件", "语句", "行覆盖", "分支覆盖")
    return "\n".join(f"{r[0]:<10} {r[1]:>5} {r[2]:>7} {r[3]:>8} {r[4]:>8}" for r in [head, *table])


def markdown(table: list[tuple]) -> str:
    lines = [
        "### 测试覆盖率（按组件）",
        "",
        "| 组件 | 文件 | 语句 | 行覆盖 | 分支覆盖 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in table]
    lines += ["", "子进程里跑的代码（假 CLI、起成子进程的 `run.py`）量不到，读数偏低而不偏高。只显示，不设门槛。"]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    path = pathlib.Path(args[0] if args else "coverage.json")
    if not path.is_file():
        print(f"没有覆盖率数据 {path}：先跑 uv run pytest --cov --cov-report=json:{path}", file=sys.stderr)
        return 2
    table = rows(by_component(json.loads(path.read_text(encoding="utf-8"))))
    print(markdown(table) if "--markdown" in argv else text(table))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(markdown(table) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
