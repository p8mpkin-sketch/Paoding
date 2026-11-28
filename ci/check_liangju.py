"""量具与被量的东西不在同一个改动里变（docs/design/fenjue/03-huolian.md §3.2）。

「量具」只有一个定义：`paoding_fenjue.lianhua.MEASURE_PATHS`。这里不另列一份，直接从那个文件里读（只解析字面量，
不 import，所以不装包也能跑）。数「量具改动行数」的表与这条检查认的是同一批路径。

一个改动只要碰了量具（表里的任何一条路径；`MEASURE_WITH_ENGINE` 里写了理由的那几样除外），就查两样：
1. 被量的路径改动行数为零：体质（同一个文件里的 `KERNEL_PATHS`），以及引擎、功法清单与火清单、适配层、提示词、
   其余组件、组装脚本（下面的 MEASURED）。
2. 功法清单、火清单、引擎用的提示词，改动前后各取一次摘要，逐个文件相等。

`MEASURE_WITH_ENGINE` 里的量具（录音、黄金日志、引擎读的表）允许与被量的东西同一个改动，理由写在那张表里；
只碰了它们时这条检查不启动。这个脚本自己在量具表里：改它按改量具来审，不能和引擎同一个改动。

仓库里每个文件都归且只归一个区（`zone`）：量具、量具（可随引擎）、体质、被量、其他。没归类的文件会让
ci/tests 里的测试变红。

用法：python ci/check_liangju.py <基线提交> [<改动后的提交，缺省 HEAD>]
CI 里基线取合并提交的第一个父提交（`HEAD^1`，即目标分支）；不是合并请求时不跑。
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys

TABLES = "fenjue/src/paoding_fenjue/lianhua.py"  # 量具表与体质表住在这里
# 被量的（体质之外）：这一轮跑起来的系统本身
MEASURED = (
    "fenjue/src/",  # 引擎、功法清单与火清单、存档（表里列为量具的那几个文件除外）
    "adapter/src/",  # 适配层
    "adapter/prompts/",  # 提示词
    "pd/src/",  # 以下是其余组件
    "sinan/src/",
    "tongjian/src/",
    "shuku/src/",
    "scripts/",  # 组装脚本：引擎是从这里起的
)
# 其他：文档、界面、测试、各组件的说明与打包文件、仓库的配置。逐条列出，新添的目录不会自动落进来
OTHER = (
    ".github/",
    ".gitignore",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "docs/",
    "web/",
    "problems/",
    "tests/",
    "ci/",
    *(
        f"{c}/{x}"
        for c in ("adapter", "fenjue", "pd", "sinan", "tongjian", "shuku")
        for x in ("tests/", "pyproject.toml")
    ),
    *(f"{c}/{x}" for c in ("executor", "graph", "qicao", "watchdog") for x in ("tests/", "pyproject.toml", "SPEC.md")),
    *(f"{c}/SPEC.md" for c in ("adapter", "pd", "sinan", "tongjian", "shuku")),
)
ZONES = ("量具", "量具（可随引擎）", "体质", "被量", "其他")
PINNED = ("fenjue/src/paoding_fenjue/gongfa", "fenjue/src/paoding_fenjue/fires/", "adapter/prompts/")


def tables(source: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """从判定函数那个文件的源码里读三张表：量具、其中可随引擎的、体质。"""
    want: dict[str, tuple[str, ...] | None] = {"MEASURE_PATHS": None, "MEASURE_WITH_ENGINE": None, "KERNEL_PATHS": None}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
            if name in want and isinstance(value, ast.Dict):  # 例外表：只要路径（键），理由是给人看的
                want[name] = tuple(ast.literal_eval(k) for k in value.keys if k is not None)
            elif name in want:
                want[name] = tuple(ast.literal_eval(value))
    measure, with_engine, kernel = want["MEASURE_PATHS"], want["MEASURE_WITH_ENGINE"], want["KERNEL_PATHS"]
    if measure is None or with_engine is None or kernel is None:
        raise SystemExit(f"{TABLES} 里读不到 {[k for k, v in want.items() if v is None]}：量具表改了名就改这里")
    stray = sorted(set(with_engine) - set(measure))
    if stray:
        raise SystemExit(f"MEASURE_WITH_ENGINE 里的 {stray} 不在 MEASURE_PATHS 里：例外只能是量具")
    return measure, with_engine, kernel


def zone(path: str, measure: tuple[str, ...], with_engine: tuple[str, ...], kernel: tuple[str, ...]) -> str | None:
    """一个文件归哪个区。量具表最先认（它列的是具体的文件与目录），然后体质、被量、其他。都不是：没归类。"""
    if path.startswith(with_engine):
        return "量具（可随引擎）"
    if path.startswith(measure):
        return "量具"
    if path.startswith(kernel):
        return "体质"
    if path.startswith(MEASURED):
        return "被量"
    if path.startswith(OTHER):
        return "其他"
    return None


def git(cwd: str, *args: str) -> str:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout


def changed(base: str, head: str, cwd: str = ".") -> dict[str, int]:
    """改动的文件 → 改动行数（增 + 删；二进制文件记 1）。"""
    out: dict[str, int] = {}
    for line in git(cwd, "diff", "--numstat", "--no-renames", base, head).splitlines():
        add, rem, path = line.split("\t", 2)
        out[path] = (int(add) if add.isdigit() else 1) + (int(rem) if rem.isdigit() else 0)
    return out


def digests(rev: str, cwd: str = ".") -> dict[str, str]:
    out = {}
    for path in git(cwd, "ls-tree", "-r", "--name-only", rev).splitlines():
        if path.startswith(PINNED):
            blob = subprocess.run(["git", "-C", cwd, "show", f"{rev}:{path}"], capture_output=True, check=True).stdout
            out[path] = hashlib.sha256(blob).hexdigest()
    return out


def check(base: str, head: str, cwd: str = ".") -> tuple[bool, list[str]]:
    """回 (这个改动碰没碰量具, 违反的地方)。没碰量具（或只碰了可随引擎的那几样）时什么都不查。

    量具表取改动之后的那一版：往表里添一条路径的改动，自己就按新表查。"""
    measure, with_engine, kernel = tables(git(cwd, "show", f"{head}:{TABLES}"))
    diff = changed(base, head, cwd)
    zones = {p: zone(p, measure, with_engine, kernel) for p in diff}
    if "量具" not in zones.values():
        return False, []
    errors = [f"{p}（{zones[p]}）：改了 {n} 行" for p, n in sorted(diff.items()) if zones[p] in ("体质", "被量")]
    before, after = digests(base, cwd), digests(head, cwd)
    errors += [f"{p}：摘要变了" for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    return True, errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    touched, errors = check(argv[1], argv[2] if len(argv) > 2 else "HEAD")
    if not touched:
        print("量具没有改动（或只动了可以随引擎一起改的那几样）：不查。")
        return 0
    if errors:
        print("这个改动碰了量具，同时又动了被量的东西：")
        print("\n".join(f"  {e}" for e in errors))
        return 1
    print("量具改动：体质与被量的路径改动零行，功法清单、火清单与提示词的摘要逐项相等。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
