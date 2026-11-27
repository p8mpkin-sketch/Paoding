"""提炼结果的九栏是否齐全：提炼（萃意）与归位（入位）之间那条边界上的唯一判据。

归位、交接与各份报告都直接读遮蔽视图里的栏目（`masked.fusion.emergent`、`masked.statement`……）。模型答成别的
形状时，这些读取以前是到了下游才以 KeyError 崩掉，而且错算在下游那个单元头上。现在分两处把住：

- 进门（`sound`）：模型的回答先按 Schema 的“必填”与“类型”过一遍，形状不对的栏整栏不收，问题逐条记下交回重写。
  收下的每一栏因此都是 Schema 认得的形状，后面的检验与渲染不必再猜；
- 出门（`gaps`）：进入归位之前问一句“九栏齐不齐”。不齐的不进归位，标“提炼不出”并写明缺什么。

判据取自 `essence.schema.json#/$defs/masked`（单一事实源），只看“缺必填栏”与“类型不对”两类：长度、枚举、正则是
内容问题，归 K1 管，人在确认点上可以坚持；缺栏和类型不对会让下游读不下去，谁也坚持不了。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import schema

# 九栏，按 Schema 的必填顺序：statement、mechanism、premises、costs、overlaps、conflicts、fusion、split、implementations
SECTIONS: tuple[str, ...] = tuple(schema.load("essence")["$defs"]["masked"]["required"])
_STRUCTURAL = re.compile(r": (缺 |应为 )")  # schema._check 的两类报法：缺必填键、类型不对
_TOP = re.compile(r"^/([^/:]+)")


def structural(masked: Any) -> list[str]:
    """遮蔽视图的结构问题（缺必填栏、类型不对），逐条带 JSON 指针；空列表即形状齐全。"""
    if not isinstance(masked, dict):
        return ["/: 应为 object"]
    return [e for e in schema.def_errors(masked, "essence", "masked") if _STRUCTURAL.search(e)]


def gaps(essence: Any) -> list[str]:
    """这份提炼结果缺什么才进不了归位；空列表即九栏齐全。"""
    if not isinstance(essence, Mapping):
        return ["提炼结果不是对象"]
    return structural(essence.get("masked"))


def sound(masked: Any) -> tuple[dict[str, Any], list[str]]:
    """进门：只收形状对的栏。交回（收下的遮蔽视图，被丢掉的栏各自的问题）。

    丢栏而不是修栏：修是替模型猜，丢了之后那一栏就是“缺”，K1 照实报，重写时模型看得到原因。"""
    if not isinstance(masked, dict):
        return {}, []
    bad: dict[str, list[str]] = {}
    for e in structural(masked):
        m = _TOP.match(e)
        if m and m.group(1) in masked:
            bad.setdefault(m.group(1), []).append(e)
    dropped = [f"{k} 一栏的形状不对，没有收下：{'；'.join(v[:4])}" for k, v in bad.items()]
    return {k: v for k, v in masked.items() if k not in bad}, dropped


def describe(essence: Any) -> str:
    """给人看的一句：缺哪几栏、哪几栏里缺东西。"""
    found = gaps(essence)
    missing = [e.rsplit("缺 ", 1)[1] for e in found if e.startswith("/: 缺 ")]
    rest = [e for e in found if not e.startswith("/: 缺 ")]
    parts = []
    if missing:
        parts.append(f"缺 {'、'.join(missing)} {len(missing)} 栏")
    if rest:
        parts.append("；".join(rest[:4]))
    return "；".join(parts)[:300]


def received(output: Any) -> str:
    """模型回答的顶层长什么样（只列键名，不带内容）。"""
    if not isinstance(output, dict):
        return "没有解析出 JSON 对象"
    return "、".join(sorted(str(k) for k in output)[:20]) or "（空对象）"


def expected() -> str:
    return (
        "一个 JSON 对象，顶层只有 masked、field_refs、plain_summary 三个键；"
        f"{len(SECTIONS)} 栏（{'、'.join(SECTIONS)}）都写在 masked 里面，一栏不能少，"
        "mechanism 的每一步是 masked.mechanism 列表里的一项，不是顶层的键"
    )


def shape_error(output: Any, masked: Any) -> str:
    """交回给模型的那一条：期望的形状，和这次收到的顶层键。"""
    got = f"收到的顶层键：{received(output)}"
    if isinstance(output, dict) and isinstance(output.get("masked"), dict):
        inner = "、".join(sorted(str(k) for k in output["masked"])[:20]) or "（空）"
        got += f"；masked 里收到的键：{inner}"
    elif isinstance(output, dict) and "masked" in output:
        got += f"；masked 不是对象（是 {type(output['masked']).__name__}）"
    lack = [s for s in SECTIONS if not isinstance(masked, dict) or s not in masked]
    tail = f"；还缺：{'、'.join(lack)}" if lack else ""
    return f"输出的形状不对。期望的形状：{expected()}。{got}{tail}"
