"""切分（五阶段的第三步）：文本 → 段落。确定：同一段文本、同一切分器版本，得到同一组段落与 id。

按标题与空行分块，相邻块并到 TARGET 字左右，不超过 MAX；超长的块按句号、换行再切。每段记下所在的标题路径与
在文档里的起止字符位置，id 由文档哈希与起止位置决定，所以重建索引不会让旧引用失效。代码按空行切，不跨文件。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

CHUNKER = "c1"  # 切分器版本：规则一变就换，旧版本的段落 id 不混用
TARGET, MAX = 500, 800


@dataclass(frozen=True)
class Chunk:
    id: str
    heading: str  # 标题路径，例如“部署 / 回滚”
    start: int
    end: int
    text: str


def _blocks(text: str) -> list[tuple[int, int]]:
    """按空行分出块的 (起, 止)。"""
    out, pos = [], 0
    for m in re.finditer(r"\n\s*\n", text):
        if m.start() > pos:
            out.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text)))
    return out


def _split_long(text: str, a: int, b: int) -> list[tuple[int, int]]:
    """块比 MAX 长时按句末与换行切。"""
    if b - a <= MAX:
        return [(a, b)]
    out, s = [], a
    while b - s > MAX:
        window = text[s : s + MAX]
        cut = max(window.rfind(c) for c in ("。", "！", "？", ". ", "\n", "；", "; "))
        e = s + (cut + 1 if cut > TARGET // 2 else MAX)
        out.append((s, e))
        s = e
    out.append((s, b))
    return out


def chunk(doc_key: str, text: str, path: str = "") -> list[Chunk]:
    heads: list[str] = []
    pieces: list[tuple[int, int, str]] = []
    for a, b in _blocks(text):
        first = text[a:b].lstrip()
        m = re.match(r"(#{1,6})\s+(.+)", first)
        if m and "\n" not in first.strip():
            level = len(m.group(1))
            heads = [*heads[: level - 1], m.group(2).strip()]
        for x, y in _split_long(text, a, b):
            pieces.append((x, y, " / ".join(heads)))
    out: list[Chunk] = []
    cur: list[tuple[int, int, str]] = []

    def flush() -> None:
        if not cur:
            return
        a, b, h = cur[0][0], cur[-1][1], cur[0][2]
        key = f"{CHUNKER}:{doc_key}:{a}:{b}"
        cid = "k_" + hashlib.sha256(key.encode()).hexdigest()[:16]
        head = " / ".join(x for x in (path, h) if x)
        out.append(Chunk(cid, head, a, b, text[a:b].strip()))
        cur.clear()

    for a, b, h in pieces:
        if cur and (h != cur[0][2] or b - cur[0][0] > MAX or cur[-1][1] - cur[0][0] >= TARGET):
            flush()
        cur.append((a, b, h))
    flush()
    return [c for c in out if c.text]
