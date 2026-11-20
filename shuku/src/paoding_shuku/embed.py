"""本机可插拔向量模型（设计稿“本机可插拔向量模型”一节）。

接口只有 id、dim、embed 三样。id 写进索引：换了模型，旧向量作废、后台重建。
默认实现 hash：字符 1 到 3 元特征哈希到 512 维，L2 归一化；不下载模型、不联网、确定。质量一般，检索主要靠词法，
向量负责把“换了个说法”的段落也捞上来。onnx 与 local_http 在第三期，配置了也先退回 hash 并说明。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol


class Embedder(Protocol):
    id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _grams(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", text.lower()).strip()
    out: list[str] = []
    for w in re.findall(r"[a-z0-9_]+|[^\sa-z0-9_]", t):
        if len(w) > 1:  # 拉丁词：整词 + 词内三元
            out.append("w:" + w)
            padded = f"^{w}$"
            out += ["t:" + padded[i : i + 3] for i in range(len(padded) - 2)]
        else:
            out.append("c:" + w)
    cjk = [c for c in t if "㐀" <= c <= "鿿"]
    out += ["b:" + cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]  # 中文二元
    return out


class HashEmbedder:
    id = "hash-512-v1"
    dim = 512

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for g in _grams(text):
                h = hashlib.blake2b(g.encode(), digest_size=8).digest()
                i = int.from_bytes(h[:4], "little") % self.dim
                v[i] += 1.0 if h[4] & 1 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


EMBEDDERS = ("hash", "onnx", "local_http")


def make_embedder(cfg: dict[str, Any] | None) -> tuple[Embedder, str]:
    """返回 (向量器, 说明)。说明不空时给人看：配了还不支持的实现，先用 hash。"""
    kind = str((cfg or {}).get("kind") or "hash")
    if kind not in EMBEDDERS:
        raise ValueError(f"knowledge.embedder.kind 取 {EMBEDDERS}，不是 {kind!r}")
    if kind == "hash":
        return HashEmbedder(), ""
    return HashEmbedder(), f"向量模型 {kind} 要到资料库第三期才接上，先用内置的 hash"


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))
