"""通鉴日志的 reducer（规格 2.4：与题日志同一种基质；01-memory §3）。validate 与 apply 都是纯函数。

事件（problem_id 固定为 LOG）：

    case_sealed   通鉴服务  {case}                 关题即封存；case.recall_outcomes 是记忆状态更新的唯一入口
    mem_derived   通鉴服务  {case, items}          判例往下的二次投影；开关 case_seal=off 时不写
    mem_pin       人        {item, reason, seen}   钉住：休眠时仍召回，对过期、退役无效
    mem_forget    人        {item, reason, seen}   遗忘：条目退役，已开题的召回清单不受影响

记忆状态不存储、不可写，是事件的派生量（mem_state），与等级同构：

    retired  被人遗忘；或最近两次复核都没通过（该环境已变）
    stale    否则若最近一次复核没通过
    dormant  否则若最近 N 次被召回且复核通过，却一次都不在新题的解题链上
    active   其它；pinned 是叠加标记，只把 dormant 当 active 召回
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .keys import digest

LOG = "tongjian"
DORMANT_N = 10
WRITERS = {"case_sealed": "graph", "mem_derived": "graph", "mem_pin": "human", "mem_forget": "human"}
KINDS = tuple(WRITERS)

TState = dict[str, Any]


@dataclass(frozen=True)
class Ok:
    body: dict[str, Any]


@dataclass(frozen=True)
class Reject:
    code: str
    detail: str = ""


def empty() -> TState:
    return {"seq": 0, "now": 0, "cases": {}, "derived": [], "items": {}, "recalls": {}, "pins": {}, "forgotten": {}}


# ---------- 派生状态 ----------


def history(st: Mapping[str, Any], mid: str) -> list[Mapping[str, Any]]:
    return cast(list[Mapping[str, Any]], st["recalls"].get(mid, []))


def mem_state(st: Mapping[str, Any], mid: str) -> str:
    if mid in st["forgotten"]:
        return "retired"
    judged = [h for h in history(st, mid) if h["verdict"] in ("pass", "fail", "flaky")]
    if len(judged) >= 2 and all(h["verdict"] != "pass" for h in judged[-2:]):
        return "retired"
    if judged and judged[-1]["verdict"] != "pass":
        return "stale"
    passed = [h for h in judged if h["verdict"] == "pass"]
    if len(passed) >= DORMANT_N and not any(h["on_chain"] for h in passed[-DORMANT_N:]):
        return "dormant"
    return "active"


def recallable(st: Mapping[str, Any], mid: str) -> bool:
    s = mem_state(st, mid)
    return s == "active" or (s == "dormant" and bool(st["pins"].get(mid)))


def card(st: Mapping[str, Any], mid: str) -> dict[str, Any]:
    """人钉住或遗忘之前看到的卡：条目本身、派生状态、历次复核。seen.card_hash 绑定它（HMI H2 同一机制）。"""
    return {
        "item": st["items"][mid],
        "state": mem_state(st, mid),
        "pinned": bool(st["pins"].get(mid)),
        "recalls": list(history(st, mid)),
    }


def card_hash(st: Mapping[str, Any], mid: str) -> str:
    return digest(card(st, mid))


# ---------- validate ----------


def validate(st: Mapping[str, Any], actor: Mapping[str, Any], kind: str, body: Mapping[str, Any]) -> Ok | Reject:
    if kind not in WRITERS:
        return Reject("schema_error", f"未知操作 {kind}")
    if actor.get("kind") != WRITERS[kind]:
        return Reject("forbidden_op", f"{actor.get('kind')} 不能提交 {kind}")
    if kind == "case_sealed":
        c = body.get("case")
        if not isinstance(c, dict) or not isinstance(c.get("seal"), dict):
            return Reject("schema_error", "case_sealed 须带 case.seal")
        if c["seal"]["problem_id"] in st["cases"]:
            return Reject("schema_error", "这道题已封存")
        return Ok({"case": c})
    if kind == "mem_derived":
        pid, items = body.get("case"), body.get("items")
        if pid not in st["cases"] or pid in st["derived"]:
            return Reject("schema_error", "判例未封存或已投影过")
        if not isinstance(items, list) or any(not isinstance(m, dict) or "id" not in m for m in items):
            return Reject("schema_error", "items 须为带 id 的条目列表")
        return Ok({"case": pid, "items": items})
    mid, reason, seen = body.get("item"), body.get("reason"), body.get("seen")
    if not isinstance(mid, str) or mid not in st["items"]:
        return Reject("unknown_ref", "记忆条目不存在")
    if not isinstance(reason, str) or not reason.strip():
        return Reject("schema_error", "须写理由")
    if not isinstance(seen, dict) or seen.get("card_hash") != card_hash(st, mid):
        return Reject("stale_view", "所见的卡片已变，先看最新的")
    if mid in st["forgotten"]:
        return Reject("schema_error", "条目已遗忘")
    if kind == "mem_pin" and mem_state(st, mid) in ("stale", "retired"):
        return Reject("schema_error", "钉不住已过期的事实")
    return Ok({"item": mid, "reason": reason.strip(), "seen": {"seq": seen.get("seq"), "card_hash": seen["card_hash"]}})


# ---------- apply ----------


def apply(st: TState, ev: Mapping[str, Any]) -> TState:
    s = dict(st)
    s["seq"], s["now"] = ev["seq"], ev["ts"]
    body, kind = ev["body"], ev["kind"]
    if kind == "case_sealed":
        c = body["case"]
        pid = c["seal"]["problem_id"]
        s["cases"] = {**s["cases"], pid: c}
        recalls = dict(s["recalls"])
        for o in c.get("recall_outcomes", []):
            rec = {"seq": ev["seq"], "problem": pid, "verdict": o["verdict"], "on_chain": o["on_chain"]}
            recalls[o["mem"]] = [*recalls.get(o["mem"], []), rec]
        s["recalls"] = recalls
    elif kind == "mem_derived":
        pid = body["case"]
        recalled = {o["mem"] for o in s["cases"][pid].get("recall_outcomes", [])}
        items, recalls = dict(s["items"]), dict(s["recalls"])
        for m in body["items"]:
            prev = items.get(m["id"])
            hits = (prev or {}).get("cases", [])
            items[m["id"]] = {**(prev or m), "cases": [*hits, pid]}
            if m["kind"] == "env_fact" and m["id"] not in recalled:
                # 这道题自己的判官刚确认过它（在链的 E3）：等同一次通过的复核，过期的条目由此回到活跃
                rec = {"seq": ev["seq"], "problem": pid, "verdict": "pass", "on_chain": True, "derived": True}
                recalls[m["id"]] = [*recalls.get(m["id"], []), rec]
        s["items"], s["recalls"], s["derived"] = items, recalls, [*s["derived"], pid]
    elif kind == "mem_pin":
        s["pins"] = {**s["pins"], body["item"]: True}
    elif kind == "mem_forget":
        s["forgotten"] = {**s["forgotten"], body["item"]: {"seq": ev["seq"], "reason": body["reason"]}}
    else:
        raise ValueError(f"apply：未知事件 {kind}")
    return s
