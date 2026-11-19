"""把 Vetted 变成一次开题批次（与向导、导入同一条提议通道：人的令牌提交 open_problem）。

批次 = 题面登记 · 参考材料登记 · 检查命令登记 · 出处账登记 · open_problem。整批原子。
答案不在批次里：调用方先把它写进保密库，拿回 VaultRef，这里替换 ANSWER_SLOT。
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from typing import Any

from .vet import ANSWER_SLOT, Vetted, derivation_bytes

Blob = tuple[str, bytes]  # (media_type, 内容)


def blobs(v: Vetted) -> dict[str, Blob]:
    out: dict[str, Blob] = {"statement": ("text/plain; charset=utf-8", v.statement.encode())}
    if v.references:
        out["references"] = ("text/uri-list", ("\n".join(v.references) + "\n").encode())
    if v.spec is not None:
        out["spec"] = ("text/x-shellscript", (v.spec + "\n").encode())
    if v.notice is not None:  # 资源公告：领题说明全文（external-verdict §5.5）
        out["notice"] = ("application/json", v.notice)
    out["derivation"] = ("application/vnd.paoding.kaiti-derivation+json", derivation_bytes(v))
    return out


def batch(v: Vetted, put: Callable[[bytes], str], vault_ref: dict[str, Any] | str | None) -> list[dict[str, Any]]:
    """put(字节) → sha256；vault_ref 是保密库返回的 {vault, digest}（有答案时必填）。
    网页的起草服务传 ANSWER_SLOT 本身：批次原样带着占位符交给前端，前端写完保密库再换（service.py）。"""
    if v.input is None or v.lane == "refuse":
        raise ValueError("拒绝道不开题")
    if v.needs_ack:
        raise ValueError("命令有外发的形状：人确认只检查、不提交之前不开题")
    if v.external is not None and v.notice is None:
        raise ValueError("外部判定的题由导入时领题生成批次（connector import），起草结果本身不开题")
    ops: list[dict[str, Any]] = []
    idx: dict[str, str] = {}
    for name, (media, data) in blobs(v).items():
        h = put(data)
        if h != hashlib.sha256(data).hexdigest():
            raise ValueError(f"Blob 哈希不符：{name}")
        idx[f"${name}"] = f"${len(ops)}"
        ops.append(
            {"op": "register_artifact", "body": {"hash": h, "size": len(data), "media_type": media, "class": "input"}}
        )
    body = _subst(copy.deepcopy(v.input), idx)
    # 出处账引用与道别（内核增量 13）：lane=practice 时内核逐条对练习道信封，不满足整单拒绝
    body["origin"]["draft"] = {"record": idx["$derivation"], "lane": v.lane}
    sealed = body["goal"]["check"].get("sealed")
    if sealed is not None:
        if vault_ref is None:
            raise ValueError("有答案键时须先写保密库")
        body["goal"]["check"]["sealed"] = [vault_ref if x == ANSWER_SLOT else x for x in sealed]
    ops.append({"op": "open_problem", "body": body})
    return ops


def _subst(x: Any, idx: dict[str, str]) -> Any:
    if isinstance(x, str):
        return idx.get(x, x)
    if isinstance(x, list):
        return [_subst(y, idx) for y in x]
    if isinstance(x, dict):
        return {k: _subst(y, idx) for k, y in x.items()}
    return x
