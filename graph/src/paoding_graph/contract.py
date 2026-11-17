"""graph 的对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""
from .envelope import ACTOR_KINDS, GENESIS, ROLES, ChainError, event_hash, verify_chain  # noqa: F401
from .jcs import canonicalize  # noqa: F401
from .resources import RESOURCE_EXTERNAL, external_resources  # noqa: F401

# 拒绝码（§3.1.2）。stale_view 为 M1、bad_seal 为 M3，先占位，内核尚不产生。
REJECT_CODES = frozenset({
    "forbidden_op", "unknown_ref", "inadmissible_class", "scope_mismatch", "missing_evidence",
    "stale_premise", "conflict_leased", "over_budget", "quota_exceeded", "schema_error",
    "stale_view", "bad_seal",
})
ARTIFACT_CLASSES = frozenset({"exec", "judge", "input", "authored"})
ADMISSIBLE_CLASSES = frozenset({"exec", "judge", "input"})   # authored 永不入 grounds（I2）

# ---------- 进程内端口（M0 单机；HTTP/Unix socket 绑定在其上，接口相同） ----------
from typing import Protocol  # noqa: E402

from .blobs import BlobStore, CorruptBlob  # noqa: E402,F401


class GraphPort(Protocol):
    """POST /v1/problems/{pid}/proposals 的进程内形态：令牌决定身份，整批原子，同 idem_key 恰好一次。"""

    def submit(self, token: str, pid: str, idem_key: str, ops: list[dict]) -> dict: ...


class BlobPort(Protocol):
    """PUT /v1/blobs 与 GET /v1/blobs/{hash}。"""

    def put(self, data: bytes) -> str: ...

    def get(self, h: str, start: int = 0, end: int | None = None) -> bytes: ...
