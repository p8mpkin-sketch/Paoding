"""文本量具：分词、专名拆分、抄写比对、注入与指令痕迹的模式匹配（08 §4.3 K2–K4、K8，§4.4 D6）。

全部是纯函数。统一先做 NFKC 与大小写折叠。分词：英文与数字按非字母数字切开，再按驼峰、下划线拆；
中文逐字成词元（没有词典，K2 的中文专名改做子串比对，K4 的“词元”对中文就是字）。
"""

from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Iterable, Iterator
from typing import Any

from .data import table

_WORD = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?|[㐀-鿿]", re.IGNORECASE)
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def tokens(s: str) -> list[str]:
    """词元序列（K4 用）：英文词、数字、单个汉字。"""
    return _WORD.findall(fold(s))


def split_ident(ident: str) -> list[str]:
    """`fooBarBaz` / `foo_bar` → 小写片段。"""
    parts: list[str] = []
    for chunk in re.split(r"[_\-.]+", unicodedata.normalize("NFKC", ident)):
        parts += [p.lower() for p in _CAMEL.findall(chunk)]
    return [p for p in parts if p]


# 受控词表的栏（枚举、编号、引用）：值是我们自己的词，不算自由文本，K2/K3/K8 不查它们
CONTROLLED = frozenset(
    {"features", "kind", "here", "resolution", "holds_here", "relation", "measure", "dir", "outcome_cap", "kernel"}
    | {"with", "fire", "dims", "primitives", "id", "dim_ids"}
)


def strings(obj: Any, skip: frozenset[str] = frozenset()) -> Iterator[str]:
    """一个 JSON 值里的全部字符串（键不算）；`skip` 里的键整栏跳过。"""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in skip:
                yield from strings(v, skip)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v, skip)


def free_text(obj: Any) -> list[str]:
    """自由文本栏（受控词表的栏除外）。"""
    return list(strings(obj, CONTROLLED))


def name_table(identifiers: Iterable[str], extra: Iterable[str] = ()) -> list[str]:
    """外部专名表（08 §3.2 末行）：标识符整体（折叠后）+ 拆开的片段（长度 ≥ 4、不在通用词表与我们词表里）。"""
    common = set(table("common-words")["words"])
    ours = {fold(w) for w in table("vocab")["identifiers"]}
    out: set[str] = set()
    stdlib = set(sys.stdlib_module_names)
    for ident in [*identifiers, *extra]:
        f = fold(ident).strip()
        if len(f) < 4 or f in common or f in ours or ident.startswith("_") or ident in stdlib:
            continue
        out.add(f)
        for part in split_ident(ident):
            if len(part) >= 4 and part not in common:
                out.add(part)
    return sorted(out)


def name_hits(text: str, names: Iterable[str]) -> list[str]:
    """遮蔽视图里出现的外部专名（K2）：英文按词元整词比对，含非 ASCII 的专名做子串比对。"""
    f = fold(text)
    words = set(tokens(text))
    for ident in _IDENT.findall(unicodedata.normalize("NFKC", text)):
        words.add(ident.lower())
        words.update(split_ident(ident))
    hits = []
    for n in names:
        if n.isascii():
            if n in words or (not re.fullmatch(r"[a-z0-9]+", n) and n in f):
                hits.append(n)
        elif n in f:
            hits.append(n)
    return sorted(set(hits))


_PATHLIKE = re.compile(r"(?<![\w])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,5}\b")
_FILELINE = re.compile(r"\b[\w./-]+\.[A-Za-z]{1,5}:\d+\b")
_CALL = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(")
_LINENO = re.compile(r"(?:\bline\s*\d+\b|第\s*\d+\s*行|\bL\d+\b)", re.IGNORECASE)
_CAMEL_IDENT = re.compile(r"\b(?:[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*)\b")
_SNAKE_IDENT = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")


def code_structure_hits(text: str) -> list[str]:
    """K3：路径形、文件:行号、函数调用形、代码围栏、我们词表之外的驼峰或下划线标识符、行号。"""
    ours = set(table("vocab")["identifiers"])
    t = unicodedata.normalize("NFKC", text)
    hits = []
    if "```" in t:
        hits.append("代码围栏")
    hits += [f"路径形 {m}" for m in _PATHLIKE.findall(t) if m not in ours]
    hits += [f"文件:行号 {m}" for m in _FILELINE.findall(t)]
    hits += [f"调用形 {m}" for m in _CALL.findall(t)]
    hits += [f"行号 {m}" for m in _LINENO.findall(t)]
    hits += [f"标识符 {m}" for m in _CAMEL_IDENT.findall(t) if m not in ours]
    hits += [f"标识符 {m}" for m in _SNAKE_IDENT.findall(t) if m not in ours]
    return hits


def longest_common_run(a: list[str], b: list[str]) -> int:
    """两段词元序列的最长公共连续片段长度（K4、V6）。动态规划，按短的一侧开行。"""
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    best = 0
    prev = [0] * (len(a) + 1)
    for y in b:
        cur = [0] * (len(a) + 1)
        for i, x in enumerate(a, 1):
            if x == y:
                cur[i] = prev[i - 1] + 1
                if cur[i] > best:
                    best = cur[i]
        prev = cur
    return best


def ngram_overlap(a: list[str], corpus: set[tuple[str, ...]], n: int = 8) -> float:
    """`a` 的 n 元组里出现在语料 n 元组集合中的比例。"""
    grams = [tuple(a[i : i + n]) for i in range(len(a) - n + 1)]
    if not grams:
        return 0.0
    return sum(g in corpus for g in grams) / len(grams)


def ngrams(seq: list[str], n: int = 8) -> set[tuple[str, ...]]:
    return {tuple(seq[i : i + n]) for i in range(len(seq) - n + 1)}


def instruction_hits(text: str) -> list[str]:
    """K8：对系统或智能体的命令式，以及把我们的文件名、命令名作宾语。"""
    inj = table("injection")
    f = fold(text)
    hits = [p for p in inj["imperative"] if fold(p) in f]
    hits += [f"宾语 {o}" for o in inj["our_objects"] if fold(o) in f]
    return hits


def injection_hits(text: str) -> list[str]:
    """D6：提示词形的句子、工具调用形 JSON、隐藏 Unicode、超长 base64、Markdown 里的 HTML 注释。"""
    inj = table("injection")
    f = fold(text)
    hits = [f"提示词形 {p}" for p in inj["prompt_like"] if fold(p) in f]
    hits += [f"工具调用形 {p}" for p in inj["tool_call_json"] if p in text]
    hidden = sorted({f"U+{ord(c):04X}" for c in text if c in inj["hidden_unicode"]})
    if hidden:
        hits.append("隐藏字符 " + " ".join(hidden))
    if re.search(r"[A-Za-z0-9+/]{%d,}={0,2}" % int(inj["base64_min_len"]), text):
        hits.append("超长 base64")
    if "<!--" in text:
        hits.append("HTML 注释")
    return hits


def without_hidden(text: str) -> str:
    """去掉隐藏 Unicode 后的文本（隐藏字符包着的句子照样能被 K8 认出来）。"""
    hidden = set(table("injection")["hidden_unicode"])
    return "".join(c for c in text if c not in hidden)
