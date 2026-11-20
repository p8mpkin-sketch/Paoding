"""knowledge 类与任务的知识偏好（资料库第二期；K1、K3，cz 2026-11-20）。

- knowledge 类：会话查到的一段人给的资料。只由书库的组件令牌（graph:shuku）登记，模型不能伪造“资料原文”。
  参考模型的登记表里没有这一类，它也不入任何 grounds：判定道的事实、验收清单、开放道的自检都不认，
  只有开放道交付的主张可以引用（deliver.CLAIM_ADMISSIBLE）。
- prefs.knowledge：{mode: auto | pick | off, pick?: [资料 id]}，开题后不变。资料是否存在由书库认，内核不查。
"""

from __future__ import annotations

from ..parse import Obj
from ..state import Actor, Body, State
from .common import Reject

REGISTRAR = {"kind": "graph", "id": "shuku"}  # 书库的组件令牌
FIELDS = {"source", "revision", "chunk", "locator"}
LOCATOR_MAX = 300
MODES = ("auto", "pick", "off")
PICK_MAX = 32


def artifact(actor: Actor, pid: str, body: Obj, state: State) -> Body | Reject:
    """register_artifact 的 knowledge 类：查登记人与出处，返回规整后的出处。"""
    if actor["kind"] != REGISTRAR["kind"] or actor["id"] != REGISTRAR["id"]:
        return Reject("forbidden_op", "knowledge 类只由书库的组件令牌登记")
    if pid not in state["problems"]:
        return Reject("unknown_ref", f"题目 {pid} 未开")
    if "knowledge" not in body or not body.child("knowledge").keys() <= FIELDS:
        return Reject("schema_error", f"knowledge 类必须带出处 {{{', '.join(sorted(FIELDS))}}}")
    k = body.child("knowledge")
    rev = k.req("revision")
    if not k.text("source").strip() or not k.text("chunk").strip() or type(rev) is not int or rev < 1:
        return Reject("schema_error", "knowledge 的 source、chunk 非空，revision 为正整数")
    return {
        "source": k.text("source"),
        "revision": rev,
        "chunk": k.text("chunk"),
        "locator": k.text("locator")[:LOCATOR_MAX] if "locator" in k else "",
    }


def prefs(k: Obj) -> Body | Reject:
    mode = k.get("mode")
    if not k.keys() <= {"mode", "pick"} or mode not in MODES:
        return Reject("schema_error", f"prefs.knowledge 是 {{mode, pick?}}，mode 取 {MODES}")
    pick = [x.strip() for x in k.texts("pick", [])]
    if mode == "pick" and not pick:
        return Reject("schema_error", "mode 为 pick 时要列出资料 id")
    if mode != "pick" and pick:
        return Reject("schema_error", "只有 mode 为 pick 时才列资料")
    if len(pick) > PICK_MAX or len(set(pick)) != len(pick) or any(not x for x in pick):
        return Reject("schema_error", f"pick 至多 {PICK_MAX} 份、不重复、非空")
    return {"mode": mode, **({"pick": pick} if pick else {})}
