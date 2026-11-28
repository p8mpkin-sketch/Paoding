"""几样小东西：规范化的 JSON、摘要、先写旁边再换名。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canon(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(obj: Any) -> str:
    return hashlib.sha256(obj if isinstance(obj, bytes) else canon(obj)).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # 写到一半被打断的那一行：不认
        if isinstance(row, dict):
            out.append(row)
    return out


class Refused(Exception):
    """量具拒绝做：缺栏、对不上、自检没过。消息就是给人看的原因。"""
