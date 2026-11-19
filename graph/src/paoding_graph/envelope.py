"""事件信封与按题哈希链（规格 §3.1.2）。

hash = sha256(JCS(除 hash 外的全部字段))；prev_hash 指同题上一条事件的 hash。
每题的第一条事件 prev_hash 取 GENESIS（64 个 0）。规格没有规定创世值，此处取定值并记入 SPEC.md。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any, cast

from .jcs import canonicalize
from .state import Event

SCHEMA_VERSION = 1
GENESIS = "0" * 64
ACTOR_KINDS = frozenset({"human", "sinan", "adapter", "judge", "executor", "watchdog", "graph"})
ROLES = frozenset({"bootstrap", "reason", "explore", "verify", "idler", "recall"})
FIELDS = ("v", "seq", "problem_id", "ts", "actor", "kind", "body", "idem_key", "prev_hash", "hash")


class EnvelopeError(ValueError):
    code = "schema_error"


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def event_hash(ev: Mapping[str, Any]) -> str:
    return sha256_hex(canonicalize({k: v for k, v in ev.items() if k != "hash"}))


def check_actor(actor: Any) -> None:
    if not isinstance(actor, dict) or actor.get("kind") not in ACTOR_KINDS or not isinstance(actor.get("id"), str):
        raise EnvelopeError(f"actor 非法：{actor!r}")
    extra = set(actor) - {"kind", "id", "session", "role"}
    if extra:
        raise EnvelopeError(f"actor 有多余字段：{sorted(extra)}")
    if "role" in actor and actor["role"] not in ROLES:
        raise EnvelopeError(f"role 非法：{actor['role']!r}")


def seal(
    *, seq: int, problem_id: str, ts: int, actor: Any, kind: str, body: dict[str, Any], idem_key: str, prev_hash: str
) -> Event:
    """组装一条事件并算出 hash。只由图服务调用；ts 由图服务在追加时写入。"""
    check_actor(actor)
    if not isinstance(body, dict) or not kind or not idem_key:
        raise EnvelopeError("kind、idem_key 必填，body 必须是对象")
    ev = {
        "v": SCHEMA_VERSION,
        "seq": seq,
        "problem_id": problem_id,
        "ts": ts,
        "actor": actor,
        "kind": kind,
        "body": body,
        "idem_key": idem_key,
        "prev_hash": prev_hash,
    }
    ev["hash"] = event_hash(ev)
    return cast(Event, ev)


def verify_chain(events: Iterable[Mapping[str, Any]]) -> None:
    """校验一题的事件序列：hash 自洽、prev_hash 首尾相接、seq 严格递增。失败抛 ChainError。"""
    prev, last_seq = GENESIS, -1
    for ev in events:
        if set(ev) != set(FIELDS):
            raise ChainError(ev.get("seq"), "字段集不符")
        if ev["hash"] != event_hash(ev):
            raise ChainError(ev["seq"], "hash 与内容不符")
        if ev["prev_hash"] != prev:
            raise ChainError(ev["seq"], "prev_hash 断链")
        if ev["seq"] <= last_seq:
            raise ChainError(ev["seq"], "seq 不递增")
        prev, last_seq = ev["hash"], ev["seq"]


class ChainError(ValueError):
    def __init__(self, seq: Any, why: str):
        super().__init__(f"seq={seq}: {why}")
        self.seq, self.why = seq, why
