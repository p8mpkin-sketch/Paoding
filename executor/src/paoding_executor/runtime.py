"""执行层运行时（§3.6.2）：Docker 容器、出站白名单、exec 的容器外采集与登记。

隔离（M0）：
- 每个沙箱一张 `--internal` 的 Docker 网络，没有出站路由；只把授权范围编译出的目标容器接进来。
  所以执行容器只能连到白名单里的本机靶场容器，连不到模型端点，也连不到外网（3.6.4 的 1、4）。
- 容器 `--cap-drop ALL`、`no-new-privileges`、资源上限；不传任何环境变量，不挂任何密钥。
- 工作区是唯一的可写挂载；判官的洁净容器不挂 Worker 的工作区（3.6.4 的 3）。

采集：命令在容器里运行，标准输出与标准错误（合并以保序）由本进程在容器之外读取，
写入 Blob 仓库，再用执行层的组件令牌登记为 exec 类。模型拿到的是 ArtifactId 和截断回显。
"""
from __future__ import annotations

import os
import shlex
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from paoding_graph.contract import BlobPort, GraphPort

from .compile import ExecSpec, ScopeError

ECHO_LIMIT = 8 * 1024                  # 回显上限 8 KB，超过只回头尾（§3.4.2）
MAX_CAPTURE = 256 * 1024 * 1024        # 单个 Blob 上限；超过保留头尾并置 truncated（§3.2.2）
LABEL = "paoding.sandbox"
OWNER = "paoding.owner"                 # 属主：<主机名>:<pid>:<进程启动时刻>，孤儿清扫只清属主已不存活的


def _start_time(pid: int) -> str | None:
    """进程启动时刻（/proc/<pid>/stat 第 22 字段）。和 pid 一起判断存活，防 pid 复用。"""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return raw.rsplit(")", 1)[1].split()[19]


def owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{_start_time(os.getpid())}"


def owner_alive(owner: str) -> bool | None:
    """True/False：本机属主是否存活；None：不是本机的属主或格式不明，不由本机判断。"""
    try:
        host, pid, started = owner.rsplit(":", 2)
        pid_i = int(pid)
    except ValueError:
        return None
    if host != socket.gethostname():
        return None
    return _start_time(pid_i) == started


@dataclass
class ExecResult:
    artifact: str | None              # 登记后的 ArtifactId；judge 模式下为 None，由判官运行器登记
    blob: str
    exit_code: int | None
    output: str                       # 截断后的回显
    truncated: bool                   # 回显或采集是否截断
    provenance: dict                  # exec 出处字段（§3.2.2），judge 模式下交给判官运行器


def _docker(*args: str, check: bool = True, timeout: float | None = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, check=check, timeout=timeout)


def echo(data: bytes, limit: int = ECHO_LIMIT) -> tuple[str, bool]:
    if len(data) <= limit:
        return data.decode("utf-8", "replace"), False
    half = limit // 2
    skipped = len(data) - 2 * half
    text = (data[:half].decode("utf-8", "replace") + f"\n…[省略 {skipped} 字节，用 show 按区间读全文]…\n"
            + data[-half:].decode("utf-8", "replace"))
    return text, True


