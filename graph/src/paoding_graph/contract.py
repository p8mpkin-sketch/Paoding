"""graph 的对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""

from .envelope import ACTOR_KINDS, GENESIS, ROLES, ChainError, event_hash, verify_chain  # noqa: F401
from .jcs import JCSError, canonicalize  # noqa: F401
from .parse import BadBody, Obj  # noqa: F401
from .resources import RESOURCE_EXTERNAL, external_resources  # noqa: F401

# 拒绝码（§3.1.2）。stale_view 由人的决策操作的 seen 校验产生（§3.1.9）；bad_seal 为 M3，先占位。
REJECT_CODES = frozenset(
    {
        "forbidden_op",
        "unknown_ref",
        "inadmissible_class",
        "scope_mismatch",
        "missing_evidence",
        "stale_premise",
        "conflict_leased",
        "over_budget",
        "quota_exceeded",
        "schema_error",
        "stale_view",
        "bad_seal",
    }
)
ARTIFACT_CLASSES = frozenset({"exec", "judge", "input", "authored"})
ADMISSIBLE_CLASSES = frozenset({"exec", "judge", "input"})  # authored 永不入 grounds（I2）

# ---------- 进程内端口（M0 单机；HTTP/Unix socket 绑定在其上，接口相同） ----------
from typing import BinaryIO, Protocol  # noqa: E402

from . import views  # noqa: E402,F401
from .blobs import BlobStore, CorruptBlob  # noqa: E402,F401

# HTTP 绑定（HMI §11 方案 A）与只读投影。四语域表与等级词表是 pd 与网页的同一事实源。
from .httpapi import GraphHttp, HttpConfig  # noqa: E402,F401

# 组装根（pd、测试台）构造服务用。组件之间仍只经下面的端口协议交互。
from .reducer import Config  # noqa: E402,F401
from .service import GraphService  # noqa: E402,F401

# 状态与事件的类型（TypedDict；运行时仍是普通 dict）
from .state import (  # noqa: E402,F401
    Actor,
    Amount,
    Artifact,
    Body,
    Check,
    Cost,
    Event,
    Fact,
    Hint,
    Intent,
    Lease,
    Problem,
    Request,
    State,
    Support,
    Verdict,
)
from .tokens import TokenRegistry, UnknownToken  # noqa: E402,F401
from .views import LEVEL_WORDS, REGISTER, REGISTERS  # noqa: E402,F401
from .work import BudgetView  # noqa: E402,F401


class GraphPort(Protocol):
    """POST /v1/problems/{pid}/proposals 的进程内形态：令牌决定身份，整批原子，同 idem_key 恰好一次。"""

    def submit(self, token: str, pid: str, idem_key: str, ops: list[Body]) -> Body: ...


class BlobPort(Protocol):
    """PUT /v1/blobs 与 GET /v1/blobs/{hash}。"""

    def put(self, data: bytes | BinaryIO) -> str: ...  # 流：逐块读到 EOF（执行层的大输出）

    def get(self, h: str, start: int = 0, end: int | None = None) -> bytes: ...


class TokenIssuer(Protocol):
    """会话令牌的签发与作废（§3.2.4 第 2 层）。Adapter 为每个租约签一枚 actor 带 session 与 role 的令牌。"""

    def issue(self, actor: Actor, token: str | None = None) -> str: ...

    def revoke(self, token: str) -> None: ...


class GraphReader(Protocol):
    """GET 只读端点的进程内形态：show 与任务包渲染读这里。state 是 reducer 状态的只读快照。"""

    state: State

    def work(self, pid: str) -> list[Body]: ...

    def budget(self, pid: str) -> BudgetView: ...


def node_levels(state: State, pid: str) -> dict[str, str]:
    """等级每次读时重算（I3），经参考模型的等级函数；只读端点与任务包渲染用。"""
    from .levels import levels

    return levels(state, pid)


def intent_status(state: State, pid: str, iid: str) -> str:
    """Intent 的派生状态（open/leased/done/abandoned/needs_human/…），只读端点与任务包渲染用。"""
    from .work import intent_status as _st

    return _st(state, pid, iid)


def seen_card(state: State, pid: str, kind: str, target: str) -> Body:
    """人的决策操作要带的 seen {seq, card_hash}：取自调用方展示给人的那份状态快照（§3.1.9）。"""
    from .cards import seen

    return seen(state, pid, kind, target)


def as_of_seq(state: State) -> int:
    """状态快照对应的最后一个事件序号：任务包的 as_of_seq。"""
    return state["seq"]
