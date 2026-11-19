"""确认卡的文本版（pd kaiti 用；网页版见设计 §7.3）。只排版 Vetted，不推导任何量。

出处记号：摘（逐字取自原文）、表（确定性的表）、估（预算先验，估值语域）、起草（模型）。
"""

from __future__ import annotations

from typing import Any

from .vet import Vetted

MARK = {"span": "摘", "table": "表", "prior": "≈估", "model": "起草", "human": "人"}
LANE = {"practice": "练习道 · 零确认", "confirm": "确认道 · 一步确认", "refuse": "没有开题"}


def _val(v: Any) -> str:
    if isinstance(v, dict):
        return " · ".join(f"{k}={x}" for k, x in v.items())
    return str(v)


def render_card(v: Vetted) -> str:
    out = [f"[叙述] {LANE[v.lane]}" + ("（练习道候选）" if v.eligible and v.lane != "practice" else "")]
    if v.input is not None:
        out.append(f"[叙述] 题名（起草）：{v.input['title']}")
    out.append("")
    out.append("出处账")
    for d in v.derivation:
        spans = f" {','.join(d['spans'])}" if d.get("spans") else ""
        note = f"  ——{d['note']}" if d.get("note") else ""
        out.append(f"  {d['field']:<22} {_val(d['value'])}  [{MARK[d['source']]}{spans}]{note}")
    if v.secret is not None:
        out.append("  答案                   已收起，只给判定器（保密库）")
    if v.notes:
        out.append("")
        out.append("为什么要你看" if v.lane != "refuse" else "为什么不开")
        for i, n in enumerate(v.notes, 1):
            out.append(f"  {i:02d} {n.text}")
    out.append(f"\n[估] 预算默认值来自 {v.priors_version}")
    return "\n".join(out) + "\n"


def render_view(doc: dict[str, Any]) -> str:
    """服务端视图（draft_view、import_view 的 JSON）的文本版：pd connector import 经 HTTP 拿到的就是它。"""
    out = [f"[叙述] {LANE[doc['lane']]}"]
    if doc.get("input"):
        out.append(f"[叙述] 题名：{doc['input']['title']}")
    out.append("")
    out.append("出处账")
    for d in doc.get("derivation", []):
        note = f"  ——{d['note']}" if d.get("note") else ""
        out.append(f"  {d['field']:<22} {_val(d['value'])}  [{MARK[d['source']]}]{note}")
    if doc.get("notes"):
        out.append("")
        out.append("为什么要你看" if doc["lane"] != "refuse" else "为什么不开")
        for i, n in enumerate(doc["notes"], 1):
            out.append(f"  {i:02d} {n['text']}")
    out.append(f"\n[估] 预算默认值来自 {doc.get('priors', '')}")
    return "\n".join(out) + "\n"
