"""量具与被量的东西不在同一个改动里变（现行设计第 14.2 节，第 0 步「不改变引擎行为」的前两件）。

一个改动只要碰了 `liangju/`（引擎之外的量具），就查两样：
1. 路径清单：引擎、适配层、体质、提示词、表、Schema、夹具与录音、组装脚本，这些路径下的改动行数为零。
2. 提示词与清单逐项相等：功法清单、火清单、引擎用的提示词，改动前后各取一次摘要，逐个文件相等。

用法：python ci/check_liangju.py <基线提交> [<改动后的提交，缺省 HEAD>]
CI 里基线取合并提交的第一个父提交（`HEAD^1`，即目标分支）；不是合并请求时不跑。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys

TOOLS = "liangju/"
PROTECTED = (
    "fenjue/src/",  # 引擎、表、Schema、功法清单与火清单、存档
    "fenjue/tests/engine_fixtures/",  # 夹具与录音
    "tests/fenjue/goldens/",
    "adapter/src/",  # 适配层
    "adapter/prompts/",  # 提示词
    "adapter/config/",  # 价表
    "adapter/tests/golden/",
    "judgebox/",  # 以下是体质（paoding_fenjue.lianhua.KERNEL_PATHS）
    "qicao/src/",
    "graph/src/",
    "executor/src/",
    "watchdog/src/",
    "scripts/",  # 组装脚本：引擎是从这里起的
)
PINNED = ("fenjue/src/paoding_fenjue/gongfa", "fenjue/src/paoding_fenjue/fires/", "adapter/prompts/")


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
    """回 (这个改动碰没碰量具, 违反的地方)。没碰量具时什么都不查。"""
    diff = changed(base, head, cwd)
    if not any(p.startswith(TOOLS) for p in diff):
        return False, []
    errors = [f"{p}：改了 {n} 行" for p, n in sorted(diff.items()) if p.startswith(PROTECTED)]
    before, after = digests(base, cwd), digests(head, cwd)
    errors += [f"{p}：摘要变了" for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    return True, errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    touched, errors = check(argv[1], argv[2] if len(argv) > 2 else "HEAD")
    if not touched:
        print("量具没有改动：不查。")
        return 0
    if errors:
        print("这个改动碰了量具（liangju/），同时又动了被量的东西：")
        print("\n".join(f"  {e}" for e in errors))
        return 1
    print(f"量具改动：被量的路径改动零行（{len(PROTECTED)} 条路径），功法清单、火清单与提示词的摘要逐项相等。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
