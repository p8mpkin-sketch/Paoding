"""组装根：把六个组件接成一个进程里的一整套系统（M0 单机形态）。

    图服务（SQLite 日志 + HTTP/SSE）  ← 唯一写入者；其余组件都持自己的令牌经同一条提议通道写
    判官运行器                       ← 轮询 /work 的 judge 项
    司南                             ← 每道未关的题一个循环：读 /work → 租约（预留预算）→ 按租约起会话
    哮天犬                           ← 过期回收、超预算终止、孤儿容器清扫
    Adapter（端点代理 + 工具端点 + 会话运行器）与执行层（Docker）是司南与判官的下层，同一进程里

为什么是一个进程：GraphService 是唯一写入者，状态在内存里由日志重放得到；两个进程各开一份 GraphService
对着同一个 SQLite 会各自持有过时的状态。组件之间仍只经契约端口（GraphPort、GraphReader、SessionPort、
TaskControl）交互，跨进程部署时把端口换成 HTTP 客户端即可，组件代码不动。

会话后端两种（配置 backend.kind）：
- fake：脚本化假 CLI（adapter/src/paoding_adapter/fakecli.py），模型端点是本机的假上游，不需要任何密钥；
  每类任务的脚本由配置给出。缺省在宿主上起子进程；`"launcher": "container"` 时在模型容器里起（同一条容器路径）。
- real：真 CLI，缺省在模型容器里起（规格 §3.4.2）。镜像由 backend.image 给出；真实密钥从环境变量读
  （backend.api_key_env，缺省 ANTHROPIC_API_KEY），只交给端点代理，不进日志与任何容器。
  其余可选项（macOS + DeepSeek 真实测试里验证过）：
    program   CLI 的命令（字符串按 shell 规则切分，或列表），缺省 claude
    api_base  模型端点，等同 upstream，例如 https://api.deepseek.com/anthropic
    model     传给 CLI 的 --model
    api_key   密钥直接写在配置里（cz 2026-11-18 同意）。环境变量有值时以环境变量为准；用它会记一条警告，
              配置文件要自己收好权限，数据目录不入 git
"""

from __future__ import annotations

import logging
import os
import secrets
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

from paoding_judgebox.contract import JudgeConfig, JudgeRunner, Vault, kernel_judges, load_registry  # noqa: E402
from paoding_watchdog.contract import DogConfig, Watchdog  # noqa: E402

from paoding_adapter.contract import (  # noqa: E402
    FAKE_CLI,
    AdapterConfig,
    CliBinding,
    ContainerLauncher,
    EndpointProxy,
    FakeUpstream,
    PriceTable,
    ProxyConfig,
    SessionRunner,
    ToolEndpoint,
    fake_program,
    local_launcher,
)
from paoding_executor.contract import DockerExecutor, sweep_orphans  # noqa: E402
from paoding_graph.contract import BlobStore, Config, GraphHttp, GraphService, HttpConfig, TokenRegistry  # noqa: E402
from paoding_sinan.contract import Sinan, SinanConfig  # noqa: E402

PRICES = ROOT / "adapter" / "config" / "prices.yaml"
TASK_KINDS = ("bootstrap", "reason", "explore")
DEV_ORIGIN = "http://127.0.0.1:5173"  # web/ 的 vite 开发服务器（只监听回环）


def log(component: str) -> logging.Logger:
    return logging.getLogger(component)


from oplog import ctx, setup_logging  # noqa: E402,F401  （组装根的日志格式在 scripts/oplog.py）

# ---------- 配置 ----------


