"""司南的最小循环（§4.1，D11）：读 /work → 挑一项 → 申请租约（同时预留预算）→ 按租约启动会话。

确定性代码，不调用模型，不写任何与等级有关的东西（I8）：它提交的只有 `lease`。
判定不归它管：/work 里的 judge 项由判官运行器领走，司南只是在判定未决时先不开新任务（开关 `wait_for_judges`）。

并发：会话在线程池里跑（`max_sessions`，默认 3），调度本身仍是单线程——`dispatch` 领租约、把会话交给线程池
就返回，`collect` 收回跑完的。互斥有两层：内核的租约（同一目标上已有在途租约则 `conflict_leased`，Reason
每题至多一个在途）与司南自己记的在途表（同一 Intent 的上一个会话线程没收尾之前不再开）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any

from paoding_adapter.contract import SessionPort
from paoding_graph.contract import BlobError, BlobPort, GraphPort, GraphReader

TASK_ORDER = ("bootstrap", "reason", "explore")


@dataclass
class SinanConfig:
    token: str
    holder: str = "sn1"
    ttl_s: int = 600
    reserve: dict = field(
        default_factory=lambda: {
            "bootstrap": {"usd_milli": 500, "wall_s": 600},
            "reason": {"usd_milli": 300, "wall_s": 300},
        }
    )
    explore_cap: dict = field(default_factory=lambda: {"usd_milli": 1000, "wall_s": 900})
    max_sessions: int = 3  # 本实例同时在途的会话上限；1 即退回串行
    # —— T-1 结构的开关（附录 B）：关掉后退化为按 /work 给出的顺序 ——
    order_by_gain: bool = True  # explore 之间按 expected_gain 从高到低（估值类字段，只读）
    wait_for_judges: bool = True  # 判定未决时不开新任务：让下一轮 Reason 看到裁决后的图
    thin_bootstrap: bool = True  # Bootstrap 先瘦：预留不超过 bootstrap_share × cap


class Sinan:
    def __init__(self, cfg: SinanConfig, graph: GraphPort, reader: GraphReader, blobs: BlobPort, sessions: SessionPort):
        if cfg.max_sessions < 1:
            raise ValueError("max_sessions 至少为 1")
        self.cfg, self.graph, self.reader, self.blobs, self.sessions = cfg, graph, reader, blobs, sessions
        self.history: list[dict] = []
        self._pool: ThreadPoolExecutor | None = None  # 用到时才建：只读的用法（pick）不起线程
        self._flying: dict[Future, dict] = {}  # 在途会话：{"pid", "item", "lease"}
        self._lock = threading.Lock()

    # ---------- 在途 ----------

    def in_flight(self, pid: str | None = None) -> list[dict]:
        """本实例交给线程池、还没收回的会话。"""
        with self._lock:
            return [dict(f) for f in self._flying.values() if pid is None or f["pid"] == pid]

    def close(self) -> None:
        """不再接新会话。在途会话由调用方叫停（SessionRunner.kill），这里不等。"""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    # ---------- 选择 ----------

    def pick(self, pid: str) -> dict:
        """从 /work 里挑下一步。返回 {"do": 项} 或 {"wait": 原因} 或 {"stop": 原因}。只读。"""
        st = self.reader.state
        p = st["problems"].get(pid)
        if p is None:
            return {"stop": "unknown_problem"}
        if p.get("closed"):
            return {"stop": "closed"}
        work = self.reader.work(pid)
        leases = [l for l in st["leases"].values() if l["problem_id"] == pid and l["active"]]
        # 判定未决 = /work 里还有 judge 项，或判官已领走、裁决还没落盘（领走后它就不在 /work 里了）。
        # 多线程部署里判官与司南并行，只看 /work 会让 Reason 读到裁决之前的图。
        judging = any(w["kind"] in ("judge", "rejudge") for w in work) or any(l["kind"] == "judge" for l in leases)
        if self.cfg.wait_for_judges and judging:
            return {"wait": "judge"}
        mine = {(f["item"]["kind"], f["item"].get("target")) for f in self.in_flight(pid)}
        tasks = [w for w in work if w["kind"] in TASK_ORDER and (w["kind"], w.get("target")) not in mine]
        # Reason 先于新的 Explore：Reason 该跑或正在跑时不开新的 Explore（它会改写 Intent 的格局），
        # 已在途的 Explore 不受影响。串行时这条由排序保证，并发时要显式守住。
        reasoning = any(l["kind"] == "reason" for l in leases) or ("reason", None) in mine
        if reasoning or any(w["kind"] == "reason" for w in tasks):
            tasks = [w for w in tasks if w["kind"] != "explore"]
        if not tasks:
            if judging:
                return {"wait": "judge"}
            if reasoning:
                return {"wait": "reason"}
            if leases or mine:
                return {"wait": "in_flight"}
            humans = [w for w in work if w["kind"] == "human"]
            return {"stop": "needs_human", "items": humans} if humans else {"stop": "idle"}
        return {"do": min(tasks, key=lambda w: self._rank(st, w, tasks))}

    def _rank(self, st: dict, w: dict, tasks: list) -> tuple:
        gain = 0.0
        if w["kind"] == "explore" and self.cfg.order_by_gain:
            gain = float(st["intents"][w["target"]].get("expected_gain") or 0.0)
        return (TASK_ORDER.index(w["kind"]), -gain, tasks.index(w))

    def _reserve(self, st: dict, pid: str, w: dict) -> dict:
        if w["kind"] == "explore":
            want = st["intents"][w["target"]].get("budget") or self.cfg.explore_cap
            return {k: min(int(want.get(k, v)), v) for k, v in self.cfg.explore_cap.items()}
        r = dict(self.cfg.reserve[w["kind"]])
        if w["kind"] == "bootstrap" and self.cfg.thin_bootstrap:
            b = st["problems"][pid]["budget"]
            r["usd_milli"] = min(r["usd_milli"], int(b["bootstrap_share"] * b["usd_milli"]))
        return r

    # ---------- 开一个会话（不等它跑完） ----------

    def dispatch(self, pid: str) -> dict:
        """挑一项、领租约（同时预留预算）、把会话交给线程池。返回 {"started": 项, "lease": id}，
        或与 pick 同形的 {"wait": …} / {"stop": …}。只由调度线程调用。"""
        with self._lock:
            if len(self._flying) >= self.cfg.max_sessions:
                return {"wait": "capacity"}
        choice = self.pick(pid)
        if "do" not in choice:
            return choice
        w, st = choice["do"], self.reader.state
        # 幂等键带上项本身：同一 seq 上接连领两个租约时，后一个不能被当成前一个的重放
        idem = f"sinan-lease:{pid}:{st['seq']}:{w['kind']}:{w.get('target') or '-'}"
        out = self.graph.submit(
            self.cfg.token,
            pid,
            idem,
            [
                {
                    "op": "lease",
                    "body": {
                        "kind": w["kind"],
                        **({"target": w["target"]} if w.get("target") else {}),
                        "holder": self.cfg.holder,
                        "reserve": self._reserve(st, pid, w),
                        "ttl_s": self.cfg.ttl_s,
                    },
                }
            ],
        )
        if not out["ok"]:
            r = out["results"][0]
            code = r.get("code", "rejected")
            # 别的会话还占着预留或目标：等它们收尾，不是停机
            if code in ("over_budget", "conflict_leased") and self.in_flight():
                return {"wait": code, "item": w}
            return {"stop": code, "item": w, "detail": r.get("detail", "")}
        lid = out["results"][0]["id"]
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self.cfg.max_sessions, thread_name_prefix="sinan-session")
        statement = self._statement(pid)
        with self._lock:
            fut = self._pool.submit(self.sessions.run, pid, lid, statement=statement)
            self._flying[fut] = {"pid": pid, "item": w, "lease": lid}
        return {"started": w, "lease": lid}

    def collect(self, timeout: float | None = 0, pid: str | None = None) -> list[dict]:
        """收回跑完的会话，记入 history。timeout=0 不等；None 等到至少一个跑完；正数最多等这么久。
        会话线程里抛出的异常在这里变成一条 status="crashed" 的记录，不带倒调度线程。"""
        with self._lock:
            futs = [f for f, v in self._flying.items() if pid is None or v["pid"] == pid]
        if not futs:
            return []
        ready, _ = wait(futs, timeout=timeout, return_when=FIRST_COMPLETED)
        out = []
        for fut in sorted(ready, key=futs.index):
            with self._lock:
                info = self._flying.pop(fut)
            out.append(self._done(info, fut))
        self.history.extend(out)
        return out

    @staticmethod
    def _done(info: dict, fut: Future) -> dict:
        err = fut.exception()
        if err is not None:
            return {
                "did": info["item"],
                "lease": info["lease"],
                "status": "crashed",
                "outcome": None,
                "detail": f"{type(err).__name__}: {err}",
            }
        rec = fut.result()
        return {
            "did": info["item"],
            "lease": info["lease"],
            "status": rec.status,
            "outcome": (rec.release or {}).get("outcome"),
        }

    # ---------- 一步（串行：开一个会话并等它跑完） ----------

    def step(self, pid: str) -> dict:
        r = self.dispatch(pid)
        if "started" not in r:
            return r
        with self._lock:
            fut = next(f for f, v in self._flying.items() if v["lease"] == r["lease"])
        wait([fut])
        with self._lock:
            info = self._flying.pop(fut)
        done = self._done(info, fut)
        self.history.append(done)
        return done

    def _statement(self, pid: str) -> str:
        st = self.reader.state
        ref = st["problems"][pid]["origin"]["statement_ref"]
        try:
            return self.blobs.get(st["artifacts"][ref]["hash"]).decode("utf-8", "replace")
        except (BlobError, OSError):  # 题面 Blob 不在本机或读不出：会话仍可从任务包里读到 Goal
            return st["problems"][pid]["goal"]["statement"]

    # ---------- 跑到停 ----------

    def run(self, pid: str, max_steps: int = 50, between: Callable[[], Any] | None = None) -> dict:
        """循环到题目关闭、需要人或没有可做的事。between 在每一轮之前调用（单进程部署里用来驱动判官运行器）。

        每一轮：把能开的会话都开出去（至多 max_sessions 个在途），再等至少一个跑完。"""
        waits = 0
        for _ in range(max_steps):
            if between is not None:
                between()
            r = self.dispatch(pid)
            while "started" in r:
                r = self.dispatch(pid)
            if self.in_flight(pid):
                self.collect(None, pid)
                waits = 0
                continue
            if "stop" in r:
                return {**r, "steps": list(self.history)}
            waits += 1
            if between is None or waits > 3:  # 没有人会来推进：交回调用方
                return {"stop": f"waiting_{r['wait']}", "steps": list(self.history)}
        return {"stop": "max_steps", "steps": list(self.history)}
