"""识火与火序的公式（docs/design/fenjue/08-algorithms.md §3.7、§6）：差距、价值、置信、难度、风险、优先级、拓扑排序。

全部可复算（原则 P4）：任何人拿同一份观察与表能算出同一个数。模型可以写注释，不能改数。校验器 V4 用同一组函数重算。
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import data

DIFFICULTY_KEYS = (
    "behavior_slots_minus_1",
    "extra_ports",
    "new_tool",
    "kernel_split",
    "a1_infeasible",
    "run_only_emergent",
)


def gap(dim: str, theirs: int) -> dict[str, Any]:
    """逐维差距：我们的级、外部的级、类型（missing / weaker / new_dim / None 表示持平或更强）。"""
    known = dim in data.dims()
    o = data.ours(dim)
    if not known:
        return {"dim": dim, "ours": 0, "theirs": theirs, "gap": theirs, "type": "new_dim"}
    g = max(0, theirs - o)
    kind = None if g == 0 else ("missing" if o == 0 else "weaker")
    row: dict[str, Any] = {"dim": dim, "ours": o, "theirs": theirs, "gap": g, "type": kind}
    by = data.dims()[dim].get("by")
    if by:
        row["ours_by"] = by
    return row


def value(gaps: Iterable[Mapping[str, Any]]) -> float:
    """V(p) = Σ w_d · gap_d · π_d；新维只作旗帜，不计入。"""
    total = 0.0
    for g in gaps:
        if g["type"] == "new_dim":
            continue
        total += float(g.get("weight", 1)) * int(g["gap"]) * int(g.get("pain", 1))
    return _num(total)


def confidence(
    dims_needed: Sequence[str], obs_by_dim: Mapping[str, Sequence[Mapping[str, Any]]]
) -> tuple[float, dict[str, float]]:
    """C(p) = c₀ × cover × corro，再按形态上限截断。

    c₀ 取观察里最高的形态基数；cover = 有观察作依据的维数 ÷ |D_p|；corro：≥ 2 条独立观察（不同文件或不同形态，
    带 suspected_injection 的不计）为 1，否则 0.7。上限：只有行为观察 ≤ 0.6、只有描述 ≤ 0.4。
    """
    all_obs = [o for d in dims_needed for o in obs_by_dim.get(d, [])]
    forms = {o["form"] for o in all_obs}
    c0 = max((data.FORM_C0[f] for f in forms), default=0.0)
    cap = max((data.FORM_CAP[f] for f in forms), default=0.0)
    covered = sum(1 for d in dims_needed if obs_by_dim.get(d))
    cover = covered / len(dims_needed) if dims_needed else 0.0
    independent = {
        (o["form"], o["evidence"][0].get("path") or str(o["evidence"][0].get("probe_item", "")))
        for o in all_obs
        if not o.get("suspected_injection")
    }
    corro = 1.0 if len(independent) >= 2 else 0.7
    c = min(cap, c0 * cover * corro)
    return _num(round(c, 4)), {"c0": c0, "cover": _num(round(cover, 4)), "corro": corro, "cap": cap}


def difficulty(parts: Mapping[str, int]) -> tuple[int, dict[str, int]]:
    """D(p) = clip(1, 5, 1 + (行为有变的火位数 − 1) + [新经脉] + [新工具] + 2·[拆体质] + [A′ 做不出]
    + [新生维只能靠运行读数])。"""
    p = {"base": 1, **{k: int(parts.get(k, 0)) for k in DIFFICULTY_KEYS}}
    raw = (
        1
        + p["behavior_slots_minus_1"]
        + min(1, p["extra_ports"])
        + min(1, p["new_tool"])
        + 2 * min(1, p["kernel_split"])
        + min(1, p["a1_infeasible"])
        + min(1, p["run_only_emergent"])
    )
    return max(1, min(5, raw)), p


def risk(behavior_slots: Iterable[str], *, strict_lane: bool, kernel_split: bool) -> str:
    """R0 只动 H6、H7 读端；R1 改会话行为、只在开放道；R2 影响严格道；R3 有守门部分要拆去体质修炼。"""
    if kernel_split:
        return "R3"
    if strict_lane:
        return "R2"
    if any(s in data.SESSION_SLOTS for s in behavior_slots):
        return "R1"
    return "R0"


def priority(v: float, c: float, d: int, r: str) -> float:
    """P = (V × C) ÷ (D × (1 + R))。"""
    return _num(round(v * c / (d * (1 + data.RISK_LEVEL[r])), 4))


def _num(x: float) -> float:
    """整数值的浮点保持为 float（JSON 里写 1.0），其余保留四位。"""
    return float(x)


# ---------------------------------------------------------------- 火序（08 §6）


@dataclass(frozen=True)
class Item:
    cid: str
    v: float
    c: float
    d: int
    r: str
    p: float = field(default=0.0)


@dataclass
class Order:
    order: list[dict[str, Any]]
    held: list[dict[str, Any]]
    cycle: list[str]


def _cnum(cid: str) -> int:
    return int(cid[1:])


def _rank(it: Item) -> tuple[float, int, int, int]:
    """就绪集合的取用次序：P 大者先；平局 R 小、D 小、编号小者先。"""
    return (-it.p, data.RISK_LEVEL[it.r], it.d, _cnum(it.cid))


def slot_edges(cands: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """先后边：候选 X 的主火位是会话火位，且候选 Y 兼及它（或主火位相同）→ 按排序先者指向后者。

    H6、H7 只动读端，共用它们不构成先后（例：两个候选都兼及 H6 不排队）。
    """
    items = {
        c["id"]: Item(c["id"], c["value"], c["confidence"], c["difficulty"], c["risk"], c["priority"]) for c in cands
    }
    edges: set[tuple[str, str]] = set()
    for x in cands:
        if x["slot"] not in data.SESSION_SLOTS:
            continue
        for y in cands:
            if y["id"] == x["id"]:
                continue
            if x["slot"] == y["slot"] or x["slot"] in y.get("also_slots", []):
                a, b = sorted((x["id"], y["id"]), key=lambda k: _rank(items[k]))
                edges.add((a, b))
    return sorted(edges)


def fire_order(
    items: Sequence[Item],
    *,
    deps: Iterable[tuple[str, str]] = (),
    after: Iterable[tuple[str, str]] = (),
    exclusive: Iterable[tuple[str, str]] = (),
) -> Order:
    """互斥对只留 P 高者；依赖边与先后边建图；有环报告不打破；Kahn 排序，就绪集合按 `_rank` 取。"""
    by = {it.cid: it for it in items}
    held: list[dict[str, Any]] = []
    for a, b in exclusive:
        if a in by and b in by:
            lose = max((by[a], by[b]), key=_rank)
            other = a if lose.cid == b else b
            held.append({"candidate": lose.cid, "why": f"互斥待定：与 {other} 二选一"})
            del by[lose.cid]
    edges = {(a, b) for a, b in [*deps, *after] if a in by and b in by}
    preds: dict[str, set[str]] = {k: set() for k in by}
    for a, b in edges:
        preds[b].add(a)
    indeg = {k: len(v) for k, v in preds.items()}
    ready = [(_rank(by[k]), k) for k, n in indeg.items() if n == 0]
    heapq.heapify(ready)
    out: list[dict[str, Any]] = []
    while ready:
        _, k = heapq.heappop(ready)
        it = by[k]
        row: dict[str, Any] = {"candidate": k, "position": len(out) + 1, "P": it.p}
        waits = sorted(preds[k], key=_cnum)
        if waits:
            row["waits_for"] = waits
        row["why"] = f"P = {_fmt(it.v)}×{_fmt(it.c)} ÷ ({it.d}×{1 + data.RISK_LEVEL[it.r]}) = {_fmt(it.p)}，风险 {it.r}"
        out.append(row)
        for a, b in sorted(edges):
            if a == k:
                indeg[b] -= 1
                if indeg[b] == 0:
                    heapq.heappush(ready, (_rank(by[b]), b))
    cycle = sorted((k for k, n in indeg.items() if n > 0), key=_cnum)
    return Order(out, held, cycle)


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)