@dataclass
class StackConfig:
    home: Path
    port: int = 8100
    allow_origins: tuple = (DEV_ORIGIN,)
    static_dir: Path | None = None
    # 会话后端：fake | real。scripts：任务种类 → 假 CLI 脚本路径；缺的种类司南不开（只对 fake 有意义）
    backend: str = "fake"
    scripts: dict = field(default_factory=dict)
    launcher: str = ""  # container | local；缺省 real → container，fake → local
    cli_image: str = ""  # 模型容器的镜像：real 必填；fake + container 缺省用通用镜像
    upstream: str = "https://api.anthropic.com"  # real 的模型端点；fake 用本机假上游
    api_key_env: str = "ANTHROPIC_API_KEY"  # real：真实密钥所在的环境变量名
    api_key: str = ""  # real：配置里直接给的密钥（环境变量有值时不用）；不进日志
    program: tuple = ()  # real：CLI 命令；空则用 CliBinding 的缺省（claude）
    model: str = ""  # real：传给 CLI 的 --model
    usage: dict | None = None  # 假上游每个请求回报的 usage
    executor: str = "docker"  # docker | none（none：没有 exec，只适合看界面）
    bases: dict = field(default_factory=lambda: {"basic": "python:3.12-slim"})
    poll_s: float = 0.5  # 司南与判官的轮询间隔
    dog_interval_s: float = 2.0
    ttl_s: int = 600
    max_sessions: int = 3  # 每道题同时在途的会话上限（司南的线程池大小）；1 即串行
    renew_s: float = 60.0
    stall_s: float = 120.0
    # 运维（P2-3）。log：level（debug|info|warning|error）、format（stderr 的格式 json|text）、
    # file（相对 home；空串即不写文件）、access（HTTP 访问日志，缺省关）
    log: dict = field(
        default_factory=lambda: {"level": "info", "format": "json", "file": "logs/stack.log", "access": False}
    )

    @classmethod
    def load(cls, home: Path, path: Path | None = None, **over) -> StackConfig:
        """配置文件（YAML）可省：没有就是空配置——假 CLI 后端、没有脚本、Docker 执行层。
        文件里的相对路径相对配置文件所在目录。缺省读 <home>/config.yaml；只有旧的 config.json 时照样读
        （JSON 是 YAML 的子集），两份都在则报错，不猜用哪份。"""
        raw: dict = {}
        if path is None:
            path, old = home / "config.yaml", home / "config.json"
            if old.exists():
                if path.exists():
                    raise ValueError(f"{path} 与 {old} 同时存在；配置已统一为 YAML，请删掉 config.json")
                path = old
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"{path}：配置的顶层必须是映射")
        base = path.parent
        be = raw.get("backend", {})
        if isinstance(be, str):
            be = {"kind": be}
        ex = raw.get("executor", {})
        if isinstance(ex, str):
            ex = {"kind": ex}
        cfg = cls(
            home=home,
            backend=be.get("kind", "fake"),
            scripts={k: str((base / v).resolve()) for k, v in be.get("scripts", {}).items()},
            usage=be.get("usage"),
            **{
                k: be[src]
                for k, src in (
                    ("launcher", "launcher"),
                    ("cli_image", "image"),
                    ("upstream", "upstream"),
                    ("upstream", "api_base"),
                    ("api_key_env", "api_key_env"),
                    ("api_key", "api_key"),
                    ("model", "model"),
                )
                if src in be
            },
            **({"program": _program(be["program"])} if be.get("program") else {}),
            executor=ex.get("kind", "docker"),
            **({"bases": ex["bases"]} if "bases" in ex else {}),
            **{
                k: raw[k]
                for k in ("poll_s", "dog_interval_s", "ttl_s", "renew_s", "stall_s", "max_sessions")
                if k in raw
            },
        )
        lg = raw.get("log", {})
        if not isinstance(lg, dict) or set(lg) - set(cfg.log):
            raise ValueError(f"log 只认 {sorted(cfg.log)} 这几项")
        cfg.log = {**cfg.log, **lg}
        for k, v in over.items():
            if v is not None:
                setattr(cfg, k, v)
        return cfg

    def log_file(self) -> Path | None:
        f = self.log.get("file")
        return (self.home / f) if f else None


class StackError(RuntimeError):
    pass


def _program(v: object) -> tuple:
    """backend.program：字符串按 shell 规则切分（可带参数），列表原样。"""
    if isinstance(v, str):
        return tuple(shlex.split(v))
    if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
        return tuple(v)
    raise StackError(f"backend.program 取字符串或字符串列表，不是 {v!r}")


def docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


# ---------- 组装 ----------


class Stack:
    def __init__(self, cfg: StackConfig):
        if cfg.backend not in ("fake", "real"):
            raise StackError(f"会话后端取 fake 或 real，不是 {cfg.backend!r}")
        self.launch_mode = cfg.launcher or ("container" if cfg.backend == "real" else "local")
        if self.launch_mode not in ("container", "local"):
            raise StackError(f"launcher 取 container 或 local，不是 {cfg.launcher!r}")
        api_key = "sk-fake-upstream"
        if cfg.backend == "real":
            api_key = os.environ.get(cfg.api_key_env, "")
            if not api_key and cfg.api_key:
                api_key = cfg.api_key
                log("stack").warning(
                    "模型密钥取自配置文件的 backend.api_key（环境变量 %s 没有设）：配置文件请只给自己读",
                    cfg.api_key_env,
                )
            if not api_key:
                raise StackError(
                    f"真实后端要模型密钥：环境变量 {cfg.api_key_env} 没有设，配置里也没有 backend.api_key。"
                    "密钥只交给端点代理，不进任何容器"
                )
            if self.launch_mode == "container" and not cfg.cli_image:
                raise StackError("真实后端在模型容器里起 CLI：配置里要给 backend.image（装有该 CLI 的镜像）")
        if self.launch_mode == "container" and not docker_available():
            raise StackError("模型容器要 Docker，但 docker info 失败。先起 dockerd")
        if cfg.executor not in ("docker", "none"):
            raise StackError(f"执行层取 docker 或 none，不是 {cfg.executor!r}")
        if cfg.executor == "docker" and not docker_available():
            raise StackError(
                '执行层要 Docker，但 docker info 失败。先起 dockerd，或在配置里写 "executor": "none"（没有 exec，只适合看界面）'  # noqa: E501
            )
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.beats: dict[str, dict] = {}  # 各循环的心跳：最近一轮的时刻与最近一次失败（/healthz 读）
        self._docker_probe = (0.0, True)
        self.workers: dict[str, threading.Thread] = {}
        self.crashed: list[dict] = []  # 因缺陷退出的组件线程（_thread_died 记下）
        self._prev_hook = threading.excepthook
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
        self.tok = {
            k: self.tokens.issue({"kind": k, "id": f"{k[:2]}1"})
            for k in ("sinan", "judge", "adapter", "executor", "watchdog")
        }

        # 图服务
        self.registry = load_registry()
        self.judges = kernel_judges(self.registry)
        self.graph = GraphService(home / "g.sqlite", Config(judges=self.judges), self.tokens)
        self.blobs = BlobStore(home / "blobs")
        self.http = GraphHttp(
            self.graph,
            self.blobs,
            HttpConfig(
                port=cfg.port,
                allowed_origins=tuple(cfg.allow_origins),
                static_dir=cfg.static_dir,
                heartbeat_s=5.0,
                health=self.health,
                access_log=bool(cfg.log.get("access")),
            ),
        )
        self.vault = Vault(home / "vault")

        # 执行层
        self.executor = (
            DockerExecutor(self.graph, self.blobs, self.tok["executor"], spool_dir=str(home / "spool"))
            if cfg.executor == "docker"
            else None
        )

        # Adapter：上游（假上游或真模型端点）→ 端点代理 → 工具端点 → 会话运行器
        real = cfg.backend == "real"
        self.upstream = None if real else FakeUpstream(cfg.usage)
        self.upstream_url = cfg.upstream if real else self.upstream.url
        self.proxy = EndpointProxy(
            ProxyConfig(self.upstream_url, api_key, self.tok["adapter"]),
            PriceTable.load(PRICES),
            self.graph,
            reader=self.graph,
        )
        if self.proxy.restored["global"]:
            log("adapter").info(
                "端点代理从账本恢复累计花费：全局 %d 毫美元，%d 道题",
                self.proxy.restored["global"],
                sum(1 for v in self.proxy.restored["problems"].values() if v),
            )
        self.endpoint = ToolEndpoint()
        # 端点先起：模型容器的启动器要知道它们在本机回环上的端口
        proxy_port = self.proxy.serve()[1]
        mcp_port = int(self.endpoint.serve().rsplit(":", 1)[1])
        if real:
            self.cfg.scripts = dict.fromkeys(TASK_KINDS, "real")  # 真实后端三类任务都开；这张表只对假 CLI 有意义
            binding = CliBinding(model=cfg.model, **({"program": list(cfg.program)} if cfg.program else {}))
            env_for = None
        else:
            binding = CliBinding(program=fake_program(in_container=self.launch_mode == "container"))
            env_for = lambda lease: {"PD_FAKE_SCRIPT": cfg.scripts.get(lease["kind"], "")}  # noqa: E731
        if self.launch_mode == "container":
            # 假 CLI + 容器：通用镜像里挂进假 CLI 与各类任务的脚本（只读）；真 CLI 的镜像自带 CLI，不挂任何东西
            mounts = (
                ()
                if real
                else (
                    (str(FAKE_CLI), "/opt/paoding/fakecli.py"),
                    *[(v, v) for v in sorted(set(cfg.scripts.values())) if v],
                )
            )
            self.launcher = ContainerLauncher(
                cfg.cli_image or cfg.bases.get("basic", "python:3.12-slim"), proxy_port, mcp_port, mounts=mounts
            )
        else:
            self.launcher = local_launcher
        self.adapter_cfg = AdapterConfig(
            root=home / "sessions",
            renew_s=cfg.renew_s,
            stall_s=cfg.stall_s,
            judges_cfg=self.judges,
            binding=binding,
            bases=dict(cfg.bases),
            env_for=env_for,
        )
        self.runner = SessionRunner(
            self.adapter_cfg,
            self.graph,
            self.graph,
            self.blobs,
            self.tokens,
            self.proxy,
            self.endpoint,
            self.executor,
            launcher=self.launcher,
        )

        # 判官运行器、哮天犬
        self.judge = JudgeRunner(
            JudgeConfig(token=self.tok["judge"], registry=self.registry, bases=dict(cfg.bases)),
            self.graph,
            self.graph,
            self.blobs,
            self.vault,
            self.executor,
        )
        self.dog = Watchdog(
            DogConfig(token=self.tok["watchdog"], interval_s=cfg.dog_interval_s),
            self.graph,
            self.graph,
            control=self.runner,
            sweep=sweep_orphans if self.executor is not None else None,
        )
        self.url = ""

    # ---------- 起 ----------

    def start(self) -> str:
        """按次序起：图服务 → 判官运行器 → 司南 → 哮天犬。返回图服务的地址。"""
        threading.excepthook = self._thread_died
        self.url = self.http.serve()
        log("graph").info(
            "HTTP + SSE 在 %s（链头 seq=%d，题 %d 道；人的令牌在 %s）",
            self.url,
            self.graph.head(),
            len(self.graph.state["problems"]),
            self.cfg.home / "human.token",
        )
        self._spawn("events", self._follow_events)
        self._spawn("judge", self._judge_loop)
        log("judge").info(
            "判官运行器已起：%s", ", ".join(f"{k}@{v['version']}" for k, v in sorted(self.judges.items()))
        )
        self._spawn("sinan", self._sinan_supervisor)
        missing = [k for k in TASK_KINDS if not self.cfg.scripts.get(k)]
        where = "模型容器" if self.launch_mode == "container" else "宿主子进程"
        if self.launch_mode == "local" and self.cfg.backend == "real":
            log("sinan").warning("真 CLI 以宿主子进程运行（launcher: local）：没有模型容器的隔离，只适合本机调试")
        log("sinan").info(
            "司南已起：后端 %s（%s；上游 %s）%s",
            self.cfg.backend,
            where,
            self.upstream_url,
            f"；没有脚本的任务种类不开：{', '.join(missing)}" if missing else "",
        )
        self._spawn("watchdog", self._dog_loop)
        log("watchdog").info(
            "哮天犬已起：每 %.1f 秒一轮%s",
            self.cfg.dog_interval_s,
            "" if self.executor else "（执行层 none，不清扫容器）",
        )
        return self.url

    def _spawn(self, name: str, fn) -> None:
        t = threading.Thread(target=fn, name=name, daemon=True)
        self.threads.append(t)
        t.start()

    def _thread_died(self, a: threading.ExceptHookArgs) -> None:
        """组件线程里没被接住的异常就是缺陷：记下栈与线程名，留在 crashed 里，不吞掉（审计 P1-4）。

        不在线程顶层宽接 Exception：那样缺陷与环境故障混在一起，只剩一行日志。司南的每题线程退出后
        由监管循环按原样重起；判官、哮天犬与事件跟随线程不重起，死了就是死了，看 crashed 与日志。"""
        name = a.thread.name if a.thread is not None else "?"
        if a.exc_type is SystemExit or not any(t is a.thread for t in [*self.threads, *self.workers.values()]):
            self._prev_hook(a)
            return
        self.crashed.append({"thread": name, "error": f"{a.exc_type.__name__}: {a.exc_value}"})
        log(name.split("-", 1)[0]).error(
            "线程因缺陷退出",
            exc_info=(a.exc_type, a.exc_value, a.exc_traceback),
        )

    # ---------- 健康（/healthz）----------

    def _beat(self, name: str, err: BaseException | None = None) -> None:
        b = self.beats.setdefault(name, {"at": 0.0, "error": None, "failures": 0})
        b["at"] = time.monotonic()
        if err is None:
            b["error"] = None
        else:
            b["error"], b["failures"] = f"{type(err).__name__}: {err}"[:300], b["failures"] + 1

    def _loop_health(self, name: str) -> dict:
        """一个后台循环的状态：线程活着、最近一轮没有抛异常，才算好。最近一轮距今多久只作读数，
        不设阈值（判官与会话的一轮可以很长）。"""
        t = next((t for t in self.threads if t.name == name), None)
        b = self.beats.get(name, {})
        alive = bool(t and t.is_alive())
        out = {
            "ok": alive and not b.get("error"),
            "alive": alive,
            "last_tick_age_s": round(time.monotonic() - b["at"], 1) if b.get("at") else None,
        }
        if b.get("error"):
            out["last_error"] = b["error"]
        if b.get("failures"):
            out["failures"] = b["failures"]
        return out

    def _docker_ok(self) -> bool:
        at, ok = self._docker_probe  # docker info 要起子进程：结果留 10 秒
        if time.monotonic() - at > 10:
            ok = docker_available()
            self._docker_probe = (time.monotonic(), ok)
        return ok

    def health(self) -> dict:
        """图服务之外各组件的状态，交给 GET /healthz（图服务自己的那一项由 HTTP 绑定填）。只读，不改任何状态。"""
        if self._stopped or self.stop_event.is_set():
            return {"stack": {"ok": False, "stopping": True}}
        out = {
            "events": self._loop_health("events"),
            "judge": {**self._loop_health("judge"), "judges": len(self.judges)},
            "sinan": {
                **self._loop_health("sinan"),
                "problems_scheduled": sum(1 for t in self.workers.values() if t.is_alive()),
            },
            "watchdog": self._loop_health("watchdog"),
            "adapter": {
                "ok": True,
                "backend": self.cfg.backend,
                "launcher": self.cfg.launcher or None,
                "sessions_in_flight": len(self.runner.live),
            },
        }
        if self.executor is None:
            out["executor"] = {"ok": True, "kind": "none"}
        else:
            ok = self._docker_ok()
            out["executor"] = {"ok": ok, "kind": "docker", **({} if ok else {"last_error": "docker info 失败"})}
        return out

    # ---------- 事件流：每条落盘事件一行日志 ----------

    def _follow_events(self) -> None:
        after = self.graph.head()
        L = log("graph")
        while not self.stop_event.is_set():
            evs = self.graph.events(None, after, limit=200)
            for ev in evs:
                after = ev["seq"]
                L.info(
                    "#%d %s %s ← %s%s",
                    ev["seq"],
                    ev["problem_id"],
                    ev["kind"],
                    _who(ev["actor"]),
                    _gist(ev),
                    extra=ctx(
                        seq=ev["seq"],
                        problem_id=ev["problem_id"],
                        kind=ev["kind"],
                        actor=_who(ev["actor"]),
                        lease_id=_lease_of(ev),
                        request_id=_request_of(ev),
                    ),
                )
            self._beat("events")
            if not evs:
                self.stop_event.wait(0.2)

    # ---------- 判官 ----------

    def _judge_loop(self) -> None:
        L = log("judge")
        while not self.stop_event.is_set():
            try:
                for d in self.judge.tick():
                    L.info(
                        "%s 请求 %s → %s（%s）%s",
                        d.get("status"),
                        d.get("request"),
                        d.get("result", "-"),
                        d.get("reason", d.get("code", "")),
                        "" if d.get("status") == "judged" else d,
                        extra=ctx(request_id=d.get("request"), problem_id=d.get("problem_id")),
                    )
                self._beat("judge")
            except (OSError, subprocess.SubprocessError) as e:  # 环境故障（磁盘、docker 命令）：记下，下一轮照常
                L.exception("tick 失败")
                self._beat("judge", e)
            self.stop_event.wait(self.cfg.poll_s)

    # ---------- 司南：每道未关的题一个循环 ----------

    def _sinan_supervisor(self) -> None:
        while not self.stop_event.is_set():
            for pid, p in sorted(self.graph.state["problems"].items()):
                t = self.workers.get(pid)
                if p.get("closed") or (t is not None and t.is_alive()):
                    continue
                t = threading.Thread(target=self._sinan_loop, args=(pid,), name=f"sinan-{pid}", daemon=True)
                self.workers[pid] = t
                t.start()
            self._beat("sinan")
            self.stop_event.wait(self.cfg.poll_s)

    def _sinan_loop(self, pid: str) -> None:
        """一道题一个司南实例：调度在本线程，会话在它的线程池里并行（至多 max_sessions 个）。"""
        L = log("sinan")
        sinan = Sinan(
            SinanConfig(token=self.tok["sinan"], ttl_s=self.cfg.ttl_s, max_sessions=self.cfg.max_sessions),
            self.graph,
            self.graph,
            self.blobs,
            self.runner,
        )
        last = None
        L.info("%s 开始调度（并发上限 %d）", pid, self.cfg.max_sessions, extra=ctx(problem_id=pid))
        try:
            while not self.stop_event.is_set():
                for r in sinan.collect(0):
                    L.info(
                        "%s %s 会话结束：租约 %s，%s，release=%s%s",
                        pid,
                        r["did"]["kind"],
                        r["lease"],
                        r["status"],
                        r["outcome"],
                        f"（{r['detail']}）" if r.get("detail") else "",
                        extra=ctx(problem_id=pid, lease_id=r["lease"]),
                    )
                    last = None
                choice = sinan.pick(pid)
                if choice.get("stop") == "closed":
                    p = self.graph.state["problems"][pid]
                    L.info("%s 已关题，终态 %s", pid, p.get("terminal"), extra=ctx(problem_id=pid))
                    return
                if "do" in choice and not self.cfg.scripts.get(choice["do"]["kind"]):
                    note = f"没有 {choice['do']['kind']} 的会话后端（假 CLI 脚本），等配置"
                else:
                    r = sinan.dispatch(pid) if "do" in choice else choice
                    if "started" in r:
                        w = r["started"]
                        L.info(
                            "%s %s 会话开始：租约 %s%s（在途 %d）",
                            pid,
                            w["kind"],
                            r["lease"],
                            f" → {w['target']}" if w.get("target") else "",
                            len(sinan.in_flight()),
                            extra=ctx(problem_id=pid, lease_id=r["lease"]),
                        )
                        last = None
                        continue  # 还有空位就接着开下一项
                    note = _note(r)
                if note != last:
                    L.info("%s %s", pid, note, extra=ctx(problem_id=pid))
                    last = note
                if sinan.in_flight():
                    sinan.collect(self.cfg.poll_s)  # 有会话跑完就立刻醒
                else:
                    self.stop_event.wait(self.cfg.poll_s)
        finally:
            # 关题时还在途的会话（并行的另一条路线已把题解掉）：叫停，不让它在已关的题上继续花钱。
            # 停机时 stop() 已经叫停过。两种情况都等它们收尾并各记一行，最多等 30 秒。
            if not self.stop_event.is_set():
                for f in sinan.in_flight():
                    L.info(
                        "%s 已关题，叫停在途会话：租约 %s",
                        pid,
                        f["lease"],
                        extra=ctx(problem_id=pid, lease_id=f["lease"]),
                    )
                    self.runner.kill(f["lease"], "problem_closed")
            deadline = time.monotonic() + 30
            while sinan.in_flight() and time.monotonic() < deadline:
                for r in sinan.collect(self.cfg.poll_s):
                    L.info(
                        "%s %s 会话结束：租约 %s，%s，release=%s",
                        pid,
                        r["did"]["kind"],
                        r["lease"],
                        r["status"],
                        r["outcome"],
                        extra=ctx(problem_id=pid, lease_id=r["lease"]),
                    )
            sinan.close()

    # ---------- 哮天犬 ----------

    def _dog_loop(self) -> None:
        L = log("watchdog")
        while not self.stop_event.is_set():
            try:
                r = self.dog.tick()
                for k in ("expired", "soft", "killed", "closed", "swept", "alerts"):
                    if getattr(r, k):
                        L.info("%s: %s", k, getattr(r, k))
                self._beat("watchdog")
            except (OSError, subprocess.SubprocessError) as e:  # 环境故障（磁盘、docker 命令）：记下，下一轮照常
                L.exception("tick 失败")
                self._beat("watchdog", e)
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
        if self.launch_mode == "container":
            self.launcher.close()
        self.endpoint.close()
        self.proxy.close()
        if self.upstream is not None:
            self.upstream.close()
        self.http.close()
        if threading.excepthook == self._thread_died:
            threading.excepthook = self._prev_hook
        L.info("已停：链头 seq=%d", self.graph.head())
        if self.crashed:
            L.error("有组件线程因缺陷退出：%s", self.crashed)


