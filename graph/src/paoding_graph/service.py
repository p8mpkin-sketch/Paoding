"""图服务：唯一写入者（§3.1.2）。把令牌、时钟、日志与纯函数内核接在一起。

- 身份只来自令牌（tokens.py），不来自请求体。
- 一批提议整批原子：逐条在演进中的状态上 validate，任何一条被拒则整批不落盘，返回各条结果。
- 批内后一条可以用 "$<下标>" 引用前一条产生的 id。
- 每批应用后，按 work.followups 与 reducer.grants.followups 追加图服务自己的事件（budget_mark、自动关题、
  随 needs_scope 的扩权申请与按判定的批准），与这批同一事务。
- 同一 (problem_id, idem_key) 重放返回首次结果；进程被 kill -9 后重启，状态由日志重放得出（3.1.5 的 2）。
- 时钟只在这里读（clock 可注入），作为参数交给 validate 与事件信封；reducer 不读时钟。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import views
from . import work as wk
from .eventlog import Append, BatchRejected, EventLog
from .reducer import Config, Ok, apply, empty_state, grants, result_id, validate
from .replay import replay
from .state import Actor, Body, Event, State
from .tokens import TokenRegistry, UnknownToken

GRAPH_ACTOR: Actor = {"kind": "graph", "id": "graph"}
FOLLOWUP_ROUNDS = 4


class GraphService:
    def __init__(
        self,
        path: str | Path,
        cfg: Config,
        tokens: TokenRegistry,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ):
        self.log, self.cfg, self.tokens, self._clock = EventLog(path), cfg, tokens, clock
        self.state: State = replay(self.log.events(), apply, empty_state())  # 崩溃恢复即重放
        self._lock = threading.RLock()  # 单写者：提交串行；日志连接只在锁内使用
        self._cond = threading.Condition(self._lock)  # 新事件落盘后唤醒长轮询与事件流
        self._snaps: OrderedDict[int, State] = OrderedDict()  # as_of 回放的状态缓存（日志只追加，永不失效）

    def _ts(self) -> int:
        return max(self._clock(), self.state["now"] + 1)

    def submit(self, token: str, pid: str, idem_key: str, ops: list[Body]) -> Body:
        with self._cond:
            out = self._submit(token, pid, idem_key, ops)
            self._cond.notify_all()
            return out

    def _submit(self, token: str, pid: str, idem_key: str, ops: list[Body]) -> Body:
        try:
            actor = self.tokens.resolve(token)
        except UnknownToken:
            return {"ok": False, "results": [{"ok": False, "code": "forbidden_op", "detail": "未知令牌"}]}

        staged: dict[str, Any] = {}

        def build(append: Append) -> Body:
            state = self.state
            results: list[Body] = []
            evs: list[Event] = []
            ids: list[str | None] = []
            for i, op in enumerate(ops):
                kind, body = op["op"], _subst(op.get("body", {}), ids)
                ts = self._ts() if not evs else max(self._ts(), evs[-1]["ts"])
                r = validate(state, actor, pid, kind, body, self.cfg, ts)
                if not isinstance(r, Ok):
                    results.append(
                        {
                            "ok": False,
                            "code": r.code,
                            "detail": r.detail,
                            # stale_view：附上链头的最新卡片（§3.1.9），形状与 /cards 端点相同
                            **(
                                {"card": {"as_of": state["seq"], **views.card(state, pid, *r.card, self.cfg)}}
                                if r.card
                                else {}
                            ),
                        }
                    )
                    raise _Abort(
                        results
                        + [{"ok": False, "code": "batch_aborted", "detail": f"第 {i} 条被拒"} for _ in ops[i + 1 :]]
                    )
                ev = append(pid, kind, r.body, actor, ts, f"{idem_key}#{i}")
                state = apply(state, ev)
                evs.append(ev)
                ids.append(result_id(ev))
                results.append({"ok": True, "id": ids[-1], "seq": ev["seq"]})
            # 图服务自己追加的事件可能接连发生（needs_scope → 申请 → 自动批准），按轮重算，直到没有新事件
            for _ in range(FOLLOWUP_ROUNDS):
                applied = 0
                for fkind, fbody in grants.followups(state, pid) + wk.followups(state, pid):
                    ts = evs[-1]["ts"] if evs else self._ts()
                    r = validate(state, GRAPH_ACTOR, pid, fkind, fbody, self.cfg, ts)
                    if isinstance(r, Ok):
                        ev = append(pid, fkind, r.body, GRAPH_ACTOR, ts, f"{idem_key}#auto-{fkind}-{len(evs)}")
                        state = apply(state, ev)
                        evs.append(ev)
                        applied += 1
                if not applied:
                    break
            staged["state"] = state
            return {"ok": True, "results": results}

        out, fresh = self.log.commit_batch(pid, idem_key, build)
        if fresh and out.get("ok"):
            self.state = staged["state"]
        return out

    def system(self, pid: str, kind: str, body: Body, actor: Actor, idem_key: str) -> Body:
        """组件内部（哮天犬等）以固定身份提交，不经令牌。只供同进程的服务组件调用。"""
        tok = self.tokens.issue(actor)
        try:
            return self.submit(tok, pid, idem_key, [{"op": kind, "body": body}])
        finally:
            self.tokens.revoke(tok)

    # ---------- 读日志与回放（HMI H3：每个只读端点都可带 as_of） ----------

    def head(self) -> int:
        return self.state["seq"]

    def events(
        self, pid: str | None = None, after: int = 0, limit: int | None = None, upto: int | None = None
    ) -> list[Event]:
        with self._lock:
            out = []
            for ev in self.log.events(pid, after):
                if upto is not None and ev["seq"] > upto:
                    break
                out.append(ev)
                if limit is not None and len(out) >= limit:
                    break
            return out

    def wait_events(self, pid: str, after: int, timeout: float, limit: int | None = None) -> list[Event]:
        """长轮询：有 seq > after 的本题事件就立刻返回，否则最多等 timeout 秒。"""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                evs = self.events(pid, after, limit)
                left = deadline - time.monotonic()
                if evs or left <= 0:
                    return evs
                self._cond.wait(left)

    def state_at(self, seq: int | None = None) -> State:
        """某序号时的状态：由唯一的 reducer 重放日志前缀得到（不另写解释器）。缺省即链头。

        日志只追加、apply 是纯函数，所以缓存永不失效；从不大于 seq 的最近一份缓存接着放。"""
        with self._lock:
            if seq is None or seq >= self.state["seq"]:
                return self.state
            if seq in self._snaps:
                self._snaps.move_to_end(seq)
                return self._snaps[seq]
            base = max((k for k in self._snaps if k <= seq), default=0)
            state = self._snaps[base] if base else empty_state()
            for ev in self.log.events(None, base):
                if ev["seq"] > seq:
                    break
                state = apply(state, ev)
            self._snaps[seq] = state
            while len(self._snaps) > 64:
                self._snaps.popitem(last=False)
            return state

    # 只读端点（§3.1.2）
    def work(self, pid: str) -> list[Body]:
        return wk.work(self.state, pid)

    def budget(self, pid: str) -> wk.BudgetView:
        return wk.budget_view(self.state, pid)


class _Abort(BatchRejected):
    def __init__(self, results: list[Body]) -> None:
        super().__init__({"ok": False, "results": results})


def _subst(v: Any, ids: list[str | None]) -> Any:
    if isinstance(v, str) and v.startswith("$") and v[1:].isdigit():
        n = int(v[1:])
        if n >= len(ids) or ids[n] is None:
            return f"<批内引用 {v} 无效>"
        return ids[n]
    if isinstance(v, list):
        return [_subst(x, ids) for x in v]
    if isinstance(v, dict):
        return {k: _subst(x, ids) for k, x in v.items()}
    return v
