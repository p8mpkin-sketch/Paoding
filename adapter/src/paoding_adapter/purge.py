"""回收站过期后清工作区（v5 第三期软删；cz 2026-11-20 裁决）。

人把任务移进回收站后 30 天内可恢复；过期后读端标成 purged，这里把那道题各会话的目录（工作区与 home）删掉。
只删 <root>/<lease_id> 目录：事件账、留档 Blob、花费都不动，读数照算。
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TRASH_MS = 30 * 86_400_000  # 与图服务 reducer/curate.py 的 TRASH_DAYS 一致


def purged(p: Mapping[str, Any], now: int) -> bool:
    sh = p.get("shelf")
    return sh is not None and sh["state"] == "trash" and now >= int(sh["ts"]) + TRASH_MS


def purge_workspaces(state: Mapping[str, Any], root: Path, now: int) -> list[str]:
    """删掉回收站过期的题的会话目录；返回删掉的租约 id。目录不在就跳过，重复调用无害。"""
    gone = {pid for pid, p in state["problems"].items() if purged(p, now)}
    out: list[str] = []
    for lid, lease in sorted(state["leases"].items()):
        if lease["problem_id"] not in gone:
            continue
        d = root / lid
        if d.is_dir() and d.resolve().parent == root.resolve():
            shutil.rmtree(d)
            out.append(lid)
    return out
