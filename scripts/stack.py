"""组装根：把六个组件接成一个进程里的一整套系统（M0 单机形态）。

    图服务（SQLite 日志 + HTTP/SSE）  ← 唯一写入者；其余组件都持自己的令牌经同一条提议通道写
    判官运行器                       ← 轮询 /work 的 judge 项
    司南                             ← 每道未关的题一个循环：读 /work → 租约（预留预算）→ 按租约起会话
    哮天犬                           ← 过期回收、超预算终止、孤儿容器清扫
    Adapter（端点代理 + 工具端点 + 会话运行器）与执行层（Docker）是司南与判官的下层，同一进程里

为什么是一个进程：GraphService 是唯一写入者，状态在内存里由日志重放得到；两个进程各开一份 GraphService
对着同一个 SQLite 会各自持有过时的状态。组件之间仍只经契约端口（GraphPort、GraphReader、SessionPort、
TaskControl）交互，跨进程部署时把端口换成 HTTP 客户端即可，组件代码不动。

会话后端在本阶段只有假 CLI（adapter/src/paoding_adapter/fakecli.py）：模型端点是本机的假上游，
不需要任何密钥；每类任务的脚本由配置给出。真实后端由人在后续阶段接入。
"""
from __future__ import annotations

import json
import logging
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from paoding_adapter.contract import (AdapterConfig, CliBinding, EndpointProxy, FakeUpstream,  # noqa: E402
                                      PriceTable, ProxyConfig, SessionRunner, ToolEndpoint, fake_program)
from paoding_executor.contract import DockerExecutor, sweep_orphans  # noqa: E402
from paoding_graph.contract import (BlobStore, Config, GraphHttp, GraphService, HttpConfig,  # noqa: E402
                                    TokenRegistry)
from paoding_judgebox.contract import JudgeConfig, JudgeRunner, Vault, kernel_judges, load_registry  # noqa: E402
from paoding_sinan.contract import Sinan, SinanConfig  # noqa: E402
from paoding_watchdog.contract import DogConfig, Watchdog  # noqa: E402

PRICES = ROOT / "adapter" / "config" / "prices.yaml"
TASK_KINDS = ("bootstrap", "reason", "explore")
DEV_ORIGIN = "http://127.0.0.1:5173"               # web/ 的 vite 开发服务器（只监听回环）


def log(component: str) -> logging.Logger:
    return logging.getLogger(component)


