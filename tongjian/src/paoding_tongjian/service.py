"""通鉴服务（规格 2.4、4.3）：通鉴日志的唯一写入者。日志复用图服务的事件日志实现（同一种基质）。

- 关题即封存：扫描图状态里已关、未封存的题，追加 case_sealed；开关 case_seal 打开时同批追加 mem_derived。
  case_seal 只管"判例往下的投影"：判例本身是守门官，照常封存。
- 状态由日志重放得出；记忆状态是派生量（reducer.mem_state），不存储。
- 读：match（开题前）、items（条目与派生状态）。写：人的 mem_pin、mem_forget（带 seen）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from paoding_graph.contract import BatchRejected, Event, EventLog, State, replay

from . import reducer as rd
from .keys import digest, env_key, sig_key, signature
from .match import match
from .project import case, derive

SERVICE: dict[str, str] = {"kind": "graph", "id": "tongjian"}


class ClosedSource(Protocol):
    state: State

    def events(self, pid: str | None = None, after: int = 0, limit: int | None = None) -> list[Event]: ...


@dataclass
class TongjianConfig:
    case_seal: bool = True  # 判例往下的投影（规格第 50 条）；取值写进评测运行的元数据
    model_epoch: str = "unknown"  # 主力模型的家族与版本（类牛层随它另起累计）


class Tongjian:
    def __init__(
        self,
        path: str | Path,
        graph: ClosedSource,
        cfg: TongjianConfig | None = None,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ):
        self.log, self.graph, self.cfg, self._clock = EventLog(path), graph, cfg or TongjianConfig(), clock
        self.state: dict[str, Any] = replay(self.log.events(), rd.apply, rd.empty())
        self._lock = threading.RLock()

    def close(self) -> None:
        self.log.close()

    # ---------- 写 ----------

    def _commit(self, idem: str, ops: list[tuple[Mapping[str, Any], str, Mapping[str, Any]]]) -> dict[str, Any]:
        staged: dict[str, Any] = {}

        def build(append: Any) -> dict[str, Any]:
            st, results = self.state, []
            for n, (actor, kind, body) in enumerate(ops):
                r = rd.validate(st, actor, kind, body)
                if isinstance(r, rd.Reject):
                    raise BatchRejected({"ok": False, "code": r.code, "detail": r.detail, "at": n})
                ts = max(self._clock(), st["now"] + 1)
                ev = append(rd.LOG, kind, r.body, dict(actor), ts, f"{idem}#{n}")
                st = rd.apply(st, ev)
                results.append({"ok": True, "seq": ev["seq"]})
            staged["state"] = st
            return {"ok": True, "results": results}

        with self._lock:
            out, fresh = self.log.commit_batch(rd.LOG, idem, build)
            if fresh and out.get("ok"):
                self.state = staged["state"]
            return out

    def sweep(self) -> list[str]:
        """把已关、未封存的题各封存一份判例。返回本轮封存的题。"""
        gs = self.graph.state
        done = []
        for pid, p in sorted(gs["problems"].items()):
            if not p.get("closed") or pid in self.state["cases"]:
                continue
            if any(l["problem_id"] == pid and l["active"] for l in gs["leases"].values()):
                continue  # 关题时还在途的会话会交回用量与留档：等它们收尾，封存的链头才是最终的
            c = case(gs, self.graph.events(pid), pid, self.cfg.model_epoch)
            ops: list[tuple[Mapping[str, Any], str, Mapping[str, Any]]] = [(SERVICE, "case_sealed", {"case": c})]
            if self.cfg.case_seal:
                ops.append((SERVICE, "mem_derived", {"case": pid, "items": derive(gs, pid, c)}))
            if self._commit(f"seal:{pid}", ops).get("ok"):
                done.append(pid)
        return done

    def decide(self, kind: str, item: str, reason: str, seen: Mapping[str, Any], who: str) -> dict[str, Any]:
        """人的 mem_pin 或 mem_forget。seen 取自人看到的那张卡（card_hash）。"""
        actor = {"kind": "human", "id": who}
        return self._commit(
            f"{kind}:{item}:{digest([who, reason, seen.get('card_hash')])}",
            [(actor, kind, {"item": item, "reason": reason, "seen": seen})],
        )

    # ---------- 读 ----------

    def match(self, problem: Mapping[str, Any], query: str = "") -> dict[str, Any]:
        """problem：开题事件体（含图服务推出的 profile，见 /v1/profile/preview）。"""
        q = query or f"{problem.get('title', '')} {problem.get('goal', {}).get('statement', '')}"
        return match(self.state, env_key(problem), signature(problem), sig_key(problem), q, self.cfg.model_epoch)

    def items(self) -> list[dict[str, Any]]:
        st = self.state
        return [
            {**m, "state": rd.mem_state(st, mid), "pinned": bool(st["pins"].get(mid)), "recalls": rd.history(st, mid)}
            for mid, m in sorted(st["items"].items())
        ]

    def card(self, item: str) -> dict[str, Any]:
        return {
            **rd.card(self.state, item),
            "seen": {"seq": self.state["seq"], "card_hash": rd.card_hash(self.state, item)},
        }
