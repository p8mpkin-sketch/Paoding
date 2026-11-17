"""授权编译（§3.6.2）：scope × 风险上限 × 批准 → ExecSpec。确定性纯函数，不做 IO。

能力按风险注入：只取 risk 不高于上限的规则；r2 规则另须该 Intent 已获批准。
内核不理解 resource，由资源种类插件解释（RESOURCE_KINDS）。M0 只有网络地址一种，外加 workspace（M3）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

RISK_RANK = {"r0": 0, "r1": 1, "r2": 2}


@dataclass(frozen=True)
class ResourceKind:
    kind: str
    external: bool

    def compile(self, rule: dict) -> dict:
        raise NotImplementedError


class NetAddress(ResourceKind):
    """pattern 是 host 或 host:port。只放行到这些地址的出站；其余一律不通。"""

    def compile(self, rule: dict) -> dict:
        return {"egress": [rule["pattern"]]}


class Workspace(ResourceKind):
    """只放行本题工作区，不开任何出站（蓝图 C1，M3 正式启用）。"""

    def compile(self, rule: dict) -> dict:
        return {}


RESOURCE_KINDS: dict[str, ResourceKind] = {
    "net": NetAddress("net", external=False),
    "workspace": Workspace("workspace", external=False),
}


@dataclass(frozen=True)
class Limits:
    cpu: float = 1.0
    mem_mb: int = 512
    pids: int = 128
    wall_s: int = 600


@dataclass(frozen=True)
class ExecSpec:
    id: str
    image: str
    baseline_ref: str
    workspace: str
    egress_allow: tuple = ()
    credentials: tuple = ()
    limits: Limits = field(default_factory=Limits)


class ScopeError(ValueError):
    pass


def compile_spec(spec_id: str, scope: list[dict], env: dict, ceiling: str, approved_r2: bool,
                 workspace: str, limits: Limits = Limits(),
                 kinds: dict[str, ResourceKind] = RESOURCE_KINDS) -> ExecSpec:
    """ceiling：所服务 Intent 的 risk（Bootstrap 取 r0；判官容器取被判对象的风险但不超过 r1）。"""
    if ceiling not in RISK_RANK:
        raise ScopeError(f"上限非法：{ceiling}")
    egress: list[str] = []
    creds: list[str] = []
    for rule in scope:
        if RISK_RANK[rule["risk"]] > RISK_RANK[ceiling]:
            continue
        if rule["risk"] == "r2" and not approved_r2:
            continue
        kind = kinds.get(rule["resource"])
        if kind is None:
            raise ScopeError(f"没有资源种类插件解释 {rule['resource']!r}")
        out = kind.compile(rule)
        egress += out.get("egress", [])
        creds += out.get("credentials", [])
    return ExecSpec(id=spec_id, image=env["base"], baseline_ref=env["baseline_ref"], workspace=workspace,
                    egress_allow=tuple(sorted(set(egress))), credentials=tuple(sorted(set(creds))),
                    limits=limits)
