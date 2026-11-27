"""在定版快照里按正则搜。单独成一个进程跑：模式是盲判的模型给的，可能在大文件上回溯个没完，
同一个进程里停不下它，所以由 `model.Toolbox` 起一个子进程、到时限就杀掉。

子进程的用法（标准输入一行 JSON，标准输出是结果）：

    echo '{"root": "<快照目录>", "under": ".", "pattern": "MAX_BATCH"}' | python -m liangju.sousuo
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SEARCH_HITS = 50  # 一次搜索至多回这么多处
FILE_BYTES = 2_000_000  # 更大的文件不搜、不读
MISS = "没有搜到"


def inside(root: Path, rel: str) -> Path:
    p = (root / str(rel or ".")).resolve()
    if p != root and root not in p.parents:
        raise ValueError("路径在快照之外")
    return p


def files(root: Path, under: Path) -> list[Path]:
    return [
        p
        for p in sorted(under.rglob("*"))
        if p.is_file() and not p.is_symlink() and ".git" not in p.relative_to(root).parts
    ]


def search(root: Path, under: str, pattern: str) -> str:
    root = root.resolve()
    pat = re.compile(pattern)
    hits: list[str] = []
    for p in files(root, inside(root, under)):
        if p.stat().st_size > FILE_BYTES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "\x00" in text[:1000]:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                hits.append(f"{p.relative_to(root).as_posix()}:{i}:{line[:300]}")
                if len(hits) >= SEARCH_HITS:
                    return "\n".join(hits) + "\n（还有更多，缩小范围再搜）"
    return "\n".join(hits) or MISS


def main() -> int:
    a = json.loads(sys.stdin.read())
    try:
        out = search(Path(a["root"]), str(a.get("under") or "."), str(a["pattern"]))
    except (OSError, ValueError, KeyError, re.error, TypeError) as e:
        out = f"没做成：{type(e).__name__}: {e}"
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
