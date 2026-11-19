"""判官注册表（§3.3.2）：一个配置目录，每个文件一条 JudgeSpec。Worker 不可写；领域词只允许出现在这些配置里。

图服务开题时把条目的 version、grade、kind、max_cost 抄进题目的判官快照，裁决时再抄进支持记录，
所以重放不依赖这个目录。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .connector import ProfileError, validate_profile

KINDS = ("deterministic", "programmatic", "panel", "deferred")
AUTHORITIES = ("local", "external")  # 判定来源（external-verdict §5.1）；人工验收走 goal.accept，不进注册表
GRADES = ("decisive", "consistent", "advisory")
FORMS = ("answer", "command", "external")  # 一句话开题的判据形态；外部裁决的条目恒为 external
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "judges.d"
CONNECTORS_DIR = Path(__file__).resolve().parents[2] / "connectors.d"


class RegistryError(ValueError):
    pass


def load_registry(directory: str | Path = DEFAULT_DIR) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
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
        spec.setdefault("authority", "local")
        if spec["authority"] not in AUTHORITIES:
            raise RegistryError(f"{f.name}：authority 取 {AUTHORITIES}")
        if spec["authority"] == "external":
            if spec["kind"] != "deferred":
                raise RegistryError(f"{f.name}：外部裁决的判官 kind 须为 deferred（回执异步到达）")
            if not isinstance((spec.get("params") or {}).get("connector"), str):
                raise RegistryError(f"{f.name}：外部裁决的判官须在 params.connector 指明连接器档案")
        if spec["authority"] == "external":
            spec.setdefault("form", "external")
        if spec.get("form") is not None and (
            spec["form"] not in FORMS or (spec["form"] == "external") != (spec["authority"] == "external")
        ):
            raise RegistryError(f"{f.name}：form 取 {FORMS}，external 与 authority: external 互为充要")
        spec.setdefault("flake", {"reruns": 0, "require": "all"})
        spec.setdefault("params", {})
        spec.setdefault("timeout_s", 60)
        spec.setdefault("max_cost", {"usd_milli": 0, "wall_s": 60})
        out[spec["id"]] = spec
    return out


def load_connectors(directory: str | Path = CONNECTORS_DIR) -> dict[str, dict[str, Any]]:
    """连接器档案（external-verdict §5.1）：一个文件一份平台档案，领域词只在这里（红线 3）。

    形状按 connector.validate_profile 校验，不合即启动失败；id、version 与整份档案的摘要（规范化 JSON 的 sha256）
    供开题时抄进判官快照，端点、字段、映射表由 connector 运行器解释。目录不存在即没有档案。"""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(Path(directory).glob("*.y*ml")) if Path(directory).is_dir() else []:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        try:
            validate_profile(doc, f.name)
        except ProfileError as e:
            raise RegistryError(str(e)) from None
        if doc["id"] in out:
            raise RegistryError(f"{f.name}：连接器 {doc['id']} 重复")
        canon = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        out[doc["id"]] = {"version": str(doc["version"]), "digest": hashlib.sha256(canon).hexdigest(), "doc": doc}
    return out


def kernel_judges(
    registry: dict[str, dict[str, Any]], connectors: dict[str, dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """图服务 Config.judges 的形状：judge_id → {version, grade, kind, max_cost（美元）}。

    外部裁决的判官另带 authority=external 与连接器档案的 {id, version, digest}；档案没加载时不带 connector，
    图服务据此拒绝以它开题。本地判官的条目与旧版逐字相同。"""
    out: dict[str, dict[str, Any]] = {}
    for jid, s in sorted(registry.items()):
        e: dict[str, Any] = {
            "version": s["version"],
            "grade": s["grade"],
            "kind": s["kind"],
            "max_cost": s["max_cost"].get("usd_milli", 0) / 1000,
        }
        if s.get("authority", "local") == "external":
            e["authority"] = "external"
            cid = s["params"]["connector"]
            c = (connectors or {}).get(cid)
            if c is not None:
                e["connector"] = {"id": cid, "version": c["version"], "digest": c["digest"]}
        out[jid] = e
    return out
