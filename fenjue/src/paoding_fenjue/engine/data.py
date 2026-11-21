"""引擎的量具表（docs/design/fenjue/08-algorithms.md 附表 A–C、§3.3、§4.4）：包内 `tables/*.json`，只读。

这些表归药鼎：引擎只能读、只能随产物交出修订提议（EN4），改它们要 cz 裁决后由实现线写入。
能力剖面不是火位注册表的副本：哪些火在生效，唯一来源仍是 `gongfa.json`；`profile_stale()` 每次运行前核对两者。
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from .. import shapes
from ..shapes import digest

FORM_C0 = {"code": 1.0, "docs": 0.7, "service": 0.6, "description": 0.4}  # 置信基数 c₀（08 §3.1）〔占位〕
FORM_CAP = {"code": 1.0, "docs": 0.7, "service": 0.6, "description": 0.4}  # 置信上限：只有行为 ≤ 0.6、只有描述 ≤ 0.4
FORM_ZH = {"code": "代码", "docs": "文档", "service": "行为", "description": "描述"}
RISK_LEVEL = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
SESSION_SLOTS = ("H1", "H2", "H3", "H4", "H5", "H8")  # 改了就改会话行为的火位；H6、H7 只动读端（08 §3.7 风险级）


@cache
def table(name: str) -> dict[str, Any]:
    text = resources.files("paoding_fenjue.engine").joinpath(f"tables/{name}.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def profile() -> dict[str, Any]:
    return table("profile")


def profile_sha256() -> str:
    return digest(profile())


@cache
def dims() -> dict[str, dict[str, Any]]:
    """能力维 → 剖面行。"""
    return {row["dim"]: row for row in profile()["dims"]}


def ours(dim: str) -> int:
    """我们在这一维的级；不在剖面里的维按 0 计（调用方另判“新维”）。"""
    row = dims().get(dim)
    return int(row["level"]) if row else 0


def weight(dim: str) -> float:
    row = dims().get(dim) or {}
    return float(row.get("weight", profile().get("weights_default", 1)))


def active_refs() -> set[str]:
    g = shapes.gongfa()
    return {r for rs in g["fires"].values() for r in rs}


def profile_stale() -> list[str]:
    """剖面里引用的 `id@ver` 不在功法里的（剖面过期）；与功法里生效却没有剖面行的火位。"""
    refs = active_refs()
    out = [
        f"{row['dim']}：{row['by']} 已不在功法里"
        for row in profile()["dims"]
        if row.get("by") and row["by"] not in refs
    ]
    covered = {row["slot"] for row in profile()["dims"]}
    out += [
        f"{slot}：功法里有生效的火，剖面没有这个火位的维" for slot in shapes.gongfa()["fires"] if slot not in covered
    ]
    return out


@cache
def primitives() -> frozenset[str]:
    return frozenset(table("primitives")["primitives"])


@cache
def features() -> dict[str, dict[str, Any]]:
    return {row["feature"]: row for row in table("probes")["features"]}


@cache
def signatures() -> dict[str, dict[str, Any]]:
    return {row["slot"]: row for row in table("slot-signatures")["slots"]}


def gongfa_basis() -> dict[str, Any]:
    g = shapes.gongfa()
    return {"gongfa_jie": int(g["jie"]), "gongfa_digest": g["digest"], "profile_sha256": profile_sha256()}
