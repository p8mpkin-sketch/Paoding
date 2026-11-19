"""校验层读的确定性数据：开题模板数据（kaiti.d/intake.yaml）、练习道信封、设置层快照、预算先验数据源。

设置层的形状以生命周期地图（PR #84）为准：GET /v1/settings → {version, digest, settings}，
settings = {caps: {...}, risk: [...], models: {profiles: [...], routes: {...}}}。一期由调用方把 settings 对象交进来。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from .extract import Extraction, extract

DATA_DIR = Path(__file__).with_name("kaiti.d")
RISKS = ("r0", "r1", "r2")
RISK_RANK = {r: i for i, r in enumerate(RISKS)}


# ---------- 预算先验：可插拔数据源（设计 §5.2） ----------


@dataclass(frozen=True)
class Prior:
    usd_milli: int
    wall_s: int
    bootstrap_share: float | None = None
    note: str = ""


class PriorSource(Protocol):
    """档位 → 默认预算。实现方不限（注入的表、M2 花费画像的投影）；vet 只认这个接口。"""

    def lookup(self, tier: str, signature: str | None) -> Prior | None: ...

    def version(self) -> str: ...


class PriorTableError(ValueError):
    pass


@dataclass(frozen=True)
class TablePriors:
    """外部注入的"档位 → 默认预算"表。格式见 kaiti.d/priors.placeholder.yaml。"""

    tiers: Mapping[str, Prior]
    source: str
    ver: str

    @classmethod
    def from_doc(cls, doc: Any) -> TablePriors:
        if not isinstance(doc, dict) or not isinstance(doc.get("tiers"), dict):
            raise PriorTableError("先验表须有 tiers 映射")
        tiers: dict[str, Prior] = {}
        for name, row in doc["tiers"].items():
            if not isinstance(row, dict):
                raise PriorTableError(f"档位 {name} 须是映射")
            usd, wall = row.get("usd_milli"), row.get("wall_s")
            if type(usd) is not int or type(wall) is not int or usd <= 0 or wall <= 0:
                raise PriorTableError(f"档位 {name} 的 usd_milli 与 wall_s 须为正整数")
            bs = row.get("bootstrap_share")
            if bs is not None and not (isinstance(bs, int | float) and 0 <= bs <= 1):
                raise PriorTableError(f"档位 {name} 的 bootstrap_share 须在 [0,1]")
            tiers[str(name)] = Prior(usd, wall, None if bs is None else float(bs), str(row.get("note", "")))
        return cls(tiers, str(doc.get("source", "injected")), str(doc.get("version", "unversioned")))

    @classmethod
    def load(cls, path: str | Path) -> TablePriors:
        return cls.from_doc(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def lookup(self, tier: str, signature: str | None) -> Prior | None:
        return self.tiers.get(tier)

    def version(self) -> str:
        return f"{self.source}:{self.ver}"

    @property
    def placeholder(self) -> bool:
        return self.source == "placeholder"


def placeholder_priors() -> TablePriors:
    return TablePriors.load(DATA_DIR / "priors.placeholder.yaml")


# ---------- 设置层快照 ----------

DEFAULT_CAPS = {
    "global_usd_milli": 500_000,
    "open_usd_milli": 20_000,
    "open_wall_s": 14_400,
    "practice_usd_milli": 500,
    "practice_wall_s": 1_800,
}  # 占位，设置页给出真实值


@dataclass(frozen=True)
class Settings:
    caps: Mapping[str, int]
    risk: tuple[Mapping[str, Any], ...]
    models: Mapping[str, Any] = field(default_factory=dict)
    version: str = "default"

    @classmethod
    def from_doc(cls, doc: Any) -> Settings:
        """doc 是 /v1/settings 的应答（{version, digest, settings}）或其中的 settings 对象。"""
        d = doc.get("settings", doc) if isinstance(doc, dict) else {}
        caps = {**DEFAULT_CAPS, **{k: int(v) for k, v in (d.get("caps") or {}).items()}}
        risk = tuple(dict(r) for r in (d.get("risk") or []))
        for r in risk:
            if r.get("risk") not in RISKS:
                raise ValueError(f"风险表条目的 risk 须为 r0/r1/r2：{r}")
        ver = str(doc.get("version", "default")) if isinstance(doc, dict) else "default"
        return cls(caps, risk, dict(d.get("models") or {}), ver)

    def risk_of(self, resource: str, pattern: str, actions: list[str]) -> tuple[str, int | None]:
        """顺序匹配风险表，返回 (风险, 命中的行号)；未命中按 r2（规格 3.1.2 的缺省）。"""
        from fnmatch import fnmatchcase

        for i, r in enumerate(self.risk):
            if r.get("resource") != resource or not fnmatchcase(pattern, str(r.get("pattern", ""))):
                continue
            allowed = set(r.get("actions") or ["*"])
            if "*" in allowed or set(actions) <= allowed:
                return str(r["risk"]), i
        return "r2", None

    def draft_profile(self, name: str | None) -> Mapping[str, Any] | None:
        """起草模型档案：缺省取 models.routes.draft；可覆盖为任一已登记档案名，不许填端点或密钥。"""
        name = name or (self.models.get("routes") or {}).get("draft")
        if not name:
            return None
        for p in self.models.get("profiles") or []:
            if p.get("name") == name:
                return dict(p)
        raise ValueError(f"没有登记名为 {name!r} 的模型档案")


# ---------- 模板数据与信封 ----------


@dataclass(frozen=True)
class Intake:
    labels: list[str]
    url_ports: dict[str, int]
    defaults: Mapping[str, Any]
    zero_confirm: bool
    envelope: Mapping[str, Any]
    money_rates: dict[str, float] = field(default_factory=lambda: {"usd": 1.0})
    host_tlds: tuple[str, ...] | None = None  # None → extract 的缺省表

    def extract(self, raw: str) -> Extraction:
        """按本模板数据做前置抽取（各调用点统一走这里，免得漏传换算表或顶级域表）。"""
        return extract(raw, self.labels, self.url_ports, money_rates=self.money_rates, host_tlds=self.host_tlds)

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> Intake:
        doc = yaml.safe_load((data_dir / "intake.yaml").read_text(encoding="utf-8"))
        env = yaml.safe_load((data_dir / "practice.yaml").read_text(encoding="utf-8"))
        return cls(
            [str(x) for x in doc["answer_labels"]],
            {str(k): int(v) for k, v in doc["url_ports"].items()},
            dict(doc["defaults"]),
            bool(doc.get("zero_confirm", False)),
            dict(env),
            {str(k): float(v) for k, v in (doc.get("money_rates") or {"usd": 1.0}).items()},
            tuple(str(x) for x in doc["host_tlds"]) if doc.get("host_tlds") else None,
        )
