"""卡片投影（规格 §3.1.9、HMI H2）：人作决定时所依据的那张卡，是状态的纯函数。

`card_object` 给出进 `card_hash` 的部分，只含与这一个决定有关的字段；内核的 `validate` 与只读端点
`/cards/{kind}/{id}` 用的是同一个函数，所以人在网页或 `pd` 上看到的哈希，就是内核在链头重算的哈希。
审批卡与哈希的语义出自参考模型（refmodel 的 `approval_card`、`card_hash`），这里只做数据形状的转换。
排版用的附带信息（题名、判据卡、估值）在 views.card 里，不进哈希。
"""
from __future__ import annotations

from typing import Any

from . import levels as lv
from . import refmodel as rm
from . import work as wk
from .state import State

Card = dict[str, Any]            # {kind, target, fields}：进 card_hash 的部分
CARD_KINDS = ("approval", "closeout", "extension", "dispute")     # 后两种随 M1


def card_object(state: State, pid: str, kind: str, target: str, ref: tuple[Any, Any] | None = None) -> Card | None:
    """本题的一张卡；对象不存在或不属于本题时返回 None。ref 是已算好的 (参考模型状态, 结果)，省一次重算。"""
    if pid not in state["problems"]:
        return None
    st, res = ref or lv.compute(state, pid)
    if kind == "approval":
        i = state["intents"].get(target)
        if i is None or i["problem_id"] != pid:
            return None
        card: Card = rm.approval_card(st, res, st.intents[target])
        return card
    if kind == "closeout":
        if target != pid:
            return None
        p = state["problems"][pid]
        return {"kind": "closeout", "target": pid,
                "fields": {"items": wk.closeout_items(state, pid), "goal_level": res.levels.get("goal"),
                           "closed": bool(p.get("closed")),
                           "terminal": p.get("terminal", "unsolved") if p.get("closed") else None}}
    return None


def card_hash(card: Card) -> str:
    return str(rm.card_hash(card))


def seen(state: State, pid: str, kind: str, target: str) -> dict[str, Any]:
    """调用方（pd、测试台）从一份状态快照取 seen：人看到的就是这份快照上的卡。"""
    card = card_object(state, pid, kind, target)
    if card is None:
        raise KeyError(f"没有 {kind} 卡 {target}")
    return {"seq": state["seq"], "card_hash": card_hash(card)}
