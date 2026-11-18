"""执行层运行时（§3.6.2）：Docker 容器、出站白名单、exec 的容器外采集与登记。

隔离（M0）：
- 每个沙箱一张 `--internal` 的 Docker 网络，没有出站路由；只把授权范围编译出的目标容器接进来。
  所以执行容器只能连到白名单里的本机题目容器，连不到模型端点，也连不到外网（3.6.4 的 1、4）。
- 容器 `--cap-drop ALL`、`no-new-privileges`、资源上限；不传任何环境变量，不挂任何密钥。
- 工作区是唯一的可写挂载；判官的洁净容器不挂 Worker 的工作区（3.6.4 的 3）。

采集：命令在容器里运行，标准输出与标准错误（合并以保序）由本进程在容器之外逐块读取、边读边落盘
（capture.py：超过上限只留头尾，内存里只有一个读块），再逐块写入 Blob 仓库，
用执行层的组件令牌登记为 exec 类。模型拿到的是 ArtifactId 和截断回显。

结束方式（ExecResult.ended_by）：exit 正常退出；timeout 到了 timeout_s 被杀；oom 触到内存上限被内核杀掉
（依据是 Docker 守护进程在这次运行期间为该容器报的 oom 事件，不取容器内的任何说法）；killed 其余被杀的情况。
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

from .capture import Capture, pump
from .compile import ExecSpec, ScopeError

ECHO_LIMIT = 8 * 1024                  # 回显上限 8 KB，超过只回头尾（§3.4.2）
MAX_CAPTURE = 256 * 1024 * 1024        # 单个 Blob 上限；超过保留头尾并置 truncated（§3.2.2）
KILL_GRACE_S = 30                      # 容器内的 timeout 没能收场时，本进程再等这么久就杀掉 docker exec
LABEL = "paoding.sandbox"
LEASE = "paoding.lease"                 # 沙箱所服务的租约；按租约回收时用
ROLE = "paoding.role"                   # sandbox（执行容器）| env（题目环境容器）
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


class SandboxGone(RuntimeError):
    """沙箱不存在或已停止：容器被销毁、被清扫，或到了墙钟上限。调用方应视作任务失败，不重试。"""


@dataclass
class ExecResult:
    artifact: str | None              # 登记后的 ArtifactId；judge 模式下为 None，由判官运行器登记
    blob: str
    exit_code: int | None
    output: str                       # 截断后的回显
    truncated: bool                   # 回显或采集是否截断
    provenance: dict                  # exec 出处字段（§3.2.2），judge 模式下交给判官运行器
    ended_by: str = "exit"            # exit | timeout | oom | killed


def _docker(*args: str, check: bool = True, timeout: float | None = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, check=check, timeout=timeout)


def echo(data: bytes | Capture, limit: int = ECHO_LIMIT) -> tuple[str, bool]:
    """回显：不超过 limit 原样给出，超过只给头尾。data 是 Capture 时只从盘上读这两段。"""
    size = data.stored if isinstance(data, Capture) else len(data)

    def part(start: int, end: int) -> str:
        raw = data.read(start, end) if isinstance(data, Capture) else data[start:end]
        return raw.decode("utf-8", "replace")
    if size <= limit:
        return part(0, size), False
    half = limit // 2
    return part(0, half) + f"\n…[省略 {size - 2 * half} 字节，用 show 按区间读全文]…\n" + part(size - half, size), True


def _oom_between(sid: str, since: float, until: float) -> bool:
    """这段时间里 Docker 守护进程有没有为该容器报过 oom 事件。事件可能比进程退出晚一点到，所以看两次。"""
    for wait in (0.0, 0.5):
        time.sleep(wait)
        p = _docker("events", "--filter", f"container={sid}", "--filter", "event=oom", "--since", f"{since:.3f}",
                    "--until", f"{until + wait:.3f}", "--format", "{{.Action}}", check=False, timeout=20)
        if p.returncode == 0 and p.stdout.strip():
            return True
    return False


class DockerExecutor:
    def __init__(self, graph: GraphPort, blobs: BlobPort, token: str, max_capture: int = MAX_CAPTURE,
                 spool_dir: str | None = None):
        """spool_dir：采集的落盘位置，缺省用系统临时目录。临时目录是内存盘的机器上应指到真盘。"""
        self.graph, self.blobs, self.token = graph, blobs, token
        self.max_capture, self.spool_dir = max_capture, spool_dir
        if spool_dir:
            Path(spool_dir).mkdir(parents=True, exist_ok=True)
        self.owner = owner_id()
        self._live: dict[str, dict] = {}

    # ---------- 生命周期 ----------

    def launch(self, spec: ExecSpec, lease_id: str, mount_workspace: bool = True, sid: str | None = None) -> str:
        """新建沙箱：一张内部网络 + 一个容器。sid 只在 reset 重建时显式给出，其余随机生成。
        任何一步失败都把已建的容器与网络拆掉，不留半成品。"""
        sid = sid or f"pd-{spec.id}-{uuid.uuid4().hex[:8]}"
        net = f"{sid}-net"
        _docker("network", "create", "--internal", "--label", f"{LABEL}={sid}", "--label", f"{OWNER}={self.owner}", net)
        targets = []
        try:
            for addr in spec.egress_allow:
                host = addr.rsplit(":", 1)[0] if ":" in addr else addr
                if _docker("inspect", "--type", "container", host, check=False).returncode != 0:
                    raise ScopeError(f"M0 只支持本机题目容器作为出站目标：{host!r} 不是容器")
                _docker("network", "connect", "--alias", host, net, host)
                targets.append(host)
            lim = spec.limits
            args = ["run", "-d", "--name", sid, "--label", f"{LABEL}={sid}", "--label", f"{OWNER}={self.owner}",
                    "--label", f"{LEASE}={lease_id}", "--label", f"{ROLE}=sandbox",
                    "--network", net, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--pids-limit", str(lim.pids), "--memory", f"{lim.mem_mb}m", "--cpus", str(lim.cpu),
                    "--env", "HOME=/tmp", "-w", "/workspace"]
            if mount_workspace:
                args += ["--mount", f"type=bind,source={spec.workspace},target=/workspace"]
            else:
                args += ["--tmpfs", "/workspace"]
            # 墙钟上限：容器自己到点退出，不靠外面记得来杀（limits.wall_s，§3.6.2）
            _docker(*args, spec.image, "sleep", str(int(lim.wall_s)))
        except BaseException:
            self._teardown(sid, net, targets)
            raise
        self._live[sid] = {"spec": spec, "net": net, "targets": targets, "lease": lease_id,
                           "mounted": mount_workspace}
        return sid

    def reset(self, sid: str) -> str:
        """回到 baseline：销毁后从同一镜像重建，沙箱 id 不变（会话手里的 id 继续有效）。
        工作区是共享挂载，不随之重置。"""
        info = self._info(sid)
        self.destroy(sid)
        return self.launch(info["spec"], info["lease"], info["mounted"], sid=sid)

    def destroy(self, sid: str) -> None:
        """幂等。本实例不认识的 sid（例如进程重启之后）按标签找到它的网络与接入的目标再拆。"""
        info = self._live.pop(sid, None)
        if info:
            self._teardown(sid, info["net"], info["targets"])
        elif _owned(sid) is not None:
            self._teardown(sid, f"{sid}-net", _net_members(f"{sid}-net", exclude=sid))

    def destroy_lease(self, lease_id: str) -> list[str]:
        """销毁某个租约名下的全部沙箱（Worker 的执行容器与判官的洁净容器）。返回销毁的 sid。"""
        sids = [s for s, i in self._live.items() if i["lease"] == lease_id]
        sids += [s for s in _list(f"label={LEASE}={lease_id}", f"label={ROLE}=sandbox") if s not in sids]
        for sid in sids:
            self.destroy(sid)
        return sids

    def reap(self, active_leases: set[str] | frozenset[str]) -> list[str]:
        """清理本实例名下、租约已不在途的沙箱（租约过期或被叫停后，哮天犬据 /status 的在途租约调用）。"""
        gone = [sid for sid, i in list(self._live.items()) if i["lease"] not in active_leases]
        for sid in gone:
            self.destroy(sid)
        return gone

    def sandboxes(self) -> list[dict]:
        """本实例名下的沙箱：sid、租约、是否仍在运行。只读，供状态页与清理决策用。"""
        out = []
        for sid, i in sorted(self._live.items()):
            out.append({"sid": sid, "lease": i["lease"], "spec": i["spec"].id, "targets": list(i["targets"]),
                        "mounted": i["mounted"], "running": _running(sid)})
        return out

    def close(self) -> None:
        """进程正常退出时：把自己名下的沙箱全部销毁。异常退出留下的由 sweep_orphans 清。"""
        for sid in list(self._live):
            self.destroy(sid)

    def __enter__(self) -> DockerExecutor:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _info(self, sid: str) -> dict:
        info = self._live.get(sid)
        if info is None:
            raise SandboxGone(f"没有沙箱 {sid}")
        return info

    def _teardown(self, sid: str, net: str, targets: list[str]) -> None:
        _docker("rm", "-f", "-v", sid, check=False)
        for t in targets:
            _docker("network", "disconnect", "-f", net, t, check=False)
        _docker("network", "rm", net, check=False)

    # ---------- exec ----------

    def exec(self, sid: str, cmd: str, pid: str, idem_key: str, timeout_s: int = 60, cwd: str = "/workspace",
             register_as: str = "exec") -> ExecResult:
        """register_as：Worker 租约下为 "exec"（本层登记）；判官租约下为 "judge"（交回判官运行器登记）。"""
        info = self._info(sid)
        if not _running(sid):
            raise SandboxGone(f"沙箱 {sid} 已停止")
        spec: ExecSpec = info["spec"]
        started_s = time.time()
        started = int(started_s * 1000)
        inner = f"exec 2>&1; timeout -s KILL {int(timeout_s)} sh -c {shlex.quote(cmd)}"
        with Capture(self.max_capture, self.spool_dir) as cap:
            code, took = pump(["docker", "exec", "-w", cwd, sid, "sh", "-c", inner], cap, timeout_s + KILL_GRACE_S)
            ended_s = time.time()
            ended = int(ended_s * 1000)
            ended_by = "exit"
            if code is None or (code == 137 and took >= timeout_s):     # 墙钟到点：本进程杀的，或容器内 timeout -s KILL
                code, ended_by = None, "timeout"
            elif code == 137:                                # 没到点就被 SIGKILL：是不是触到了内存上限
                ended_by = "oom" if _oom_between(sid, started_s, ended_s + 1) else "killed"
            captured_trunc, size = cap.truncated, cap.stored
            h = self.blobs.put(cap.reader())                  # 逐块写入，不把整段输出读进内存
            text, echo_trunc = echo(cap)
        if ended_by == "timeout":
            text += f"\n[执行层：超过 {int(timeout_s)} 秒，已终止]"
        elif ended_by == "oom":
            text += f"\n[执行层：超过内存上限 {spec.limits.mem_mb} MB，已被终止]"
        prov = {"sandbox_id": sid, "base": spec.image, "baseline_ref": spec.baseline_ref, "tool": "shell",
                "command": cmd, "cwd": cwd, "exit_code": code,
                "touched": [],                               # 见 SPEC.md 已知缺口：M0 没有逐连接的访问摘要
                "started_at": started, "ended_at": ended, "truncated": captured_trunc}
        aid = None
        if register_as == "exec":
            out = self.graph.submit(self.token, pid, idem_key, [{"op": "register_artifact", "body": {
                "hash": h, "size": size, "media_type": "text/plain; charset=utf-8", "class": "exec",
                "exec": prov}}])
            if not out["ok"]:
                raise RuntimeError(f"登记失败：{out['results']}")
            aid = out["results"][0]["id"]
        return ExecResult(artifact=aid, blob=h, exit_code=code, output=text,
                          truncated=echo_trunc or captured_trunc, provenance=prov, ended_by=ended_by)


def _running(name: str) -> bool:
    p = _docker("inspect", "--type", "container", "--format", "{{.State.Running}}", name, check=False)
    return p.returncode == 0 and p.stdout.decode().strip() == "true"


def _owned(name: str) -> str | None:
    """容器带本层标签时返回它的属主，否则 None：不是本层建的东西一律不碰。"""
    p = _docker("inspect", "--type", "container", "--format",
                f'{{{{index .Config.Labels "{LABEL}"}}}}|{{{{index .Config.Labels "{OWNER}"}}}}', name, check=False)
    if p.returncode != 0:
        return None
    label, _, owner = p.stdout.decode().strip().partition("|")
    return owner if label else None


def _list(*filters: str) -> list[str]:
    args = ["ps", "-a", "--format", "{{.Names}}"]
    for f in filters:
        args += ["--filter", f]
    return [n for n in _docker(*args, check=False).stdout.decode().split() if n]


def _net_members(net: str, exclude: str = "") -> list[str]:
    p = _docker("network", "inspect", "--format", "{{range .Containers}}{{.Name}} {{end}}", net, check=False)
    return [n for n in p.stdout.decode().split() if n and n != exclude] if p.returncode == 0 else []


class EnvManager:
    """题目环境容器的生命周期（规格 §3.6.2 的 env；kickoff §6：启动、重置 = 删除后按同一参数重建、销毁）。

    环境容器是执行容器的出站目标，本身不跑 Worker 的命令。它与沙箱用同一套属主标签，
    所以进程异常退出后同样由 sweep_orphans 回收。启动参数（含环境变量）只留在本进程内存里，
    不写日志、不进 Blob、不进任何沙箱。"""

    def __init__(self) -> None:
        self.owner = owner_id()
        self._envs: dict[str, dict] = {}

    def start(self, name: str, image: str, env: dict[str, str] | None = None, command: list[str] | None = None,
              ready_port: int | None = None, ready_timeout_s: float = 30.0) -> str:
        if name in self._envs or _docker("inspect", "--type", "container", name, check=False).returncode == 0:
            raise ValueError(f"环境容器 {name} 已存在")
        args = ["run", "-d", "--name", name, "--label", f"{LABEL}={name}", "--label", f"{OWNER}={self.owner}",
                "--label", f"{ROLE}=env", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "256", "--memory", "512m"]
        for k, v in sorted((env or {}).items()):
            args += ["--env", f"{k}={v}"]
        try:
            _docker(*args, image, *(command or []))
        except BaseException:
            _docker("rm", "-f", "-v", name, check=False)
            raise
        self._envs[name] = {"image": image, "env": dict(env or {}), "command": list(command or []),
                            "ready_port": ready_port, "ready_timeout_s": ready_timeout_s}
        if ready_port is not None:
            self.wait_ready(name, ready_port, ready_timeout_s)
        return name

    def wait_ready(self, name: str, port: int, timeout_s: float = 30.0) -> None:
        """等容器内的端口开始监听。探测在容器自己的网络命名空间里做，不需要对宿主发布端口。"""
        probe = f"exec 3<>/dev/tcp/127.0.0.1/{int(port)}"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not _running(name):
                break
            if subprocess.run(["docker", "exec", name, "bash", "-c", probe], capture_output=True).returncode == 0:
                return
            time.sleep(0.2)
        logs = _docker("logs", "--tail", "20", name, check=False)
        self.stop(name)
        raise RuntimeError(f"环境容器 {name} 未就绪：{(logs.stdout + logs.stderr).decode('utf-8', 'replace')[-400:]}")

    def reset(self, name: str) -> str:
        """回到初始状态：删除后按同一镜像、同一参数重建（镜像不变，状态清零）。"""
        cfg = self._envs[name]
        self.stop(name)
        return self.start(name, cfg["image"], cfg["env"], cfg["command"], cfg["ready_port"], cfg["ready_timeout_s"])

    def stop(self, name: str) -> None:
        """幂等。只删本层建的容器；先把它从所有沙箱网络上摘下来，免得网络删不掉。"""
        known = self._envs.pop(name, None)
        if known is None and _owned(name) is None:
            return
        p = _docker("inspect", "--type", "container", "--format",
                    "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}", name, check=False)
        for net in p.stdout.decode().split():
            if net.endswith("-net"):
                _docker("network", "disconnect", "-f", net, name, check=False)
        _docker("rm", "-f", "-v", name, check=False)

    def running(self, name: str) -> bool:
        return _running(name)

    def names(self) -> list[str]:
        return sorted(self._envs)

    def close(self) -> None:
        for name in list(self._envs):
            self.stop(name)

    def __enter__(self) -> EnvManager:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


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
        _docker("rm", "-f", "-v", n, check=False)
    nets = _docker("network", "ls", "--filter", f"label={LABEL}", "--format",
                   f'{{{{.Name}}}} {{{{.Label "{OWNER}"}}}}', check=False)
    for n in dead(nets.stdout.decode()):
        for member in _net_members(n):                       # 目标容器还接在上面时网络删不掉
            _docker("network", "disconnect", "-f", n, member, check=False)
        _docker("network", "rm", n, check=False)
    return names
