"""授权编译（§3.6.2）：scope × 风险上限 × 批准 → ExecSpec。确定性纯函数，不做 IO。

能力按风险注入：只取 risk 不高于上限的规则；r2 规则另须该 Intent 已获批准。
内核不理解 resource，由资源种类插件解释（RESOURCE_KINDS）。M0 只有网络地址一种，外加 workspace（M3）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from paoding_graph.contract import RESOURCE_EXTERNAL


class ScopeError(ValueError):
    pass


RISK_RANK = {"r0": 0, "r1": 1, "r2": 2}


@dataclass(frozen=True)
class ResourceKind:
    kind: str
    external: bool

    def compile(self, rule: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


CONNECT_ACTIONS = frozenset({"connect", "*"})  # 放行出站连接的动作；其余动作 M0 没有执行手段，一律不开通路


def split_address(pattern: str) -> tuple[str, int]:
    """host:port → (host, port)。端口必须写明：出站放行到端口为止，没有"整台主机"这一档（异议报告 006 第 1 项）。"""
    host, sep, port = str(pattern).rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ScopeError(f"net 规则的 pattern 必须是 host:port：{pattern!r}")
    return host, int(port)


class NetAddress(ResourceKind):
    """pattern 是 host:port。只放行到这些地址的出站连接；同一主机的其他端口与其余地址一律不通。

    egress：actions 含 connect（或 *）的地址，出站闸门为它开转发。
    rules：全部地址连同各自的 actions，原样交给闸门，由闸门决定开不开（不含 connect 的不开）。"""

    def compile(self, rule: Mapping[str, Any]) -> dict[str, Any]:
        split_address(rule["pattern"])
        actions = tuple(sorted({str(a) for a in rule.get("actions") or ()}))
        return {
            "egress": [rule["pattern"]] if CONNECT_ACTIONS & set(actions) else [],
            "rules": [(rule["pattern"], actions)],
        }


class Workspace(ResourceKind):
    """只放行本题工作区，不开任何出站（蓝图 C1，M3 正式启用）。"""

    def compile(self, rule: Mapping[str, Any]) -> dict[str, Any]:
        return {}


_IMPL = {"net": NetAddress, "workspace": Workspace}
# external 取自 graph 的登记表（单一事实源）；这里只挂编译行为。键集合不一致时导入即失败。
if set(_IMPL) != set(RESOURCE_EXTERNAL):
    raise RuntimeError(f"资源种类与 graph 登记表不一致：{sorted(_IMPL)} vs {sorted(RESOURCE_EXTERNAL)}")
RESOURCE_KINDS: dict[str, ResourceKind] = {k: cls(k, external=RESOURCE_EXTERNAL[k]) for k, cls in _IMPL.items()}


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
    egress_allow: tuple[Any, ...] = ()  # 放行出站连接的 host:port
    credentials: tuple[Any, ...] = ()
    limits: Limits = field(default_factory=Limits)
    egress_rules: tuple[Any, ...] = ()  # ((host:port, (动作…)), …)：闸门据此逐端口执行；同一地址的动作取并集


def compile_spec(
    spec_id: str,
    scope: Sequence[Mapping[str, Any]],
    env: dict[str, Any],
    ceiling: str,
    approved_r2: bool,
    workspace: str,
    limits: Limits = Limits(),
    kinds: dict[str, ResourceKind] = RESOURCE_KINDS,
) -> ExecSpec:
    """ceiling：所服务 Intent 的 risk（Bootstrap 取 r0；判官容器取被判对象的风险但不超过 r1）。"""
    if ceiling not in RISK_RANK:
        raise ScopeError(f"上限非法：{ceiling}")
    egress: list[str] = []
    creds: list[str] = []
    rules: dict[str, set[str]] = {}
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
        for pattern, actions in out.get("rules", []):
            rules.setdefault(pattern, set()).update(actions)
    return ExecSpec(
        id=spec_id,
        image=env["base"],
        baseline_ref=env["baseline_ref"],
        workspace=workspace,
        egress_allow=tuple(sorted(set(egress))),
        credentials=tuple(sorted(set(creds))),
        limits=limits,
        egress_rules=tuple((p, tuple(sorted(a))) for p, a in sorted(rules.items())),
    )