def _who(actor: dict) -> str:
    return actor["kind"] + (f"/{actor['role']}" if actor.get("role") else "")


def _lease_of(ev: dict) -> str | None:
    b = ev.get("body") or {}
    if ev["kind"] == "lease":
        return f"l_{ev['seq']}"  # 租约 id 由签发它的事件序号派生（reducer 的 apply）
    v = b.get("lease")
    return v if isinstance(v, str) else None


def _request_of(ev: dict) -> str | None:
    b = ev.get("body") or {}
    if ev["kind"] == "request_judge":
        return f"j_{ev['seq']}"  # 同上：判定请求的 id
    v = b.get("request")
    return v if isinstance(v, str) else None


def _gist(ev: dict) -> str:
    b = ev.get("body") or {}
    k = ev["kind"]
    if k == "lease":
        return f"（{b.get('kind')}{' → ' + b['target'] if b.get('target') else ''}，预留 {b.get('reserve', {}).get('usd_milli')} 毫美元）"  # noqa: E501
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
        return f"等待：{r['wait']}" + ("（并发上限已满）" if r["wait"] == "capacity" else "")
    why = r.get("stop")
    if why == "needs_human":
        return f"需要人：{[i.get('target') for i in r.get('items', [])]}"
    if why == "idle":
        return "没有可做的事，等新事件（Hint、审批或判定）"
    return f"停：{why} {r.get('detail', '')}".rstrip()


def default_static() -> Path | None:
    d = ROOT / "web" / "dist"
    return d if (d / "index.html").is_file() else None