class DockerExecutor:
    def __init__(self, graph: GraphPort, blobs: BlobPort, token: str):
        self.graph, self.blobs, self.token = graph, blobs, token
        self.owner = owner_id()
        self._live: dict[str, dict] = {}

    # ---------- 生命周期 ----------

    def launch(self, spec: ExecSpec, lease_id: str, mount_workspace: bool = True) -> str:
        sid = f"pd-{spec.id}-{uuid.uuid4().hex[:8]}"
        net = f"{sid}-net"
        _docker("network", "create", "--internal", "--label", f"{LABEL}={sid}", "--label", f"{OWNER}={self.owner}", net)
        targets = []
        try:
            for addr in spec.egress_allow:
                host = addr.rsplit(":", 1)[0] if ":" in addr else addr
                if _docker("inspect", "--type", "container", host, check=False).returncode != 0:
                    raise ScopeError(f"M0 只支持本机靶场容器作为出站目标：{host!r} 不是容器")
                _docker("network", "connect", "--alias", host, net, host)
                targets.append(host)
            lim = spec.limits
            args = ["run", "-d", "--name", sid, "--label", f"{LABEL}={sid}", "--label", f"{OWNER}={self.owner}",
                    "--label", f"paoding.lease={lease_id}",
                    "--network", net, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--pids-limit", str(lim.pids), "--memory", f"{lim.mem_mb}m", "--cpus", str(lim.cpu),
                    "--env", "HOME=/tmp", "-w", "/workspace"]
            if mount_workspace:
                args += ["--mount", f"type=bind,source={spec.workspace},target=/workspace"]
            else:
                args += ["--tmpfs", "/workspace"]
            _docker(*args, spec.image, "sleep", "infinity")
        except BaseException:
            self._teardown(sid, net, targets)
            raise
        self._live[sid] = {"spec": spec, "net": net, "targets": targets, "lease": lease_id,
                           "mounted": mount_workspace}
        return sid

    def reset(self, sid: str) -> str:
        """回到 baseline：销毁后从同一镜像重建。工作区是共享挂载，不随之重置。"""
        info = self._live[sid]
        self.destroy(sid)
        return self.launch(info["spec"], info["lease"], info["mounted"])

    def destroy(self, sid: str) -> None:
        info = self._live.pop(sid, None)
        if info:
            self._teardown(sid, info["net"], info["targets"])

    def _teardown(self, sid: str, net: str, targets: list[str]) -> None:
        _docker("rm", "-f", sid, check=False)
        for t in targets:
            _docker("network", "disconnect", "-f", net, t, check=False)
        _docker("network", "rm", net, check=False)

    # ---------- exec ----------

    def exec(self, sid: str, cmd: str, pid: str, idem_key: str, timeout_s: int = 60, cwd: str = "/workspace",
             register_as: str = "exec") -> ExecResult:
        """register_as：Worker 租约下为 "exec"（本层登记）；判官租约下为 "judge"（交回判官运行器登记）。"""
        info = self._live[sid]
        spec: ExecSpec = info["spec"]
        started = int(time.time() * 1000)
        inner = f"exec 2>&1; timeout -s KILL {int(timeout_s)} sh -c {shlex.quote(cmd)}"
        try:
            p = subprocess.run(["docker", "exec", "-w", cwd, sid, "sh", "-c", inner],
                               capture_output=True, timeout=timeout_s + 30)
            data, code = p.stdout + p.stderr, p.returncode
            if code == 137:                                  # timeout -s KILL
                code = None
        except subprocess.TimeoutExpired as e:
            data, code = (e.stdout or b"") + (e.stderr or b""), None
        ended = int(time.time() * 1000)
        captured_trunc = len(data) > MAX_CAPTURE
        if captured_trunc:
            half = MAX_CAPTURE // 2
            data = data[:half] + data[-half:]
        h = self.blobs.put(data)
        text, echo_trunc = echo(data)
        prov = {"sandbox_id": sid, "base": spec.image, "baseline_ref": spec.baseline_ref, "tool": "shell",
                "command": cmd, "cwd": cwd, "exit_code": code,
                "touched": [],                               # 见 SPEC.md 已知缺口：M0 没有逐连接的访问摘要
                "started_at": started, "ended_at": ended, "truncated": captured_trunc}
        aid = None
        if register_as == "exec":
            out = self.graph.submit(self.token, pid, idem_key, [{"op": "register_artifact", "body": {
                "hash": h, "size": len(data), "media_type": "text/plain; charset=utf-8", "class": "exec",
                "exec": prov}}])
            if not out["ok"]:
                raise RuntimeError(f"登记失败：{out['results']}")
            aid = out["results"][0]["id"]
        return ExecResult(artifact=aid, blob=h, exit_code=code, output=text,
                          truncated=echo_trunc or captured_trunc, provenance=prov)


def sweep_orphans() -> list[str]:
    """哮天犬用：清理带本层标签、且属主进程已不存活的容器与网络。返回清掉的名字。

    只清本机属主确定已死的：属主在别的主机、标签缺失或格式不明的一律不动（宁漏勿误杀活沙箱）。"""
    def dead(listing: str) -> list[str]:
        out = []
        for line in listing.splitlines():
            name, _, owner = line.partition(" ")
            if name and owner_alive(owner.strip()) is False:
                out.append(name)
        return out
    ps = _docker("ps", "-a", "--filter", f"label={LABEL}", "--format", f'{{{{.Names}}}} {{{{.Label "{OWNER}"}}}}',
                 check=False)
    names = dead(ps.stdout.decode())
    for n in names:
        _docker("rm", "-f", n, check=False)
    nets = _docker("network", "ls", "--filter", f"label={LABEL}", "--format",
                   f'{{{{.Name}}}} {{{{.Label "{OWNER}"}}}}', check=False)
    for n in dead(nets.stdout.decode()):
        _docker("network", "rm", n, check=False)
    return names