def setup_logging(level: int = logging.INFO) -> None:
    """stderr，一行一条：时间、组件名、消息。"""
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(_OneLine("%(asctime)s %(name)-8s %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)


class _OneLine(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return super().format(record).replace("\r", " ").replace("\n", " ⏎ ")


# ---------- 配置 ----------

@dataclass
class StackConfig:
    home: Path
    port: int = 8100
    allow_origins: tuple = (DEV_ORIGIN,)
    static_dir: Path | None = None
    # 会话后端：本阶段只有 fake。scripts：任务种类 → 假 CLI 脚本路径；缺的种类司南不开
    backend: str = "fake"
    scripts: dict = field(default_factory=dict)
    usage: dict | None = None                       # 假上游每个请求回报的 usage
    executor: str = "docker"                        # docker | none（none：没有 exec，只适合看界面）
    bases: dict = field(default_factory=lambda: {"basic": "python:3.12-slim"})
    poll_s: float = 0.5                             # 司南与判官的轮询间隔
    dog_interval_s: float = 2.0
    ttl_s: int = 600
    renew_s: float = 60.0
    stall_s: float = 120.0

    @classmethod
    def load(cls, home: Path, path: Path | None = None, **over) -> "StackConfig":
        """配置文件（JSON）可省：没有就是空配置——假 CLI 后端、没有脚本、Docker 执行层。
        文件里的相对路径相对配置文件所在目录。"""
        raw: dict = {}
        path = path or (home / "config.json")
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
        base = path.parent
        be = raw.get("backend", {})
        if isinstance(be, str):
            be = {"kind": be}
        ex = raw.get("executor", {})
        if isinstance(ex, str):
            ex = {"kind": ex}
        cfg = cls(home=home,
                  backend=be.get("kind", "fake"),
                  scripts={k: str((base / v).resolve()) for k, v in be.get("scripts", {}).items()},
                  usage=be.get("usage"),
                  executor=ex.get("kind", "docker"),
                  **({"bases": ex["bases"]} if "bases" in ex else {}),
                  **{k: raw[k] for k in ("poll_s", "dog_interval_s", "ttl_s", "renew_s", "stall_s") if k in raw})
        for k, v in over.items():
            if v is not None:
                setattr(cfg, k, v)
        return cfg


class StackError(RuntimeError):
    pass


def docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


# ---------- 组装 ----------

class Stack:
    def __init__(self, cfg: StackConfig):
        if cfg.backend != "fake":
            raise StackError(f"会话后端 {cfg.backend!r} 本阶段不接：只有假 CLI（backend: fake）。真实后端由人在后续阶段接入")
        if cfg.executor not in ("docker", "none"):
            raise StackError(f"执行层取 docker 或 none，不是 {cfg.executor!r}")
        if cfg.executor == "docker" and not docker_available():
            raise StackError("执行层要 Docker，但 docker info 失败。先起 dockerd，或在配置里写 \"executor\": \"none\"（没有 exec，只适合看界面）")
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.workers: dict[str, threading.Thread] = {}
        self._stopped = False
        home = cfg.home
        home.mkdir(parents=True, exist_ok=True)

        # 令牌：人的令牌落盘（网页右上角填它）；组件令牌每次启动随机发，只在本进程
        tf = home / "human.token"
        if not tf.exists():
            tf.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            tf.chmod(0o600)
        self.human_token = tf.read_text(encoding="utf-8").strip()
        self.tokens = TokenRegistry()
        self.tokens.issue({"kind": "human", "id": "human"}, self.human_token)
        self.tok = {k: self.tokens.issue({"kind": k, "id": f"{k[:2]}1"}) for k in
                    ("sinan", "judge", "adapter", "executor", "watchdog")}

        # 图服务
        self.registry = load_registry()
        self.judges = kernel_judges(self.registry)
        self.graph = GraphService(home / "g.sqlite", Config(judges=self.judges), self.tokens)
        self.blobs = BlobStore(home / "blobs")
        self.http = GraphHttp(self.graph, self.blobs, HttpConfig(
            port=cfg.port, allowed_origins=tuple(cfg.allow_origins), static_dir=cfg.static_dir,
            heartbeat_s=5.0))
        self.vault = Vault(home / "vault")

        # 执行层
        self.executor = DockerExecutor(self.graph, self.blobs, self.tok["executor"]) if cfg.executor == "docker" else None

        # Adapter：假上游 → 端点代理 → 工具端点 → 会话运行器（假 CLI）
        self.upstream = FakeUpstream(cfg.usage)
        self.proxy = EndpointProxy(ProxyConfig(self.upstream.url, "sk-fake-upstream", self.tok["adapter"]),
                                   PriceTable.load(PRICES), self.graph)
        self.endpoint = ToolEndpoint()
        self.adapter_cfg = AdapterConfig(
            root=home / "sessions", renew_s=cfg.renew_s, stall_s=cfg.stall_s, judges_cfg=self.judges,
            binding=CliBinding(program=fake_program()), bases=dict(cfg.bases),
            env_for=lambda lease: {"PD_FAKE_SCRIPT": cfg.scripts.get(lease["kind"], "")})
        self.runner = SessionRunner(self.adapter_cfg, self.graph, self.graph, self.blobs, self.tokens,
                                    self.proxy, self.endpoint, self.executor)

        # 判官运行器、哮天犬
        self.judge = JudgeRunner(JudgeConfig(token=self.tok["judge"], registry=self.registry, bases=dict(cfg.bases)),
                                 self.graph, self.graph, self.blobs, self.vault, self.executor)
        self.dog = Watchdog(DogConfig(token=self.tok["watchdog"], interval_s=cfg.dog_interval_s), self.graph,
                            self.graph, control=self.runner,
                            sweep=sweep_orphans if self.executor is not None else None)
        self.url = ""

    # ---------- 起 ----------

    def start(self) -> str:
        """按次序起：图服务 → 判官运行器 → 司南 → 哮天犬。返回图服务的地址。"""
        self.proxy.serve()
        self.endpoint.serve()
        self.url = self.http.serve()
        log("graph").info("HTTP + SSE 在 %s（链头 seq=%d，题 %d 道；人的令牌在 %s）", self.url, self.graph.head(),
                          len(self.graph.state["problems"]), self.cfg.home / "human.token")
        self._spawn("events", self._follow_events)
        self._spawn("judge", self._judge_loop)
        log("judge").info("判官运行器已起：%s", ", ".join(f"{k}@{v['version']}" for k, v in sorted(self.judges.items())))
        self._spawn("sinan", self._sinan_supervisor)
        missing = [k for k in TASK_KINDS if not self.cfg.scripts.get(k)]
        log("sinan").info("司南已起：后端 fake（假上游 %s）%s", self.upstream.url,
                          f"；没有脚本的任务种类不开：{', '.join(missing)}" if missing else "")
        self._spawn("watchdog", self._dog_loop)
        log("watchdog").info("哮天犬已起：每 %.1f 秒一轮%s", self.cfg.dog_interval_s,
                             "" if self.executor else "（执行层 none，不清扫容器）")
        return self.url

    def _spawn(self, name: str, fn) -> None:
        t = threading.Thread(target=self._guarded, args=(name, fn), name=name, daemon=True)
        self.threads.append(t)
        t.start()

    def _guarded(self, name: str, fn) -> None:
        try:
            fn()
        except Exception:
            log(name).exception("线程异常退出")

    # ---------- 事件流：每条落盘事件一行日志 ----------

    def _follow_events(self) -> None:
        after = self.graph.head()
        L = log("graph")
        while not self.stop_event.is_set():
            evs = self.graph.events(None, after, limit=200)
            for ev in evs:
                after = ev["seq"]
                L.info("#%d %s %s ← %s%s", ev["seq"], ev["problem_id"], ev["kind"], _who(ev["actor"]), _gist(ev))
            if not evs:
                self.stop_event.wait(0.2)

    # ---------- 判官 ----------

    def _judge_loop(self) -> None:
        L = log("judge")
        while not self.stop_event.is_set():
            try:
                for d in self.judge.tick():
                    L.info("%s 请求 %s → %s（%s）%s", d.get("status"), d.get("request"), d.get("result", "-"),
                           d.get("reason", d.get("code", "")), "" if d.get("status") == "judged" else d)
            except Exception:
                L.exception("tick 失败")
            self.stop_event.wait(self.cfg.poll_s)

    # ---------- 司南：每道未关的题一个循环 ----------

    def _sinan_supervisor(self) -> None:
        while not self.stop_event.is_set():
            for pid, p in sorted(self.graph.state["problems"].items()):
                t = self.workers.get(pid)
                if p.get("closed") or (t is not None and t.is_alive()):
                    continue
                t = threading.Thread(target=self._guarded, args=("sinan", lambda pid=pid: self._sinan_loop(pid)),
                                     name=f"sinan-{pid}", daemon=True)
                self.workers[pid] = t
                t.start()
            self.stop_event.wait(self.cfg.poll_s)

    def _sinan_loop(self, pid: str) -> None:
        L = log("sinan")
        sinan = Sinan(SinanConfig(token=self.tok["sinan"], ttl_s=self.cfg.ttl_s), self.graph, self.graph,
                      self.blobs, self.runner)
        last = None
        L.info("%s 开始调度", pid)
        while not self.stop_event.is_set():
            choice = sinan.pick(pid)
            if choice.get("stop") == "closed":
                p = self.graph.state["problems"][pid]
                L.info("%s 已关题，终态 %s", pid, p.get("terminal"))
                return
            if "do" in choice:
                kind = choice["do"]["kind"]
                if not self.cfg.scripts.get(kind):
                    note = f"没有 {kind} 的会话后端（假 CLI 脚本），等配置"
                else:
                    r = sinan.step(pid)
                    if "did" in r:
                        L.info("%s %s 会话结束：租约 %s，%s，release=%s", pid, r["did"]["kind"], r["lease"],
                               r["status"], r["outcome"])
                        last = None
                        continue
                    note = _note(r)
            else:
                note = _note(choice)
            if note != last:
                L.info("%s %s", pid, note)
                last = note
            self.stop_event.wait(self.cfg.poll_s)

    # ---------- 哮天犬 ----------

    def _dog_loop(self) -> None:
        L = log("watchdog")
        while not self.stop_event.is_set():
            try:
                r = self.dog.tick()
                for k in ("expired", "soft", "killed", "closed", "swept", "alerts"):
                    if getattr(r, k):
                        L.info("%s: %s", k, getattr(r, k))
            except Exception:
                L.exception("tick 失败")
            self.stop_event.wait(self.cfg.dog_interval_s)

    # ---------- 停 ----------

    def stop(self, grace_s: float = 20.0) -> None:
        """优雅退出：先叫停在途会话（假 CLI 进程树、执行容器），等各循环收尾，再关服务。不留孤儿进程与容器。"""
        if self._stopped:
            return
        self._stopped = True
        L = log("stack")
        L.info("停机：收掉在途会话 %s", sorted(self.runner.live) or "（无）")
        self.stop_event.set()
        for lid in list(self.runner.live):
            self.runner.kill(lid, "shutdown")
        deadline = time.monotonic() + grace_s
        for t in [*self.workers.values(), *self.threads]:
            t.join(max(0.1, deadline - time.monotonic()))
        stuck = [t.name for t in [*self.workers.values(), *self.threads] if t.is_alive()]
        if stuck:
            L.warning("这些线程没在 %.0f 秒内收尾：%s", grace_s, stuck)
            for lid in list(self.runner.live):
                self.runner.kill(lid, "shutdown")
        if self.executor is not None:
            self.executor.close()
        self.endpoint.close()
        self.proxy.close()
        self.upstream.close()
        self.http.close()
        L.info("已停：链头 seq=%d", self.graph.head())


def _who(actor: dict) -> str:
    return actor["kind"] + (f"/{actor['role']}" if actor.get("role") else "")


def _gist(ev: dict) -> str:
    b = ev.get("body") or {}
    k = ev["kind"]
    if k == "lease":
        return f"（{b.get('kind')}{' → ' + b['target'] if b.get('target') else ''}，预留 {b.get('reserve', {}).get('usd_milli')} 毫美元）"
    if k == "release":
        return f"（{b.get('lease')}：{b.get('outcome')}）"
    if k == "judge_verdict":
        return f"（{b.get('request')}：{b.get('result')}）"
    if k == "close_problem":
        return f"（终态 {b.get('terminal')}）"
    if k == "cost":
        return f"（{b.get('source')} {b.get('usd_milli')} 毫美元）"
    if k in ("add_fact", "add_intent", "open_problem"):
        return f"（{b.get('title', '')}）"
    if k == "request_judge":
        return f"（{b.get('target')} ← {b.get('judge_id')}）"
    return ""


def _note(r: dict) -> str:
    if "wait" in r:
        return f"等待：{r['wait']}"
    why = r.get("stop")
    if why == "needs_human":
        return f"需要人：{[i.get('target') for i in r.get('items', [])]}"
    if why == "idle":
        return "没有可做的事，等新事件（Hint、审批或判定）"
    return f"停：{why} {r.get('detail', '')}".rstrip()


def default_static() -> Path | None:
    d = ROOT / "web" / "dist"
    return d if (d / "index.html").is_file() else None

