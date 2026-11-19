"""开题前的确定性匹配（01-memory §4.1）：环境键精确、签名包含、BM25。字符串运算与排序，不调用模型，不进内核。"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

from .keys import digest
from .reducer import history, mem_state, recallable

R_FACTS = 8
R_EXCLUDED = 5
R_CASES = 5
MIN_SPEND = 3  # 同签名同代际不足 3 题不给花费画像


def _rank(st: Mapping[str, Any], mid: str) -> tuple[int, int, str]:
    h = history(st, mid)
    on_chain = sum(1 for x in h if x["on_chain"])
    last_pass = max((x["seq"] for x in h if x["verdict"] == "pass"), default=0)
    return (-on_chain, -last_pass, mid)


def tokens(text: str) -> list[str]:
    """词法单元：ASCII 词，加汉字的单字与相邻二字。确定性，不依赖分词词典。"""
    words = re.findall(r"[a-z0-9_]+", text.lower())
    han = re.findall(r"[一-鿿]", text)
    return words + han + [a + b for a, b in zip(han, han[1:], strict=False)]


def bm25(query: str, docs: Sequence[tuple[str, str]], k1: float = 1.2, b: float = 0.75) -> list[tuple[float, str]]:
    """docs：(id, 文本)。返回 (得分, id)，按得分降序、id 升序。"""
    q = tokens(query)
    toks = {d: tokens(t) for d, t in docs}
    n = len(docs) or 1
    avg = sum(len(t) for t in toks.values()) / n or 1.0
    df = {w: sum(1 for t in toks.values() if w in t) for w in set(q)}
    out = []
    for d, t in toks.items():
        s = 0.0
        for w in q:
            tf = t.count(w)
            if tf:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(t) / avg))
        out.append((round(s, 9), d))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def _contains(case_sig: Mapping[str, Any], sig: Mapping[str, Any]) -> bool:
    """签名包含（规格 4.3 第 5 步）：判例的判官、资源种类、tags 都在新题的集合之内。"""
    return all(set(case_sig[k]) <= set(sig[k]) for k in ("judges", "resources", "tags"))


def match(
    st: Mapping[str, Any], env_key: str, sig: Mapping[str, Any], sig_key: str, query: str, model_epoch: str
) -> dict[str, Any]:
    items = st["items"]
    facts = sorted(
        (m for m, x in items.items() if x["kind"] == "env_fact" and x["scope"].get("env_key") == env_key),
        key=lambda m: _rank(st, m),
    )
    facts = [m for m in facts if recallable(st, m)][:R_FACTS]
    excluded = sorted(
        (
            m
            for m, x in items.items()
            if x["kind"] == "excluded" and x["scope"].get("env_key") == env_key and mem_state(st, m) != "retired"
        ),
        key=lambda m: _rank(st, m),
    )[:R_EXCLUDED]
    profiles = [
        x["body"]["usd_milli"]
        for x in items.values()
        if x["kind"] == "spend_profile" and x["scope"].get("sig_key") == sig_key and x.get("model_epoch") == model_epoch
    ]
    spend = (
        {"n": len(profiles), "median_usd_milli": int(median(profiles)), "model_epoch": model_epoch}
        if len(profiles) >= MIN_SPEND
        else None
    )
    pool = [(c["id"], c["title"]) for c in st["cases"].values() if _contains(c["sig"], sig)]
    cases = [d for _, d in bm25(query, pool)][:R_CASES]
    out = {
        "env_key": env_key,
        "sig_key": sig_key,
        "facts": [{**items[m], "state": mem_state(st, m)} for m in facts],
        "excluded": [{**items[m], "state": mem_state(st, m)} for m in excluded],
        "spend": spend,
        "cases": cases,
        "as_of": st["seq"],
    }
    out["digest"] = digest(
        {k: out[k] for k in ("env_key", "sig_key", "spend", "cases", "as_of")}
        | {
            "facts": facts,
            "excluded": excluded,
        }
    )
    return out
