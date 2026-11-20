"""哮天犬（§3.5.2、3.4.4）：不含任何策略的脚本，只做四件事。

1. 过期租约：expires_at 已过的在途租约，提交 expire_lease；Intent 回到 open（Adapter 崩溃时的回收）。
2. 超预算终止：读 /budget 与 cost 事件。任务花费越过软线（预留额的 90%）→ 通知 Adapter 进入收尾轮
   （开放道的题墙钟用到 90% 时同样通知求解会话收尾交付），
   每个任务只通知一次；越过硬顶（预留额）→ 终止任务。题花费达到 cap → 终止题内所有任务，以 unsolved 关题。
   题的墙钟（wall_s）用尽 → 同样终止并关题。墙钟的含义随开题时抄进事件体的 wall_mode（external-verdict §5.6）：
   elapsed（缺省，旧行为）按开题以来的墙钟；spend 按花费墙钟（cost 事件的 wall_s 累计），另有题的最长存活
   life_s 兜底。两种取值下都执行 deadline：到点停掉工作租约，等待中的延迟判官复判在 settle_s 之内照常进行，
   之后关题。
   开放道（地图 v0.9 Q20、Q33）另有三条：人叫停之后通知在途的求解会话收尾，HALT_GRACE_S 之后仍在就终止；
   墙钟按“这一轮”计（从开题或最后一次追问算起），交付之后等人的时间不算；交付后闲置满 idle_close_s
   （开题时抄入，缺省 7 天）自动关题，原因 idle，不带反馈。
3. 清理孤儿容器：调用注入的清扫函数（执行层按标签回收）。
4. 健康告警：某后端最近 N 个任务里失败占比超过阈值 → backend_unhealthy 告警交人。

依赖方向只到 graph.contract（ci/check_deps.py）。对会话与容器的动作经注入的 TaskControl 完成，
由组装根把 Adapter 的会话运行器接进来；哮天犬不 import 任何其它组件。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from paoding_graph.contract import GraphPort, GraphReader

from .contract import TaskControl

SOFT_LINE = 0.9
HALT_GRACE_S = 60  # 与 graph reducer.deliver.HALT_GRACE_S 相同（D12）；哮天犬只依赖 contract，这里抄一份
IDLE_CLOSE_S = 7 * 86400  # 与 graph work.IDLE_CLOSE_S 相同：开题时没抄入时用它
FAIL_OUTCOMES = ("failed", "expired")


@dataclass
class DogConfig:
    token: str  # 哮天犬的组件令牌（actor.kind = watchdog）
    interval_s: float = 10.0
    health_window: int = 10  # 最近多少个已结束任务
    health_threshold: float = 0.5  # 失败占比超过它就告警
    health_min: int = 4  # 样本不足不告警
    settle_s: int = 3600  # deadline 之后还等延迟判官回执多久（二期改取连接器档案的 poll.settle_s）


@dataclass
class TickReport:
    expired: list = field(default_factory=list)
    soft: list = field(default_factory=list)
    killed: list = field(default_factory=list)
    closed: list = field(default_factory=list)
    swept: list = field(default_factory=list)
    alerts: list = field(default_factory=list)


def _last(p: dict, key: str) -> dict | None:
    xs = p.get(key) or []
    return xs[-1] if xs else None


def _round_start_ts(p: dict) -> int:
    """开放道这一轮的起点：最后一次追问，没有即开题（地图 Q31）。"""
    u = _last(p, "follow_ups")
    return int(u["ts"]) if u is not None else int(p["opened_ts"])


def _open_waiting_since(p: dict, solving: bool) -> int | None:
    """开放道交付之后等人的起点；这一轮还没交付、或还有在途求解会话时 None（与 graph work.waiting_since 同义）。"""
    d, u = _last(p, "deliveries"), _last(p, "follow_ups")
    if d is None or solving or (u is not None and u["seq"] > d["seq"]):
        return None
    return int(d.get("ts", p["opened_ts"]))


def _halted(p: dict) -> dict | None:
    h, u = p.get("halted"), _last(p, "follow_ups")
    return h if h is not None and (u is None or h["seq"] > u["seq"]) else None


def _over_time(p: dict, view: dict, now: int) -> str | None:
    """墙钟与存活（§5.6）。elapsed：开题以来的墙钟 ≥ wall_s（旧行为，逐字不变）。spend：花费墙钟 ≥ wall_s，
    或开题以来 ≥ life_s。"""
    if "wall_s" not in p["budget"] or "opened_ts" not in p:
        return None
    age_ms = now - p["opened_ts"]
    if p["goal"]["accept"] == "open":  # 开放道：墙钟按这一轮计，交付之后等人的时间不算（由闲置自动关接管）
        return "wall_s" if now - _round_start_ts(p) >= p["budget"]["wall_s"] * 1000 else None
    if p.get("wall_mode", "elapsed") == "elapsed":
        return "wall_s" if age_ms >= p["budget"]["wall_s"] * 1000 else None
    if (view["spent"].get("wall_s") or 0) >= p["budget"]["wall_s"]:
        return "wall_s"
    if "life_s" in p and age_ms >= p["life_s"] * 1000:
        return "life_s"
    return None


def _wall_used(p: dict, view: dict, now: int) -> float | None:
    """墙钟用掉的比例（与 _over_time 同一口径）；题没有墙钟时 None。"""
    if "wall_s" not in p["budget"] or "opened_ts" not in p or p["budget"]["wall_s"] <= 0:
        return None
    if p["goal"]["accept"] == "open":
        return (now - _round_start_ts(p)) / (p["budget"]["wall_s"] * 1000)
    if p.get("wall_mode", "elapsed") == "elapsed":
        return (now - p["opened_ts"]) / (p["budget"]["wall_s"] * 1000)
    return (view["spent"].get("wall_s") or 0) / p["budget"]["wall_s"]


class Watchdog:
    def __init__(
        self,
        cfg: DogConfig,
        graph: GraphPort,
        reader: GraphReader,
        control: TaskControl | None = None,
        sweep: Callable[[], list] | None = None,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ):
        self.cfg, self.graph, self.reader, self.control, self.sweep, self.clock = (
            cfg,
            graph,
            reader,
            control,
            sweep,
            clock,
        )
        self._soft_sent: set[str] = set()
        self._killed: set[str] = set()
        self._alerted: set[str] = set()

    def tick(self) -> TickReport:
        r = TickReport()
        now = self.clock()
        st = self.reader.state
        for pid, p in sorted(st["problems"].items()):
            if p.get("closed"):
                continue
            self._expire(pid, now, r)
            self._budget(pid, now, r)
        if self.sweep is not None:
            r.swept = list(self.sweep())
        r.alerts = self._health()
        return r

    # ---------- 1. 过期租约 ----------

    def _expire(self, pid: str, now: int, r: TickReport) -> None:
        for l in self._active(pid):
            if now >= l["expires_at"]:
                out = self.graph.submit(
                    self.cfg.token, pid, f"expire:{l['id']}", [{"op": "expire_lease", "body": {"lease": l["id"]}}]
                )
                if out["ok"]:
                    r.expired.append(l["id"])
                    self._halt(l["id"], "expired", r, record=False)  # 会话若还活着，一并收掉容器

    # ---------- 2. 超预算终止 ----------

    def _budget(self, pid: str, now: int, r: TickReport) -> None:
        st = self.reader.state
        view = self.reader.budget(pid)
        spent_by_task: dict[str, int] = {}
        for c in st["costs"]:
            if c["problem_id"] == pid:
                spent_by_task[c["task_id"]] = spent_by_task.get(c["task_id"], 0) + c["usd_milli"]
        for l in self._active(pid):
            if l["kind"] == "judge":
                continue
            spent, reserve = spent_by_task.get(l["id"], 0), l["reserve"]["usd_milli"]
            if spent >= reserve:
                self._halt(l["id"], "budget", r)
            elif spent >= SOFT_LINE * reserve and l["id"] not in self._soft_sent:
                self._soft_sent.add(l["id"])
                if self.control is not None:
                    self.control.soft_line(l["id"])
                r.soft.append(l["id"])
        p = st["problems"][pid]
        used = _wall_used(p, view, now)
        if p["goal"]["accept"] == "open" and used is not None and used >= SOFT_LINE:
            # 开放道（docs/design/open-lane/ §3.3）：墙钟到 90% 也叫求解会话收尾交付，到点关题时人手里有东西
            for l in self._active(pid):
                if l["kind"] == "solve" and l["id"] not in self._soft_sent:
                    self._soft_sent.add(l["id"])
                    if self.control is not None:
                        self.control.soft_line(l["id"])
                    r.soft.append(l["id"])
        if p["goal"]["accept"] == "open" and self._open_lane(pid, p, now, r):
            return
        cap = view["cap"].get("usd_milli")
        over_cap = cap is not None and view["spent"]["usd_milli"] >= cap
        why = "problem_budget" if over_cap else _over_time(p, view, now)
        dl = (p.get("deadline") or {}).get("at")
        if why is None and dl is not None and now >= dl:
            # 外部时限到了：停掉工作租约；延迟判官的回执还在路上时，settle_s 之内不关题（§5.6）
            for l in self._active(pid):
                if l["kind"] != "judge":
                    self._halt(l["id"], "deadline", r)
            waiting = any(i["kind"] == "rejudge" and i.get("why") == "pending" for i in self.reader.work(pid))
            if waiting and now < dl + self.cfg.settle_s * 1000:
                return
            why = "deadline"
        if why is not None:
            for l in self._active(pid):
                self._halt(l["id"], why, r)
            out = self.graph.submit(
                self.cfg.token, pid, f"close:{pid}:{why}", [{"op": "close_problem", "body": {"reason": why}}]
            )
            if out["ok"]:
                r.closed.append(pid)

    def _open_lane(self, pid: str, p: dict, now: int, r: TickReport) -> bool:
        """开放道的叫停与闲置（地图 Q20、Q33）。返回 True 表示这道题本轮已处理完（等人或已关），不再看墙钟与题预算：
        交付之后等人的时间不算墙钟；预算到顶的题在等人时也不关，人追问时再追加。"""
        solves = [l for l in self._active(pid) if l["kind"] == "solve"]
        h = _halted(p)
        if h is not None:
            for l in solves:
                if l["id"] not in self._soft_sent:
                    self._soft_sent.add(l["id"])
                    if self.control is not None:
                        self.control.soft_line(l["id"])
                    r.soft.append(l["id"])
                if now - int(h["ts"]) >= HALT_GRACE_S * 1000:
                    self._halt(l["id"], "halted", r)
        since = _open_waiting_since(p, bool(solves))
        if since is None:
            return False
        if now - since >= int(p.get("idle_close_s", IDLE_CLOSE_S)) * 1000:
            out = self.graph.submit(
                self.cfg.token, pid, f"close:{pid}:idle", [{"op": "close_problem", "body": {"reason": "idle"}}]
            )
            if out["ok"]:
                r.closed.append(pid)
        return True

    def _halt(self, lid: str, why: str, r: TickReport, record: bool = True) -> None:
        if lid in self._killed:
            return
        self._killed.add(lid)
        if self.control is not None:
            self.control.kill(lid, why)
        if record:
            r.killed.append((lid, why))

    # ---------- 4. 健康告警 ----------

    def _health(self) -> list:
        ended = [l for l in self.reader.state["leases"].values() if not l["active"] and l["kind"] != "judge"]
        ended.sort(key=lambda l: l["ended_seq"])
        by_backend: dict[str, list] = {}
        for l in ended:
            by_backend.setdefault(l.get("backend", "default"), []).append(l)
        alerts = []
        for b, ls in sorted(by_backend.items()):
            recent = ls[-self.cfg.health_window :]
            if len(recent) < self.cfg.health_min:
                continue
            rate = sum(1 for l in recent if l["outcome"] in FAIL_OUTCOMES) / len(recent)
            key = f"{b}:{recent[-1]['id']}"
            if rate > self.cfg.health_threshold and key not in self._alerted:
                self._alerted.add(key)
                alerts.append(
                    {"alert": "backend_unhealthy", "backend": b, "fail_rate": round(rate, 3), "window": len(recent)}
                )
        return alerts

    def _active(self, pid: str) -> list:
        return [l for l in self.reader.state["leases"].values() if l["problem_id"] == pid and l["active"]]

    def run_forever(self, stop: Callable[[], bool] = lambda: False) -> None:
        while not stop():
            self.tick()
            time.sleep(self.cfg.interval_s)
