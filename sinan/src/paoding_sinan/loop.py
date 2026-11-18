"""司南的最小循环（§4.1，D11）：读 /work → 挑一项 → 申请租约（同时预留预算）→ 按租约启动会话。

确定性代码，不调用模型，不写任何与等级有关的东西（I8）：它提交的只有 `lease`。
判定不归它管：/work 里的 judge 项由判官运行器领走，司南只是在判定未决时先不开新任务（开关 `wait_for_judges`）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from paoding_adapter.contract import SessionPort
from paoding_graph.contract import BlobPort, GraphPort, GraphReader

TASK_ORDER = ("bootstrap", "reason", "explore")


@dataclass
class SinanConfig:
    token: str
    holder: str = "sn1"
    ttl_s: int = 600
    reserve: dict = field(default_factory=lambda: {"bootstrap": {"usd_milli": 500, "wall_s": 600},
                                                   "reason": {"usd_milli": 300, "wall_s": 300}})
    explore_cap: dict = field(default_factory=lambda: {"usd_milli": 1000, "wall_s": 900})
    # —— T-1 结构的开关（附录 B）：关掉后退化为按 /work 给出的顺序 ——
    order_by_gain: bool = True          # explore 之间按 expected_gain 从高到低（估值类字段，只读）
    wait_for_judges: bool = True        # 判定未决时不开新任务：让下一轮 Reason 看到裁决后的图
    thin_bootstrap: bool = True         # Bootstrap 先瘦：预留不超过 bootstrap_share × cap


class Sinan:
    def __init__(self, cfg: SinanConfig, graph: GraphPort, reader: GraphReader, blobs: BlobPort,
                 sessions: SessionPort):
        self.cfg, self.graph, self.reader, self.blobs, self.sessions = cfg, graph, reader, blobs, sessions
        self.history: list[dict] = []

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
        # 判定未决 = /work 里还有 judge 项，或判官已领走、裁决还没落盘（领走后它就不在 /work 里了）。
        # 多线程部署里判官与司南并行，只看 /work 会让 Reason 读到裁决之前的图。
        judging = any(w["kind"] in ("judge", "rejudge") for w in work) or any(
            l["active"] and l["kind"] == "judge" for l in st["leases"].values() if l["problem_id"] == pid)
        if self.cfg.wait_for_judges and judging:
            return {"wait": "judge"}
        tasks = [w for w in work if w["kind"] in TASK_ORDER]
        if not tasks:
            if judging:
                return {"wait": "judge"}
            if any(l["active"] for l in st["leases"].values() if l["problem_id"] == pid):
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

    # ---------- 一步 ----------

    def step(self, pid: str) -> dict:
        choice = self.pick(pid)
        if "do" not in choice:
            return choice
        w, st = choice["do"], self.reader.state
        out = self.graph.submit(self.cfg.token, pid, f"sinan-lease:{pid}:{st['seq']}", [{"op": "lease", "body": {
            "kind": w["kind"], **({"target": w["target"]} if w.get("target") else {}), "holder": self.cfg.holder,
            "reserve": self._reserve(st, pid, w), "ttl_s": self.cfg.ttl_s}}])
        if not out["ok"]:
            r = out["results"][0]
            return {"stop": r.get("code", "rejected"), "item": w, "detail": r.get("detail", "")}
        lid = out["results"][0]["id"]
        rec = self.sessions.run(pid, lid, statement=self._statement(pid))
        done = {"did": w, "lease": lid, "status": rec.status, "outcome": (rec.release or {}).get("outcome")}
        self.history.append(done)
        return done

    def _statement(self, pid: str) -> str:
        st = self.reader.state
        ref = st["problems"][pid]["origin"]["statement_ref"]
        try:
            return self.blobs.get(st["artifacts"][ref]["hash"]).decode("utf-8", "replace")
        except Exception:                               # 题面 Blob 不在本机：会话仍可从任务包里读到 Goal
            return st["problems"][pid]["goal"]["statement"]

    # ---------- 跑到停 ----------

    def run(self, pid: str, max_steps: int = 50, between: Callable[[], Any] | None = None) -> dict:
        """循环到题目关闭、需要人或没有可做的事。between 在每一步之前调用（单进程部署里用来驱动判官运行器）。"""
        waits = 0
        for _ in range(max_steps):
            if between is not None:
                between()
            r = self.step(pid)
            if "stop" in r:
                return {**r, "steps": list(self.history)}
            if "wait" in r:
                waits += 1
                if between is None or waits > 3:        # 没有人会来推进：交回调用方
                    return {"stop": f"waiting_{r['wait']}", "steps": list(self.history)}
                continue
            waits = 0
        return {"stop": "max_steps", "steps": list(self.history)}
