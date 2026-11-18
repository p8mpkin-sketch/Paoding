"""重放测试台：把日志按 seq 喂给纯函数 apply，得到状态与状态哈希（3.1.5 的 1）。

apply 不读时钟、不做 IO、不调用模型；唯一的时钟是事件里的 ts。
状态哈希 = sha256(JCS(state))，所以状态必须是 JSON 值。
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Iterable

from .envelope import sha256_hex, verify_chain
from .jcs import canonicalize

Apply = Callable[[Any, Any], Any]


def state_hash(state: Any) -> str:
    return sha256_hex(canonicalize(state))


def replay(events: Iterable[Any], apply: Apply, init: Any, *, check_chain: bool = True) -> Any:
    evs = list(events)
    if check_chain:
        by_problem: dict[str, list[Any]] = {}
        for ev in evs:
            by_problem.setdefault(ev["problem_id"], []).append(ev)
        for chain in by_problem.values():
            verify_chain(chain)
    state = copy.deepcopy(init)
    for ev in sorted(evs, key=lambda e: e["seq"]):
        state = apply(state, ev)
    return state
