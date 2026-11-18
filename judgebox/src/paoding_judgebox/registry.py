"""判官注册表（§3.3.2）：一个配置目录，每个文件一条 JudgeSpec。Worker 不可写；领域词只允许出现在这些配置里。

图服务开题时把条目的 version、grade、kind、max_cost 抄进题目的判官快照，裁决时再抄进支持记录，
所以重放不依赖这个目录。
"""
from __future__ import annotations

from pathlib import Path

import yaml

KINDS = ("deterministic", "programmatic", "panel", "deferred")
GRADES = ("decisive", "consistent", "advisory")
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "judges.d"


class RegistryError(ValueError):
    pass


def load_registry(directory: str | Path = DEFAULT_DIR) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(Path(directory).glob("*.y*ml")):
        spec = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(spec, dict) or not isinstance(spec.get("id"), str):
            raise RegistryError(f"{f.name}：缺 id")
        if spec["id"] in out:
            raise RegistryError(f"{f.name}：判官 {spec['id']} 重复")
        if spec.get("kind") not in KINDS or spec.get("grade") not in GRADES:
            raise RegistryError(f"{f.name}：kind 取 {KINDS}，grade 取 {GRADES}")
        spec["version"] = str(spec.get("version", ""))
        if not spec["version"]:
            raise RegistryError(f"{f.name}：缺 version")
        spec.setdefault("flake", {"reruns": 0, "require": "all"})
        spec.setdefault("params", {})
        spec.setdefault("timeout_s", 60)
        spec.setdefault("max_cost", {"usd_milli": 0, "wall_s": 60})
        out[spec["id"]] = spec
    return out


def kernel_judges(registry: dict[str, dict]) -> dict[str, dict]:
    """图服务 Config.judges 的形状：judge_id → {version, grade, kind, max_cost（美元）}。"""
    return {jid: {"version": s["version"], "grade": s["grade"], "kind": s["kind"],
                  "max_cost": s["max_cost"].get("usd_milli", 0) / 1000} for jid, s in sorted(registry.items())}
