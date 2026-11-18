"""baseline 的运行环境（两臂环境对等）：CLI 在执行层同款的沙箱里跑，经出站闸门只连得到授权目标。

full 模式里，模型的命令经代理工具 exec 落到执行容器，执行容器所在的内部网络上每台授权主机一个闸门，
只放行 scope 里 actions 含 connect 的 host:port。baseline 必须面对同一个环境，否则对照量到的是网络差异，
不是能力差异（M1 第一批读数的教训：CLI 在宿主上跑，解析不了题目容器的名字，三次全败）。

所以 baseline 直接借执行层：
- `compile_spec` 把题目的 scope 编成 ExecSpec（风险上限 r1、r2 不批准：与 full 里没有人批准时相同）；
- `DockerExecutor.launch` 建内部网络、沙箱容器（镜像换成装有 CLI 的镜像）和逐主机闸门；
- 再在这张网络上放一个端点中继（别名 pd-endpoints），CLI 经它连宿主上的端点代理，计量照旧（红线 5）；
- CLI 用 `docker exec` 在沙箱里起，工具面是原生的（含 Bash），工作区挂在 /workspace。

中继到端点代理的通路：Linux 上走挂进去的 Unix 套接字（与模型容器相同）；Docker Desktop（macOS）上
Unix 套接字挂不进容器，中继另接默认网桥，经 host.docker.internal 连宿主回环上的代理。模型所在的
沙箱网络始终是内部网络，模型自己出不去。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from paoding_adapter.contract import PROXY_PORT, RELAY_ALIAS, RELAY_SCRIPT, UnixBridge
from paoding_executor.contract import DockerExecutor, Limits, compile_spec, gate_log

LABEL, OWNER, ROLE = "paoding.sandbox", "paoding.owner", "paoding.role"
RELAY_IMAGE = "python:3.12-slim"
WORKSPACE = "/workspace"
HOME = "/tmp/pd-home"
PD_DIR = "/tmp/pd"  # 运行器拷进沙箱的东西（MCP 空配置、假 CLI）放这里，不进工作区


def _docker(*args: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess[bytes]:
    p = subprocess.run(["docker", *args], capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"docker {args[0]} 失败：{p.stderr.decode('utf-8', 'replace').strip()[-400:]}")
    return p


def default_transport() -> str:
    return "tcp" if sys.platform == "darwin" else "unix"


class BaselineBox:
    """一次 baseline 运行的沙箱。用法：

        with BaselineBox(scope, image, workspace, proxy_port) as box:
            box.copy_in(本机文件, 沙箱内路径)
            proc = box.exec(argv, env, timeout_s)
            box.connects()  # 闸门上的连接记录

    退出时拆掉沙箱、闸门、中继与网络；题目容器只摘网，不删。"""

    def __init__(
        self,
        scope: list[dict[str, Any]],
        image: str,
        workspace: Path,
        proxy_port: int,
        *,
        name: str = "",
        wall_s: int = 900,
        transport: str = "",
        relay_image: str = RELAY_IMAGE,
    ):
        if not shutil.which("docker"):
            raise RuntimeError("baseline 的真题运行要 Docker（CLI 在沙箱里跑），但找不到 docker 命令")
        self.scope, self.image, self.workspace = scope, image, Path(workspace)
        self.proxy_port, self.wall_s, self.relay_image = proxy_port, wall_s, relay_image
        self.transport = transport or default_transport()
        if self.transport not in ("unix", "tcp"):
            raise ValueError(f"transport 只能是 unix 或 tcp：{self.transport!r}")
        self.name = (name or uuid.uuid4().hex[:8]).replace("_", "-")
        self.user = f"{os.getuid()}:{os.getgid()}"  # 与宿主同一 uid：工作区里写出的文件属主一致
        self.sid = ""
        self.relay = ""
        self._ex = DockerExecutor(None, None, "")  # type: ignore[arg-type]  # 只用 launch/destroy，不登记产物
        self._bridge: UnixBridge | None = None
        self._sock_dir: Path | None = None

    # ---------- 生命周期 ----------

    def __enter__(self) -> BaselineBox:
        try:
            self._launch()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _launch(self) -> None:
        spec = compile_spec(
            f"eval-{self.name}",
            self.scope,
            {"base": self.image, "baseline_ref": "eval-baseline"},
            "r1",
            False,
            str(self.workspace),
            Limits(cpu=2.0, mem_mb=2048, pids=512, wall_s=self.wall_s),
        )
        self.sid = self._ex.launch(spec, lease_id=f"eval-{self.name}")
        net = f"{self.sid}-net"
        self.relay = f"{self.sid}-ep"
        labels = ["--label", f"{LABEL}={self.sid}", "--label", f"{ROLE}=endpoints"]
        if self.transport == "unix":
            self._sock_dir = Path(tempfile.mkdtemp(prefix="pd-eval-"))  # 套接字路径有长度上限，放短路径
            self._sock_dir.chmod(0o700)
            self._bridge = UnixBridge(self._sock_dir / "proxy.sock", self.proxy_port)
            mount = ["--mount", f"type=bind,src={self._sock_dir},dst=/run/pd,readonly", "--user", self.user]
            target = "/run/pd/proxy.sock"
            extra: list[str] = []
        else:
            mount, target = [], f"tcp:host.docker.internal:{self.proxy_port}"
            extra = ["--add-host", "host.docker.internal:host-gateway"]
        _docker(
            "create",
            "--name",
            self.relay,
            *labels,
            "--network",
            net,
            "--network-alias",
            RELAY_ALIAS,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--pids-limit",
            "256",
            "--memory",
            "128m",
            *extra,
            *mount,
            "--mount",
            f"type=bind,src={RELAY_SCRIPT},dst=/opt/paoding/relay.py,readonly",
            self.relay_image,
            "python",
            "-I",
            "/opt/paoding/relay.py",
            f"{PROXY_PORT}={target}",
        )
        if self.transport == "tcp":  # 中继另一只脚接默认网桥去找宿主；沙箱本身不在这张网上
            _docker("network", "connect", "bridge", self.relay)
        _docker("start", self.relay)
        probe = (
            "import socket,sys,time\n"
            "for _ in range(100):\n"
            "    try:\n"
            f"        socket.create_connection(('127.0.0.1', {PROXY_PORT}), 1).close(); sys.exit(0)\n"
            "    except OSError:\n"
            "        time.sleep(0.05)\n"
            "sys.exit(1)\n"
        )
        if _docker("exec", self.relay, "python", "-I", "-c", probe, check=False).returncode != 0:
            logs = _docker("logs", "--tail", "20", self.relay, check=False)
            raise RuntimeError(f"端点中继未就绪：{(logs.stdout + logs.stderr).decode('utf-8', 'replace')[-400:]}")
        _docker("exec", "-u", "0", self.sid, "sh", "-c", f"mkdir -p {HOME} {PD_DIR} && chmod 777 {HOME} {PD_DIR}")

    def close(self) -> None:
        if self.relay:
            _docker("rm", "-f", "-v", self.relay, check=False)
        if self.sid:
            self._ex.destroy(self.sid)
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None
        if self._sock_dir is not None:
            shutil.rmtree(self._sock_dir, ignore_errors=True)
            self._sock_dir = None

    # ---------- 用 ----------

    @property
    def proxy_url(self) -> str:
        return f"http://{RELAY_ALIAS}:{PROXY_PORT}"

    def copy_in(self, src: Path, dst: str) -> None:
        _docker("cp", str(src), f"{self.sid}:{dst}")
        _docker("exec", "-u", "0", self.sid, "chmod", "a+r", dst)

    def exec_argv(self, argv: list[str], env: dict[str, str]) -> list[str]:
        out = ["docker", "exec", "-u", self.user, "-w", WORKSPACE]
        for k, v in sorted(env.items()):
            out += ["-e", f"{k}={v}"]
        return [*out, self.sid, *argv]

    def connects(self) -> list[dict[str, Any]]:
        """各闸门上的连接记录（connect / deny），按时间排。用来核对 baseline 确实碰到了目标。"""
        ps = _docker(
            "ps",
            "-a",
            "--filter",
            f"label={LABEL}={self.sid}",
            "--filter",
            f"label={ROLE}=gate",
            "--format",
            "{{.Names}}",
            check=False,
        )
        gates = sorted(n for n in ps.stdout.decode().split() if n)
        recs = [r for g in gates for r in gate_log(g) if r.get("event") in ("connect", "deny")]
        return sorted(recs, key=lambda r: r.get("t", 0))


def write_connects(box: BaselineBox, path: Path) -> int:
    recs = box.connects()
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs), encoding="utf-8")
    return sum(1 for r in recs if r.get("event") == "connect" and r.get("ok"))
