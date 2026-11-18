"""图服务：唯一写入者（§3.1.2）。把令牌、时钟、日志与纯函数内核接在一起。

- 身份只来自令牌（tokens.py），不来自请求体。
- 一批提议整批原子：逐条在演进中的状态上 validate，任何一条被拒则整批不落盘，返回各条结果。
- 批内后一条可以用 "$<下标>" 引用前一条产生的 id。
- 每批应用后，按 work.followups 追加图服务自己的事件（budget_mark、自动关题），与这批同一事务。
- 同一 (problem_id, idem_key) 重放返回首次结果；进程被 kill -9 后重启，状态由日志重放得出（3.1.5 的 2）。
- 时钟只在这里读（clock 可注入），作为参数交给 validate 与事件信封；reducer 不读时钟。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from . import work as wk
from .eventlog import EventLog
from .reducer import Config, Ok, apply, empty_state, result_id, validate
from .replay import replay
from .tokens import TokenRegistry, UnknownToken

GRAPH_ACTOR = {"kind": "graph", "id": "graph"}



class GraphService:
    def __init__(self, path: str | Path, cfg: Config, tokens: TokenRegistry,
                 clock: Callable[[], int] = lambda: int(time.time() * 1000)):
        self.log, self.cfg, self.tokens, self._clock = EventLog(path), cfg, tokens, clock
        self.state = replay(self.log.events(), apply, empty_state())     # 崩溃恢复即重放

    def _ts(self) -> int:
        return max(self._clock(), self.state["now"] + 1)

    def submit(self, token: str, pid: str, idem_key: str, ops: list[dict]) -> dict:
        try:
            actor = self.tokens.resolve(token)
        except UnknownToken:
            return {"ok": False, "results": [{"ok": False, "code": "forbidden_op", "detail": "未知令牌"}]}

        staged: dict[str, Any] = {}

        def build(append) -> dict:
            state = self.state
            results: list[dict] = []
            evs: list[dict] = []
            ids: list[str | None] = []
            for i, op in enumerate(ops):
                kind, body = op["op"], _subst(op.get("body", {}), ids)
                ts = self._ts() if not evs else max(self._ts(), evs[-1]["ts"])
                r = validate(state, actor, pid, kind, body, self.cfg, ts)
                if not isinstance(r, Ok):
                    results.append({"ok": False, "code": r.code, "detail": r.detail})
                    raise _Abort(results + [{"ok": False, "code": "batch_aborted", "detail": f"第 {i} 条被拒"}
                                            for _ in ops[i + 1:]])
                ev = append(pid, kind, r.body, actor, ts, f"{idem_key}#{i}")
                state = apply(state, ev)
                evs.append(ev)
                ids.append(result_id(ev))
                results.append({"ok": True, "id": ids[-1], "seq": ev["seq"]})
            for fkind, fbody in wk.followups(state, pid):
                r = validate(state, GRAPH_ACTOR, pid, fkind, fbody, self.cfg, evs[-1]["ts"] if evs else self._ts())
                if isinstance(r, Ok):
                    ev = append(pid, fkind, r.body, GRAPH_ACTOR, evs[-1]["ts"] if evs else self._ts(),
                                f"{idem_key}#auto-{fkind}-{len(evs)}")
                    state = apply(state, ev)
                    evs.append(ev)
            staged["state"] = state
            return {"ok": True, "results": results}

        out, fresh = self.log.commit_batch(pid, idem_key, build)
        if fresh and out.get("ok"):
            self.state = staged["state"]
        return out

    def system(self, pid: str, kind: str, body: dict, actor: dict, idem_key: str) -> dict:
        """组件内部（哮天犬等）以固定身份提交，不经令牌。只供同进程的服务组件调用。"""
        tok = self.tokens.issue(actor)
        try:
            return self.submit(tok, pid, idem_key, [{"op": kind, "body": body}])
        finally:
            self.tokens.revoke(tok)

    # 只读端点（§3.1.2）
    def work(self, pid: str) -> list[dict]:
        return wk.work(self.state, pid)

    def budget(self, pid: str) -> dict:
        return wk.budget_view(self.state, pid)


class _Abort(Exception):
    def __init__(self, results):
        super().__init__("batch rejected")
        self.batch_results = {"ok": False, "results": results}


def _subst(v: Any, ids: list) -> Any:
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
