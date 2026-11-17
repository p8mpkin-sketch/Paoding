"""graph 的对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""
from .envelope import ACTOR_KINDS, GENESIS, ROLES, ChainError, event_hash, verify_chain  # noqa: F401
from .jcs import canonicalize  # noqa: F401

# 拒绝码（§3.1.2）。stale_view 为 M1、bad_seal 为 M3，先占位，内核尚不产生。
REJECT_CODES = frozenset({
    "forbidden_op", "unknown_ref", "inadmissible_class", "scope_mismatch", "missing_evidence",
    "stale_premise", "conflict_leased", "over_budget", "quota_exceeded", "schema_error",
    "stale_view", "bad_seal",
})
ARTIFACT_CLASSES = frozenset({"exec", "judge", "input", "authored"})
ADMISSIBLE_CLASSES = frozenset({"exec", "judge", "input"})   # authored 永不入 grounds（I2）
