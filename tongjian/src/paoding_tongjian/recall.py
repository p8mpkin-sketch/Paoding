"""开题批次里带上召回清单（01-memory §4.2）：开题人一侧的纯函数，向导、评测台与 `pd` 共用。

    memory=off        开题批次原样
    memory=recall     每条召回事实的 spec 与对照输入登记为 input 类 Artifact（同批），open_problem 带 recall.items；
                      开题后 /work 先给出 recall 项，由召回运行器提交、本题判官复核
    recall_noverify   消融臂：不复核，事实只进 recall.notes，在任务包第③段作叙述

人逐条去掉的条目记进 excluded_by_human。清单随开题事件登记，之后不可改；重放不依赖通鉴的当前状态。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

MODES = ("off", "recall", "noverify")
SPEC_MEDIA = "text/plain; charset=utf-8"


def _reg(blob: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "op": "register_artifact",
        "body": {"hash": blob["hash"], "size": blob["size"], "media_type": SPEC_MEDIA, "class": "input"},
    }


def _notes(match: Mapping[str, Any], facts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    notes = [{"mem": m["id"], "kind": "env_fact", "title": m["title"]} for m in facts]
    notes += [{"mem": m["id"], "kind": "excluded", "title": m["title"]} for m in match["excluded"]]
    if match.get("spend"):
        s = match["spend"]
        notes.append({"mem": match["sig_key"], "kind": "spend_profile", "title": "同类题的花费中位数", "body": s})
    return notes


def with_recall(
    ops: list[dict[str, Any]], match: Mapping[str, Any], mode: str = "recall", drop: Iterable[str] = ()
) -> list[dict[str, Any]]:
    """ops：开题批次，最后一条是 open_problem。返回带召回清单的新批次（不改入参）。"""
    if mode not in MODES:
        raise ValueError(f"memory 取 {MODES} 之一，不是 {mode!r}")
    if mode == "off":
        return [dict(o) for o in ops]
    *head, opener = ops
    assert opener["op"] == "open_problem", "开题批次的最后一条须为 open_problem"
    dropped = set(drop)
    facts = [m for m in match["facts"] if m["id"] not in dropped]
    regs: list[dict[str, Any]] = []
    items = []
    if mode == "recall":
        for m in facts:
            c = m["check"]
            spec = len(head) + len(regs)
            regs.append(_reg(c["spec"]))
            check: dict[str, Any] = {"judge_id": c["judge_id"], "spec_ref": f"${spec}"}
            if "expect" in c:
                check["expect"] = c["expect"]
            if c.get("control"):
                refs = []
                for blob in c["control"]:
                    refs.append(f"${len(head) + len(regs)}")
                    regs.append(_reg(blob))
                check["control"] = {"inputs": refs}
            items.append({"mem": m["id"], "title": m["title"], "check": check})
    notes = _notes(match, [] if mode == "recall" else facts)
    recall: dict[str, Any] = {
        "items": items,
        "excluded_by_human": sorted(dropped & {m["id"] for m in match["facts"]}),
        "match_digest": match["digest"],
        **({"mode": "noverify"} if mode == "noverify" else {}),
        **({"notes": notes} if notes else {}),
    }
    body = {**opener["body"], "recall": recall}
    return [*[dict(o) for o in head], *regs, {"op": "open_problem", "body": body}]
