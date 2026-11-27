"""模型容器的启动器（§3.4.2；审计 P0-2）：CLI 在 Docker 容器里跑，不在宿主上跑。

每个会话（租约）一套三样东西，会话结束时一并拆掉：

    内部网络  pd-model-<实例>-<租约>-net   `--internal`，隔离网关：没有出站路由，也到不了宿主
    端点中继  pd-model-<实例>-<租约>-ep    网络别名 pd-endpoints；8081 → 端点代理，8082 → 工具端点（见 relay.py）
    模型容器  pd-model-<实例>-<租约>       CLI 镜像；只挂工作区、会话目录（只读）与它自己的 HOME

<实例> 是这个启动器自己的一段随机标记。租约 id 由各实例自己的事件序号派生（l_1、l_2……），同一台机器上
两个实例的租约会同号；名字里只有租约的话，后起的那个会把先起的那个的网络、中继与模型容器拆掉。

模型容器的出站因此只有两处：工具端点与模型端点代理（规格 §3.4.2“出站只放行工具端点与模型端点代理”）。
它不在执行容器的网络上，所以连不到授权范围内的目标；执行容器也不在这张网络上，连不到模型端点（3.6.4 的 4）。
容器里只有任务令牌（ANTHROPIC_API_KEY）与中继地址（ANTHROPIC_BASE_URL），真实密钥只在端点代理进程里。

中继到 Adapter 进程之间有两种通路（`transport`），端点代理与工具端点都仍只监听本机回环：

- `unix`（Linux 缺省）：Adapter 在一个短路径目录里开两个 Unix 套接字（UnixBridge），只读挂进中继；
- `tcp`（macOS 缺省）：Docker Desktop 的容器跑在虚拟机里，挂进去的 Unix 套接字连不通（连上就被重置）。
  中继另接默认网桥，经 `host.docker.internal` 连宿主回环上的两个端点（Docker Desktop 把它转到宿主的本机回环），
  与评测台 baseline 的做法相同（eval/box.py）。模型容器始终只在内部网络上，`host.docker.internal` 只加给中继。

中继起来后先从中继里探一遍上游（两个套接字，或宿主上的两个端口）：连不上就在开会话之前报 LaunchError，
而不是等 CLI 或驱动程序第一次调工具时才被重置。
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from . import backend as be
from .relay import accept_loop
from .session import stderr_file

RELAY_ALIAS = "pd-endpoints"
PROXY_PORT, MCP_PORT = 8081, 8082
WORKSPACE, SESSION, HOME = "/workspace", "/session", "/home/pd"
# 与执行层同一套标签约定（executor/SPEC.md）：进程异常退出后，哮天犬的孤儿清扫按属主回收容器与网络
LABEL, OWNER, LEASE, ROLE = "paoding.sandbox", "paoding.owner", "paoding.lease", "paoding.role"
ISOLATED = "com.docker.network.bridge.gateway_mode_ipv4=isolated"
RELAY_SCRIPT = Path(__file__).with_name("relay.py")  # 中继脚本；评测台的 baseline 也挂它
HOST_ALIAS = "host.docker.internal"  # tcp 通路：中继里宿主的名字（--add-host …:host-gateway）
TRANSPORTS = ("unix", "tcp")


def default_transport() -> str:
    """macOS（Docker Desktop）上 Unix 套接字挂不进容器，走 tcp；其余走 unix。"""
    return "tcp" if sys.platform == "darwin" else "unix"


class LaunchError(RuntimeError):
    pass


def _docker(*args: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess[Any]:
    p = subprocess.run(["docker", *args], capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        raise LaunchError(f"docker {args[0]} 失败：{p.stderr.decode('utf-8', 'replace').strip()[-400:]}")
    return p


def _owner() -> str:
    """<主机名>:<pid>:<进程启动时刻>，与执行层的属主标签同形。"""
    try:
        started = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except OSError:
        started = "?"
    return f"{socket.gethostname()}:{os.getpid()}:{started}"


class UnixBridge:
    """Unix 套接字 → 本机回环上的一个端口。中继容器经挂载进去的套接字连到这里。"""

    def __init__(self, path: Path, port: int):
        self.path, self.port = path, port
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(str(path))
        path.chmod(0o600)
        self.srv.listen(64)
        threading.Thread(target=accept_loop, args=(self.srv, self._connect), daemon=True).start()

    def _connect(self) -> socket.socket:
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.settimeout(None)  # 超时只管建连：流式响应可以很久没有字节
        return s

    def close(self) -> None:
        try:
            self.srv.shutdown(socket.SHUT_RDWR)  # 叫醒卡在 accept 里的线程
        except OSError:
            pass
        self.srv.close()
        self.path.unlink(missing_ok=True)


class ContainerProc:
    """模型容器的一轮 CLI。对会话运行器而言与 subprocess.Popen 同形（stdout、poll、wait），
    另给出 interrupt / terminate：信号发给容器里的 CLI，而不是只发给宿主上的 docker 客户端。"""

    def __init__(self, name: str, popen: subprocess.Popen[Any]):
        self.name, self._p = name, popen
        self.stdout, self.pid = popen.stdout, popen.pid

    def poll(self) -> int | None:
        return self._p.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._p.wait(timeout)

    def interrupt(self) -> None:
        """软线：SIGINT 结束当前回合。"""
        if self._p.poll() is None:
            _docker("kill", "--signal", "INT", self.name, check=False)

    def terminate(self) -> None:
        """终止：SIGTERM，5 秒不退再 SIGKILL（docker stop），然后确保容器不在了。"""
        if self._p.poll() is None:
            _docker("stop", "--time", "5", self.name, check=False, timeout=30)
        _docker("rm", "-f", "-v", self.name, check=False)
        try:
            self._p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._p.kill()


class ContainerLauncher:
    """SessionRunner 的 launcher。proxy_port 与 mcp_port 是端点代理与工具端点在本机回环上的端口。

    mounts：额外的只读挂载 (宿主路径, 容器路径)，例如测试里把假 CLI 挂进通用镜像。
    env_paths：环境变量里出现的宿主路径若在某个挂载之下，换成容器内的路径（argv 同样处理）。
    """

    def __init__(
        self,
        image: str,
        proxy_port: int,
        mcp_port: int,
        *,
        relay_image: str = "python:3.12-slim",
        mounts: tuple[Any, ...] = (),
        sock_dir: Path | None = None,
        memory: str = "2g",
        pids: int = 512,
        transport: str = "",
        host_ports: tuple[int, int] | None = None,
        instance: str = "",
    ):
        """transport：中继到 Adapter 的通路，`unix` 或 `tcp`，缺省按平台（default_transport）。
        host_ports：tcp 通路下中继在 host.docker.internal 上要连的两个端口（端点代理、工具端点）；缺省就是
        proxy_port、mcp_port（Docker Desktop 把 host.docker.internal 转到宿主的本机回环）。
        instance：名字里的实例标记，缺省随机取；同一台机器上的各个启动器必须互不相同。"""
        if not shutil.which("docker"):
            raise LaunchError("模型容器要 Docker，但找不到 docker 命令")
        self.transport = transport or default_transport()
        if self.transport not in TRANSPORTS:
            raise LaunchError(f"transport 取 unix 或 tcp，不是 {self.transport!r}")
        self.image, self.relay_image, self.mounts = image, relay_image, tuple(mounts)
        self.memory, self.pids = memory, pids
        self.owner = _owner()
        self.instance = instance or secrets.token_hex(4)
        if not self.instance.isalnum():
            raise LaunchError(f"instance 只取字母与数字，不是 {self.instance!r}")
        self.user = f"{os.getuid()}:{os.getgid()}"  # 容器内与 Adapter 同一 uid：工作区文件的属主一致
        self.host_ports = host_ports or (proxy_port, mcp_port)
        self._own_sock_dir = False
        self._bridges: list[UnixBridge] = []
        if self.transport == "unix":
            # 套接字路径有上限（Linux 108 字节、macOS 104 字节），所以放在短路径下，不放数据目录里
            self._own_sock_dir = sock_dir is None
            self.sock_dir = Path(sock_dir or tempfile.mkdtemp(prefix="pd-ep-"))
            self.sock_dir.chmod(0o700)
            self._bridges = [
                UnixBridge(self.sock_dir / "proxy.sock", proxy_port),
                UnixBridge(self.sock_dir / "mcp.sock", mcp_port),
            ]
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._isolated: bool | None = None  # 这台 Docker 认不认隔离网关（27.1 起）

    # ---------- 会话运行器读的两个地址：模型容器里看到的端点 ----------

    @property
    def proxy_url(self) -> str:
        return f"http://{RELAY_ALIAS}:{PROXY_PORT}"

    @property
    def mcp_base(self) -> str:
        return f"http://{RELAY_ALIAS}:{MCP_PORT}"

    def names(self, lease_id: str) -> dict[str, Any]:
        """这个启动器给一个租约起的三个名字。带实例标记：别的实例的同号租约不会落到同一个名字上。"""
        base = f"pd-model-{self.instance}-" + lease_id.replace("_", "-")
        return {"model": base, "relay": base + "-ep", "net": base + "-net"}

    # ---------- 每个会话一张内部网络 + 一个中继 ----------

    def _ensure(self, lease_id: str) -> dict[str, Any]:
        with self._lock:
            s = self._sessions.get(lease_id)
        if s is not None:
            return s
        n = self.names(lease_id)
        labels = [
            "--label",
            f"{LABEL}={n['model']}",
            "--label",
            f"{OWNER}={self.owner}",
            "--label",
            f"{LEASE}={lease_id}",
        ]
        try:
            self._network(n["net"], labels)
            if self.transport == "unix":
                way = ["--mount", f"type=bind,src={self.sock_dir},dst=/run/pd,readonly"]
                ups = ("/run/pd/proxy.sock", "/run/pd/mcp.sock")
            else:
                way = ["--add-host", f"{HOST_ALIAS}:host-gateway"]
                ups = (f"tcp:{HOST_ALIAS}:{self.host_ports[0]}", f"tcp:{HOST_ALIAS}:{self.host_ports[1]}")
            _docker(
                "create",
                "--name",
                n["relay"],
                *labels,
                "--label",
                f"{ROLE}=endpoints",
                "--network",
                n["net"],
                "--network-alias",
                RELAY_ALIAS,
                "--user",
                self.user,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--read-only",
                "--pids-limit",
                "256",
                "--memory",
                "128m",
                *way,
                "--mount",
                f"type=bind,src={RELAY_SCRIPT},dst=/opt/paoding/relay.py,readonly",
                self.relay_image,
                "python",
                "-I",
                "/opt/paoding/relay.py",
                f"{PROXY_PORT}={ups[0]}",
                f"{MCP_PORT}={ups[1]}",
            )
            if self.transport == "tcp":  # 中继另一只脚接默认网桥去找宿主；模型容器不在这张网上
                _docker("network", "connect", "bridge", n["relay"])
            _docker("start", n["relay"])
            self._probe(n["relay"], ups)
        except BaseException:
            self._teardown(n)
            raise
        with self._lock:
            self._sessions[lease_id] = n
        return n

    @staticmethod
    def _probe(relay: str, ups: tuple[str, ...]) -> None:
        """从中继里探：先等它自己的两个端口听上，再对每个上游走一个来回（发一个 GET、要收到应答的头一个字节；
        两个上游都是 HTTP 服务）。只建连不够：Docker Desktop 上挂进去的 Unix 套接字有时连得上、一发数据就被重置。
        上游不通（那种套接字、tcp 通路上宿主的端口没开或被挡）在这里就报出来，
        不留到会话里变成“Connection reset by peer”。"""
        probe = (
            "import socket,sys,time\n"
            f"ups={list(ups)!r}\n"
            "def up(u):\n"
            "    if u.startswith('tcp:'):\n"
            "        _, h, p = u.split(':')\n"
            "        return socket.create_connection((h, int(p)), 3)\n"
            "    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(3); s.connect(u); return s\n"
            "for _ in range(100):\n"
            "    try:\n"
            f"        [socket.create_connection(('127.0.0.1', p), 1).close() for p in ({PROXY_PORT}, {MCP_PORT})]\n"
            "        break\n"
            "    except OSError:\n"
            "        time.sleep(0.05)\n"
            "else:\n"
            "    print('relay not listening'); sys.exit(1)\n"
            "for u in ups:\n"
            "    try:\n"
            "        c = up(u); c.sendall(b'GET / HTTP/1.0\\r\\nHost: pd\\r\\n\\r\\n')\n"
            "        if not c.recv(1):\n"
            "            raise OSError('closed without a reply')\n"
            "        c.close()\n"
            "    except OSError as e:\n"
            "        print(f'{u}: {e}'); sys.exit(2)\n"
        )
        p = _docker("exec", relay, "python", "-I", "-c", probe, check=False)
        if p.returncode == 0:
            return
        said = p.stdout.decode("utf-8", "replace").strip()
        if p.returncode == 2:
            raise LaunchError(
                f"端点中继连不到宿主上的端点（{said}）。macOS 的 Docker Desktop 上要走 tcp 通路"
                "（配置 backend.transport: tcp，缺省按平台选）；Linux 上检查 Unix 套接字目录的权限"
            )
        logs = _docker("logs", "--tail", "20", relay, check=False)
        raise LaunchError(f"端点中继未就绪：{said} {(logs.stdout + logs.stderr).decode('utf-8', 'replace')[-400:]}")

    def _network(self, net: str, labels: list[str]) -> None:
        """`--internal` 且隔离网关：容器既没有出站路由，也到不了宿主在网桥上的地址。
        老版本 Docker 不认隔离网关时退回普通的 `--internal`（仍无出站；宿主上监听全部接口的服务可达）。"""
        if self._isolated is not False:
            p = _docker("network", "create", "--internal", "-o", ISOLATED, *labels, net, check=False)
            if p.returncode == 0:
                self._isolated = True
                return
            if self._isolated:  # 之前成功过：这次是别的毛病
                raise LaunchError(f"建网络失败：{p.stderr.decode('utf-8', 'replace').strip()[-400:]}")
            self._isolated = False
            _docker("network", "rm", net, check=False)
        _docker("network", "create", "--internal", *labels, net)

    def _teardown(self, n: dict[str, Any]) -> None:
        _docker("rm", "-f", "-v", n["model"], n["relay"], check=False)
        _docker("network", "rm", n["net"], check=False)

    # ---------- launcher 接口 ----------

    def __call__(self, argv: list[str], env: dict[str, Any], cwd: Path) -> ContainerProc:
        """cwd 是会话的工作区 <会话目录>/workspace；会话目录名就是租约 id。"""
        workspace = Path(cwd)
        sdir = workspace.parent
        lease_id = sdir.name
        n = self._ensure(lease_id)
        _docker("rm", "-f", "-v", n["model"], check=False)  # 收尾轮复用同一个名字
        table: list[tuple[str, str]] = [
            (str(workspace), WORKSPACE),
            (str(sdir / "home"), HOME),
            (str(sdir), SESSION),
            *[(str(src), str(dst)) for src, dst in self.mounts],
        ]
        table.sort(key=lambda kv: -len(kv[0]))  # 最长前缀优先

        def inside(v: str) -> str:
            for src, dst in table:
                if v == src or v.startswith(src + "/"):
                    return dst + v[len(src) :]
            return v

        cmd = be.container_argv(
            self.image,
            n["model"],
            n["net"],
            workspace,
            sdir,
            [inside(a) for a in argv],
            {k: inside(str(v)) for k, v in env.items()},
            home=sdir / "home",
            user=self.user,
            labels={LABEL: n["model"], OWNER: self.owner, LEASE: lease_id, ROLE: "model"},
            mounts=self.mounts,
            memory=self.memory,
            pids=self.pids,
        )
        with stderr_file(cwd) as err:  # docker run 的 stderr：容器里 CLI 的 stderr 与 docker 自己的报错
            popen = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL, start_new_session=True
            )
        return ContainerProc(n["model"], popen)

    def release(self, lease_id: str) -> None:
        """会话结束：拆掉模型容器、中继与网络。幂等。"""
        with self._lock:
            n = self._sessions.pop(lease_id, None)
        self._teardown(n or self.names(lease_id))

    def close(self) -> None:
        with self._lock:
            leases = list(self._sessions)
        for lid in leases:
            self.release(lid)
        for b in self._bridges:
            b.close()
        if self._own_sock_dir:
            shutil.rmtree(self.sock_dir, ignore_errors=True)
