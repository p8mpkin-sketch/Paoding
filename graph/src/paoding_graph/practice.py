"""练习道信封（一句话开题设计 §4.4；内核增量 13、15）。

信封是一份人签的策略：在它之内的开题不要求逐题确认（零确认）。图服务启动时由组装根交进来（Config.practice），
开题时把它的 (版本, 摘要) 抄进事件体，重放只读事件体，不读策略文件（与 judge_snapshot、settings 同法）。

`open_problem` 的 `origin.draft.lane = practice` 时逐条核对，任一条不满足整单拒绝（forbidden_op）：
- 每条 scope 规则的资源在 allow.resources 内、风险 ≤ allow.max_risk；net 规则的 pattern 匹配 allow.net_patterns 之一；
- Goal 判官在 judge.ids 内；judge.require_sealed 时 check.sealed 非空；
- budget.usd_milli ≤ budget.usd_milli_max，budget.wall_s ≤ budget.wall_s_max；
- goal.max_attempts ≤ goal.max_attempts_max。
`lane = confirm` 或不带 origin.draft 的开题不受信封限制（人确认过）。

策略的形状由这里定义与检查；内容（地址白名单、判官）是数据，由组装根从起草组件的数据目录与设置层合成。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from .envelope import sha256_hex
from .jcs import canonicalize

RISK_RANK = {"r0": 0, "r1": 1, "r2": 2}
LANES = ("practice", "confirm")


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PracticePolicy:
    version: int
    digest: str  # sha256(JCS(策略全文))
    resources: tuple[str, ...]
    net_patterns: tuple[str, ...]
    max_risk: str
    judge_ids: tuple[str, ...]
    require_sealed: bool
    usd_milli_max: int
    wall_s_max: int
    max_attempts_max: int

    def stamp(self) -> dict[str, Any]:
        return {"version": self.version, "digest": self.digest}


def _strs(v: Any, what: str) -> tuple[str, ...]:
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x for x in v):
        raise PolicyError(f"{what} 须为非空字符串列表")
    return tuple(v)


def _pos(v: Any, what: str) -> int:
    if type(v) is not int or v <= 0:
        raise PolicyError(f"{what} 须为正整数")
    return v


def load_policy(doc: Any) -> PracticePolicy:
    """策略全文 → PracticePolicy。形状不对即 PolicyError（启动失败，不带着坏策略跑）。"""
    if not isinstance(doc, Mapping) or set(doc) != {"version", "allow", "judge", "budget", "goal"}:
        raise PolicyError("信封须且只须有 version、allow、judge、budget、goal")
    allow, judge, budget, goal = (doc[k] for k in ("allow", "judge", "budget", "goal"))
    if not all(isinstance(x, Mapping) for x in (allow, judge, budget, goal)):
        raise PolicyError("allow、judge、budget、goal 须为映射")
    if set(allow) != {"resources", "net_patterns", "max_risk"} or allow["max_risk"] not in RISK_RANK:
        raise PolicyError("allow 须为 {resources, net_patterns, max_risk ∈ r0/r1/r2}")
    if set(judge) != {"ids", "require_sealed"} or not isinstance(judge["require_sealed"], bool):
        raise PolicyError("judge 须为 {ids, require_sealed: bool}")
    if set(budget) != {"usd_milli_max", "wall_s_max"} or set(goal) != {"max_attempts_max"}:
        raise PolicyError("budget 须为 {usd_milli_max, wall_s_max}，goal 须为 {max_attempts_max}")
    return PracticePolicy(
        version=_pos(doc["version"], "version"),
        digest=sha256_hex(canonicalize(dict(doc))),
        resources=_strs(allow["resources"], "allow.resources"),
        net_patterns=_strs(allow["net_patterns"], "allow.net_patterns"),
        max_risk=str(allow["max_risk"]),
        judge_ids=_strs(judge["ids"], "judge.ids"),
        require_sealed=judge["require_sealed"],
        usd_milli_max=_pos(budget["usd_milli_max"], "budget.usd_milli_max"),
        wall_s_max=_pos(budget["wall_s_max"], "budget.wall_s_max"),
        max_attempts_max=_pos(goal["max_attempts_max"], "goal.max_attempts_max"),
    )


def rule_violations(p: PracticePolicy, rules: list[Mapping[str, Any]], where: str = "rules") -> list[str]:
    """授权规则不在信封里的每一条。开题时查 scope，运行时扩权的练习道自动批准查申请的规则（同一套判定）。"""
    out: list[str] = []
    for i, r in enumerate(rules):
        if r["resource"] not in p.resources:
            out.append(f"{where}[{i}] 的资源 {r['resource']} 不在信封里")
        if RISK_RANK[r["risk"]] > RISK_RANK[p.max_risk]:
            out.append(f"{where}[{i}] 的风险 {r['risk']} 高于 {p.max_risk}")
        if r["resource"] == "net" and not any(fnmatchcase(r["pattern"], g) for g in p.net_patterns):
            out.append(f"{where}[{i}] 的地址 {r['pattern']} 不在白名单里")
    return out


def violations(
    p: PracticePolicy,
    scope: list[Mapping[str, Any]],
    check: Mapping[str, Any],
    budget: Mapping[str, Any],
    max_attempts: int,
) -> list[str]:
    """不在信封里的每一条，空即在信封内。纯函数。"""
    out = rule_violations(p, scope, "scope")
    if check["judge_id"] not in p.judge_ids:
        out.append(f"Goal 判官 {check['judge_id']} 不在信封里")
    if p.require_sealed and not check.get("sealed"):
        out.append("没有封存的答案（sealed）")
    if budget["usd_milli"] > p.usd_milli_max:
        out.append(f"budget.usd_milli={budget['usd_milli']} 超过练习上限 {p.usd_milli_max}")
    if budget["wall_s"] > p.wall_s_max:
        out.append(f"budget.wall_s={budget['wall_s']} 超过练习上限 {p.wall_s_max}")
    if max_attempts > p.max_attempts_max:
        out.append(f"max_attempts={max_attempts} 超过 {p.max_attempts_max}")
    return out
