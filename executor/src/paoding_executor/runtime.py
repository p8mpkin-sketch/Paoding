"""执行层运行时（§3.6.2）：Docker 容器、出站白名单、exec 的容器外采集与登记。

隔离（M0）：
- 每个沙箱一张 `--internal` 的 Docker 网络 `<sid>-net`，没有出站路由，上面只有执行容器与出站闸门。
  闸门（gate.py，每台授权主机一个容器 `<sid>-gate-N`）在这张网络上顶着目标的主机名，只为授权规则写明的
  host:port 开转发；目标容器接在另一张内部网络 `<sid>-up-net` 上，只有闸门到得了。
  所以执行容器只能连到白名单里的 host:port：同一目标的其他端口、目标的真实地址、模型端点、外网都不通
  （3.6.4 的 1、4）。闸门只认执行容器的源地址，别的容器即使接进 `<sid>-net` 也过不了闸门。
- 容器 `--cap-drop ALL`、`no-new-privileges`、资源上限；不传任何环境变量，不挂任何密钥。
- 工作区是唯一的可写挂载；判官的洁净容器不挂 Worker 的工作区（3.6.4 的 3）。

采集：命令在容器里运行，标准输出与标准错误（合并以保序）由本进程在容器之外逐块读取、边读边落盘
（capture.py：超过上限只留头尾，内存里只有一个读块），再逐块写入 Blob 仓库，
用执行层的组件令牌登记为 exec 类。模型拿到的是 ArtifactId 和截断回显。

结束方式（ExecResult.ended_by）：exit 正常退出；timeout 到了 timeout_s 被杀；oom 触到内存上限被内核杀掉
（依据是 Docker 守护进程在这次运行期间为该容器报的 oom 事件，不取容器内的任何说法）；killed 其余被杀的情况。
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paoding_graph.contract import BlobPort, GraphPort

from .capture import Capture, pump
from .compile import ExecSpec, ScopeError, split_address

ECHO_LIMIT = 8 * 1024  # 回显上限 8 KB，超过只回头尾（§3.4.2）
MAX_CAPTURE = 256 * 1024 * 1024  # 单个 Blob 上限；超过保留头尾并置 truncated（§3.2.2）
KILL_GRACE_S = 30  # 容器内的 timeout 没能收场时，本进程再等这么久就杀掉 docker exec
LABEL = "paoding.sandbox"
LEASE = "paoding.lease"  # 沙箱所服务的租约；按租约回收时用
ROLE = "paoding.role"  # sandbox（执行容器）| gate（出站闸门）| env（题目环境容器）
GATE_IMAGE = "python:3.12-slim"  # 闸门只要一个带 Python 标准库的镜像；与题目、与执行容器的镜像无关
GATE_SOURCE = Path(__file__).with_name("gate.py").read_text(encoding="utf-8")
GATE_READY_S = 20.0
OWNER = "paoding.owner"  # 属主：<主机名>:<pid>:<进程启动时刻>，孤儿清扫只清属主已不存活的
CLEAN_S = 30.0  # 拆沙箱时每条容器命令最多等这么久
CLEAN_FAST_S = 5.0  # 已经有一条超时（容器服务没在答）之后，剩下的只发不久等：超时的删除请求事后仍会被执行
LIST_S = 10.0  # 清扫里的列取命令：容器服务无响应时不让看门狗一轮卡上几分钟
DOOM_KEEP_S = 600.0  # 启动失败的沙箱名至少复查这么久：容器可能在清理跑完之后才出现
RECLAIM_GRACE_S = 60.0  # 租约结束后过这么久才按标签回收：让会话自己的收尾先跑完


def _start_time(pid: int) -> str | None:
    """进程启动时刻（/proc/<pid>/stat 第 22 字段）。和 pid 一起判断存活，防 pid 复用。"""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return raw.rsplit(")", 1)[1].split()[19]


def owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{_start_time(os.getpid())}"


def _has_proc() -> bool:
    return Path("/proc/self/stat").exists()


def owner_alive(owner: str) -> bool | None:
    """True/False：本机属主是否存活；None：不是本机的属主、格式不明，或本机没有 /proc（macOS 等），不由本机判断。

    没有 /proc 时取不到进程启动时刻，活着的属主也会被判成“已死”，孤儿清扫就会误杀在用的沙箱与模型容器；
    这时一律答 None（宁漏勿误杀），清扫只在有 /proc 的平台上生效。"""
    try:
        host, pid, started = owner.rsplit(":", 2)
        pid_i = int(pid)
    except ValueError:
        return None
    if host != socket.gethostname() or not _has_proc():
        return None
    return _start_time(pid_i) == started


def host_path(p: str | Path) -> str:
    """交给 Docker 的宿主路径。macOS 上 /var、/tmp 是 /private/var、/private/tmp 的符号链接，解析过的路径带
    /private/ 前缀；Docker Desktop 的共享目录按 /var/folders、/tmp 登记，带前缀的挂载会被拒。去掉前缀即可。
    其它平台原样返回（Linux 上 /private/ 没有这层含义）。"""
    s = str(p)
    if sys.platform == "darwin" and s.startswith("/private/"):
        return s[len("/private") :]
    return s


def bind_args(src: str | Path, dst: str, readonly: bool = False) -> list[str]:
    """绑定挂载用 `-v 宿主:容器[:ro]`，不用 `--mount type=bind`（macOS 的 Docker Desktop 上后者对这些路径失败，
    真实环境验证过）。`-v` 遇到不存在的宿主路径会悄悄建一个空目录：这里先查存在，保留 `--mount` 那样的当场报错。"""
    s = host_path(src)
    if ":" in s or ":" in dst:
        raise ValueError(f"挂载路径里不能有冒号（-v 的分隔符）：{s!r} → {dst!r}")
    if not Path(src).exists():
        raise FileNotFoundError(f"挂载源不存在：{src}")
    return ["-v", f"{s}:{dst}" + (":ro" if readonly else "")]


class SandboxGone(RuntimeError):
    """沙箱不存在或已停止：容器被销毁、被清扫，或到了墙钟上限。调用方应视作任务失败，不重试。"""


@dataclass
class ExecResult:
    artifact: str | None  # 登记后的 ArtifactId；judge 模式下为 None，由判官运行器登记
    blob: str
    exit_code: int | None
    output: str  # 截断后的回显
    truncated: bool  # 回显或采集是否截断
    provenance: dict[str, Any]  # exec 出处字段（§3.2.2），judge 模式下交给判官运行器
    ended_by: str = "exit"  # exit | timeout | oom | killed


def _docker(*args: str, check: bool = True, timeout: float | None = 120) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(["docker", *args], capture_output=True, check=check, timeout=timeout)


def _try(*args: str, timeout: float) -> subprocess.CompletedProcess[Any] | None:
    """清理与清扫用：不抛。超时或命令行本身起不来返回 None（“没问到”），其余返回结果（退出码自己看）。"""
    try:
        return _docker(*args, check=False, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


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
        p = _docker(
            "events",
            "--filter",
            f"container={sid}",
            "--filter",
            "event=oom",
            "--since",
            f"{since:.3f}",
            "--until",
            f"{until + wait:.3f}",
            "--format",
            "{{.Action}}",
            check=False,
            timeout=20,
        )
        if p.returncode == 0 and p.stdout.strip():
            return True
    return False


class DockerExecutor:
    def __init__(
        self,
        graph: GraphPort,
        blobs: BlobPort,
        token: str,
        max_capture: int = MAX_CAPTURE,
        spool_dir: str | None = None,
        gate_image: str = GATE_IMAGE,
    ):
        """spool_dir：采集的落盘位置，缺省用系统临时目录。临时目录是内存盘的机器上应指到真盘。"""
        self.graph, self.blobs, self.token = graph, blobs, token
        self.max_capture, self.spool_dir = max_capture, spool_dir
        if spool_dir:
            Path(spool_dir).mkdir(parents=True, exist_ok=True)
        self.gate_image = gate_image
        self.owner = owner_id()
        self._hot = threading.Lock()
        self._live: dict[str, dict[str, Any]] = {}
        # 待确认表：启动失败（或没拆干净）的沙箱名 → {lease, at}。settle 按名字加标签反复查、反复删，
        # 查得到“确实没有”且离失败已过 DOOM_KEEP_S 才划掉。只在内存里：进程重启后的遗留归 sweep_orphans。
        self._doomed: dict[str, dict[str, Any]] = {}
        self._launching: set[str] = set()
        self._book = threading.Lock()  # 护着 _doomed 与 _launching
        self._rebuild = threading.Lock()  # 重建（同名再起）与复查互斥：复查不删正在重建的沙箱
        self._clock = time.monotonic

    # ---------- 生命周期 ----------

    def launch(self, spec: ExecSpec, lease_id: str, mount_workspace: bool = True, sid: str | None = None) -> str:
        """新建沙箱：一张内部网络 + 执行容器 + 每台授权主机一个出站闸门。sid 只在 reset 重建时显式给出。
        任何一步失败都把已建的容器与网络拆掉，不留半成品。"""
        if sid is not None:  # 重建：名字是旧的，可能正在待确认表里——与复查互斥，起来了就从表里划掉
            with self._rebuild:
                return self._launch(spec, lease_id, mount_workspace, sid)
        return self._launch(spec, lease_id, mount_workspace, f"pd-{spec.id}-{uuid.uuid4().hex[:8]}")

    def _launch(self, spec: ExecSpec, lease_id: str, mount_workspace: bool, sid: str) -> str:
        with self._book:
            self._launching.add(sid)
        try:
            return self._launch_steps(spec, lease_id, mount_workspace, sid)
        except BaseException:
            # 善后做不完也不抛新的错（原来第一条查询超时就把整个清理打断了）；这个名字无论如何进待确认表：
            # 容器可能在清理跑完之后才出现（建容器的请求客户端超时了，容器服务事后还是把它建了出来）。
            _teardown(sid)
            self._doom(sid, lease_id)
            raise
        finally:
            with self._book:
                self._launching.discard(sid)

    def _launch_steps(self, spec: ExecSpec, lease_id: str, mount_workspace: bool, sid: str) -> str:
        net, up = f"{sid}-net", f"{sid}-up-net"
        labels = ["--label", f"{LABEL}={sid}", "--label", f"{OWNER}={self.owner}"]
        hosts = _by_host(spec)
        _docker("network", "create", "--internal", *labels, net)
        if hosts:
            _docker("network", "create", "--internal", *labels, up)
        for host in hosts:
            if _docker("inspect", "--type", "container", host, check=False).returncode != 0:
                raise ScopeError(f"M0 只支持本机题目容器作为出站目标：{host!r} 不是容器")
            _docker("network", "connect", "--alias", host, up, host)  # 目标只接上游网络，沙箱够不着
        lim = spec.limits
        args = [
            "run",
            "-d",
            "--name",
            sid,
            *labels,
            "--label",
            f"{LEASE}={lease_id}",
            "--label",
            f"{ROLE}=sandbox",
            "--network",
            net,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(lim.pids),
            "--memory",
            f"{lim.mem_mb}m",
            "--cpus",
            str(lim.cpu),
            "--env",
            "HOME=/tmp",
            "-w",
            "/workspace",
        ]
        if mount_workspace:
            args += bind_args(spec.workspace, "/workspace")
        else:
            args += ["--tmpfs", "/workspace"]
        # 墙钟上限：容器自己到点退出，不靠外面记得来杀（limits.wall_s，§3.6.2）
        _docker(*args, spec.image, "sleep", str(int(lim.wall_s)))
        gate_of = self._start_gates(sid, net, up, hosts, labels, lease_id, lim.wall_s)
        with self._book:
            self._doomed.pop(sid, None)  # 重建成功：不再待确认
            self._live[sid] = {
                "spec": spec,
                "net": net,
                "up": up if hosts else None,
                "targets": sorted(hosts),
                "gate_of": gate_of,
                "gates": [gate_of[h] for h in sorted(gate_of)],
                "lease": lease_id,
                "mounted": mount_workspace,
                "labels": labels,
                "deadline": time.monotonic() + lim.wall_s,
            }
        return sid

    def reconcile(self, sid: str, spec: ExecSpec) -> dict[str, list[str]]:
        """运行时扩权（docs/design/runtime-grants/ §5）：把在跑的沙箱的出站闸门对齐到新编出的 spec。

        只动闸门，不动执行容器与工作区：新授权的主机起一个闸门（热加），撤销的主机停掉它的闸门（热撤销，
        主机名随之解析不到，进行中的连接断开），同一主机的端口集合变了就换一个闸门。隔离不变：新闸门照旧
        只认执行容器的源地址、只为写明的端口开转发。spec 与在跑的相同时什么都不做。返回 {added, removed}。"""
        with self._hot:  # 工具线程（批下即对齐）与会话循环（看到范围变了）可能同时来
            return self._reconcile(sid, spec)

    def _reconcile(self, sid: str, spec: ExecSpec) -> dict[str, list[str]]:
        info = self._info(sid)
        old, new = _by_host(info["spec"]), _by_host(spec)
        drop = sorted(h for h in old if old[h] != new.get(h))
        add = sorted(h for h in new if new[h] != old.get(h))
        gate_of: dict[str, str] = dict(info["gate_of"])
        for host in drop:
            _docker("rm", "-f", "-v", gate_of.pop(host), check=False)
            if host not in new and info["up"]:
                _docker("network", "disconnect", "-f", info["up"], host, check=False)
        if add:
            up = info["up"] or f"{sid}-up-net"
            if info["up"] is None:
                _docker("network", "create", "--internal", *info["labels"], up)
                info["up"] = up
            for host in add:
                if host in old:
                    continue  # 目标已接在上游网络上
                if _docker("inspect", "--type", "container", host, check=False).returncode != 0:
                    raise ScopeError(f"M0 只支持本机题目容器作为出站目标：{host!r} 不是容器")
                _docker("network", "connect", "--alias", host, up, host)
            left = max(1, int(info["deadline"] - time.monotonic()))
            gate_of.update(
                self._start_gates(
                    sid, info["net"], up, {h: new[h] for h in add}, info["labels"], info["lease"], left, fresh=True
                )
            )
        info.update(spec=spec, gate_of=gate_of, gates=[gate_of[h] for h in sorted(gate_of)], targets=sorted(new))
        return {"added": add, "removed": [h for h in drop if h not in new]}

    def _start_gates(
        self,
        sid: str,
        net: str,
        up: str,
        hosts: dict[str, list[dict[str, Any]]],
        labels: list[str],
        lease_id: str,
        wall_s: int,
        fresh: bool = False,
    ) -> dict[str, str]:
        """每台授权主机一个闸门：在沙箱网络上顶着主机名，另一只脚在上游网络。等它们都开始监听再返回。
        返回 主机 → 闸门容器名。fresh：热加时用随机后缀起名，不与已有闸门撞名。"""
        if not hosts:
            return {}
        src = _ip(sid, net)
        gates = []
        names: dict[str, str] = {}
        for n, (host, rules) in enumerate(sorted(hosts.items())):
            gate = f"{sid}-gate-{uuid.uuid4().hex[:6] if fresh else n}"
            names[host] = gate
            cfg = {"host": host, "upstream": _ip(host, up), "allow_src": src, "rules": rules}
            _docker(
                "create",
                "--name",
                gate,
                *labels,
                "--label",
                f"{LEASE}={lease_id}",
                "--label",
                f"{ROLE}=gate",
                "--network",
                net,
                "--network-alias",
                host,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--read-only",
                "--user",
                "65534:65534",
                "--pids-limit",
                "512",
                "--memory",
                "128m",
                "--stop-timeout",
                "1",
                self.gate_image,
                "timeout",
                "-s",
                "KILL",
                str(int(wall_s) + 60),
                "python",
                "-u",
                "-c",
                GATE_SOURCE,
                json.dumps(cfg, sort_keys=True),
            )
            _docker("network", "connect", up, gate)
            _docker("start", gate)
            gates.append(gate)
        deadline = time.monotonic() + GATE_READY_S
        for gate in gates:
            while not any(e.get("event") == "ready" for e in gate_log(gate)):
                if time.monotonic() > deadline or not _running(gate):
                    tail = _docker("logs", "--tail", "5", gate, check=False)
                    raise RuntimeError(
                        f"出站闸门 {gate} 未就绪：{(tail.stdout + tail.stderr).decode('utf-8', 'replace')[-300:]}"
                    )
                time.sleep(0.05)
        return names

    def reset(self, sid: str) -> str:
        """回到 baseline：销毁后从同一镜像重建，沙箱 id 不变（会话手里的 id 继续有效）。
        工作区是共享挂载，不随之重置。"""
        info = self._info(sid)
        self.destroy(sid)
        return self.launch(info["spec"], info["lease"], info["mounted"], sid=sid)

    def destroy(self, sid: str) -> None:
        """幂等。按标签拆：执行容器、闸门、两张网络。本实例不认识的 sid（例如进程重启之后）同样拆得掉。
        拆的过程中有命令没答（容器服务无响应）不抛：这个名字记进待确认表，settle 之后接着拆。"""
        known = self._live.pop(sid, None)
        if known or _owned(sid) is not None or _labelled_nets(sid):
            if not _teardown(sid) and known:
                self._doom(sid, known["lease"])

    def destroy_lease(self, lease_id: str) -> list[str]:
        """销毁**本实例**某个租约名下的全部沙箱（Worker 的执行容器与判官的洁净容器）。返回销毁的 sid。
        按标签找时核对属主：租约编号在每个实例里从 1 顺序编，共用一个容器服务的两个实例一定有相同的编号。"""
        sids = [s for s, i in self._live.items() if i["lease"] == lease_id]
        mine = _list(f"label={LEASE}={lease_id}", f"label={ROLE}=sandbox", f"label={OWNER}={self.owner}")
        sids += [s for s in mine if s not in sids]
        for sid in sids:
            self.destroy(sid)
        return sids

    # ---------- 回收：启动失败的复查（待确认表）与按租约标签兜底 ----------

    def _doom(self, sid: str, lease_id: str) -> None:
        with self._book:
            self._doomed[sid] = {"lease": lease_id, "at": self._clock()}

    def doomed(self) -> list[dict[str, Any]]:
        """待确认表（只读）：启动失败或没拆干净、还在复查的沙箱名。"""
        with self._book:
            return [{"sid": s, "lease": r["lease"], "age_s": self._clock() - r["at"]} for s, r in self._doomed.items()]

    def settle(self) -> list[str]:
        """把待确认表过一遍：每个名字按“沙箱标签 = 这个名字、属主标签 = 本实例”查一遍、删一遍。返回这一轮删掉的。

        划掉的条件两条都要：这一次查询成功且确认什么都没有；离失败已过 DOOM_KEEP_S。失败后第一次复查时可能
        什么都没有、之后容器才出现，所以不能查到“没有”就划掉。在册的、正在启动的、正在重建的名字这一轮跳过。
        容器服务没答就到此为止，下一轮再来（不为每个名字各等一遍超时）。"""
        with self._book:
            todo = [s for s in self._doomed if s not in self._live and s not in self._launching]
        removed: list[str] = []
        for sid in todo:
            if not self._rebuild.acquire(blocking=False):
                continue  # 有沙箱正在重建：这一轮不碰
            try:
                with self._book:
                    if sid not in self._doomed or sid in self._live or sid in self._launching:
                        continue
                found = self._recheck(sid)
            finally:
                self._rebuild.release()
            if found is None:
                break
            removed += found
            with self._book:
                rec = self._doomed.get(sid)
                if rec is not None and not found and self._clock() - rec["at"] >= DOOM_KEEP_S:
                    del self._doomed[sid]
        return removed

    def _recheck(self, sid: str) -> list[str] | None:
        """一个待确认的名字名下还有什么（容器、网络），有就删。None：没问到（容器服务没答）。
        只认两个标签都对得上的：沙箱标签是这个名字，属主标签是本实例。"""
        mine = [f"label={LABEL}={sid}", f"label={OWNER}={self.owner}"]
        filters = [x for f in mine for x in ("--filter", f)]
        ps = _try("ps", "-a", *filters, "--format", "{{.Names}}", timeout=LIST_S)
        if ps is None or ps.returncode != 0:
            return None  # 没在答：第二条不必再等一遍
        nets = _try("network", "ls", *filters, "--format", "{{.Name}}", timeout=LIST_S)
        if nets is None or nets.returncode != 0:
            return None
        names = [n for n in ps.stdout.decode().split() if n]
        for name in names:
            _try("rm", "-f", "-v", name, timeout=CLEAN_S)
        for net in [n for n in nets.stdout.decode().split() if n]:
            _drop_net(net, CLEAN_S)
            names.append(net)
        return names

    def reclaim(self, lease_ended: Callable[[str], float | None], grace_s: float = RECLAIM_GRACE_S) -> list[str]:
        """清扫钩子用：先把待确认表过一遍（settle），再按租约标签兜底回收。返回这一轮拆掉的沙箱名与删掉的东西。

        兜底回收不看在册表，只看容器服务里实际有什么：列出带本层标签的沙箱与闸门容器，下面四条同时满足才拆
        （连同它的两张网络），缺一条就不碰——
          (a) 属主标签与本实例的属主标识逐字相同（别的实例、评测进程、本实例重启前的进程起的都不碰）；
          (b) 带租约标签，角色是沙箱或闸门（题目环境容器没有租约标签，不在范围内）；
          (c) lease_ended(租约) 答得出数：这个租约在本实例的账上查得到，并且已经结束；
          (d) 结束已超过 grace_s 秒。
        lease_ended 由组装层给：返回租约结束至今的秒数；账上查不到或仍在途返回 None。执行层不读事件账。
        不抛：列取用短超时，容器服务没答就返回已做的部分，下一轮再来。"""
        out = self.settle()
        fmt = "\t".join(["{{.Names}}", *(f'{{{{.Label "{k}"}}}}' for k in (LABEL, OWNER, LEASE, ROLE))])
        mine = ("--filter", f"label={LABEL}", "--filter", f"label={OWNER}={self.owner}")
        p = _try("ps", "-a", *mine, "--format", fmt, timeout=LIST_S)
        if p is None or p.returncode != 0:
            return out
        leases: dict[str, set[str]] = {}
        for line in p.stdout.decode().splitlines():
            cells = (line.split("\t") + [""] * 5)[:5]
            _name, sid, owner, lease, role = (c.strip() for c in cells)
            if sid and owner == self.owner and role in ("sandbox", "gate"):
                leases.setdefault(sid, set()).add(lease)  # 缺租约标签记成空串：这个沙箱整个不碰
        ended: dict[str, bool] = {}
        for sid, ls in sorted(leases.items()):
            with self._book:
                if sid in self._launching:
                    continue
            for lease in ls:
                if lease not in ended:
                    ended[lease] = bool(lease) and _past(lease_ended, lease, grace_s)
            if not all(ended[lease] for lease in ls):
                continue
            if not self._rebuild.acquire(blocking=False):
                continue  # 有沙箱正在重建：这一轮不碰
            try:
                with self._book:
                    if sid in self._launching:
                        continue
                    known = self._live.pop(sid, None)
                if not _teardown(sid):
                    self._doom(sid, known["lease"] if known else sorted(ls)[0])
            finally:
                self._rebuild.release()
            out.append(sid)
        return out

    def sandboxes(self) -> list[dict[str, Any]]:
        """本实例名下的沙箱：sid、租约、是否仍在运行。只读，供状态页与清理决策用。"""
        out = []
        for sid, i in sorted(self._live.items()):
            out.append(
                {
                    "sid": sid,
                    "lease": i["lease"],
                    "spec": i["spec"].id,
                    "targets": list(i["targets"]),
                    "mounted": i["mounted"],
                    "running": _running(sid),
                }
            )
        return out

    def close(self) -> None:
        """进程正常退出时：把自己名下的沙箱全部销毁。异常退出留下的由 sweep_orphans 清。"""
        for sid in list(self._live):
            self.destroy(sid)

    def __enter__(self) -> DockerExecutor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _info(self, sid: str) -> dict[str, Any]:
        info = self._live.get(sid)
        if info is None:
            raise SandboxGone(f"没有沙箱 {sid}")
        return info

    # ---------- exec ----------

    def _touched(self, info: dict[str, Any], started_ms: int, ended_ms: int) -> list[str]:
        """访问摘要（§3.2.2）：这次运行期间经闸门连到过的授权目标，形如 net:host:port，去重排序。

        来源是闸门在容器之外的逐连接记录，不取命令输出里的任何说法。目标端口没开、上游没接通的连接也算：
        它确实去碰了授权范围内的地址。白名单外的连接到不了闸门，不会出现在这里。"""
        seen = set()
        for gate in info.get("gates", []):
            for rec in gate_log(gate, since_ms=started_ms):
                if rec.get("event") == "connect" and started_ms <= rec.get("t", 0) <= ended_ms:
                    seen.add(f"net:{rec['dst']}")
        return sorted(seen)

    def exec(
        self,
        sid: str,
        cmd: str,
        pid: str,
        idem_key: str,
        timeout_s: int = 60,
        cwd: str = "/workspace",
        register_as: str = "exec",
    ) -> ExecResult:
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
            if code is None or (code == 137 and took >= timeout_s):  # 墙钟到点：本进程杀的，或容器内 timeout -s KILL
                code, ended_by = None, "timeout"
            elif code == 137:  # 没到点就被 SIGKILL：是不是触到了内存上限
                ended_by = "oom" if _oom_between(sid, started_s, ended_s + 1) else "killed"
            captured_trunc, size = cap.truncated, cap.stored
            h = self.blobs.put(cap.reader())  # 逐块写入，不把整段输出读进内存
            text, echo_trunc = echo(cap)
        if ended_by == "timeout":
            text += f"\n[执行层：超过 {int(timeout_s)} 秒，已终止]"
        elif ended_by == "oom":
            text += f"\n[执行层：超过内存上限 {spec.limits.mem_mb} MB，已被终止]"
        prov = {
            "sandbox_id": sid,
            "base": spec.image,
            "baseline_ref": spec.baseline_ref,
            "tool": "shell",
            "command": cmd,
            "cwd": cwd,
            "exit_code": code,
            "touched": self._touched(info, started, int(time.time() * 1000)),
            "started_at": started,
            "ended_at": ended,
            "truncated": captured_trunc,
        }
        aid = None
        if register_as == "exec":
            out = self.graph.submit(
                self.token,
                pid,
                idem_key,
                [
                    {
                        "op": "register_artifact",
                        "body": {
                            "hash": h,
                            "size": size,
                            "media_type": "text/plain; charset=utf-8",
                            "class": "exec",
                            "exec": prov,
                        },
                    }
                ],
            )
            if not out["ok"]:
                raise RuntimeError(f"登记失败：{out['results']}")
            aid = out["results"][0]["id"]
        return ExecResult(
            artifact=aid,
            blob=h,
            exit_code=code,
            output=text,
            truncated=echo_trunc or captured_trunc,
            provenance=prov,
            ended_by=ended_by,
        )


def _by_host(spec: ExecSpec) -> dict[str, list[dict[str, Any]]]:
    """授权规则按主机分组：host → [{port, actions}]。手工构造、只给了 egress_allow 的 ExecSpec 按 connect 处理。"""
    rules = spec.egress_rules or tuple((addr, ("connect",)) for addr in spec.egress_allow)
    out: dict[str, list[dict[str, Any]]] = {}
    for addr, actions in rules:
        host, port = split_address(addr)
        out.setdefault(host, []).append({"port": port, "actions": list(actions)})
    return out


def _ip(name: str, net: str) -> str:
    p = _docker(
        "inspect",
        "--type",
        "container",
        "--format",
        f'{{{{(index .NetworkSettings.Networks "{net}").IPAddress}}}}',
        name,
    )
    ip: str = p.stdout.decode().strip()
    if not ip:
        raise RuntimeError(f"{name} 在网络 {net} 上没有地址")
    return ip


def gate_log(gate: str, since_ms: int | None = None) -> list[dict[str, Any]]:
    """闸门的逐连接记录（它的标准输出，由本进程在容器之外读）。不是 JSON 的行忽略。
    since_ms：只读这个时刻（留一秒余量）之后的记录，长会话里不必每次读全量。"""
    since = [] if since_ms is None else ["--since", f"{since_ms / 1000 - 1:.3f}"]
    out = []
    for line in _docker("logs", *since, gate, check=False).stdout.decode("utf-8", "replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _labelled_nets(sid: str) -> list[str]:
    p = _docker("network", "ls", "--filter", f"label={LABEL}={sid}", "--format", "{{.Name}}", check=False)
    return [n for n in p.stdout.decode().split() if n]


def _past(lease_ended: Callable[[str], float | None], lease: str, grace_s: float) -> bool:
    try:
        age = lease_ended(lease)
    except Exception:  # noqa: BLE001  查询函数是别人给的：它出错就当“不知道”，不碰
        return False
    return age is not None and age >= grace_s


def _drop_net(net: str, timeout: float) -> bool:
    """删一张网络：先把还接在上面的容器摘掉（目标容器只摘网，不删）。False：有命令没答。"""
    p = _try("network", "inspect", "--format", "{{range .Containers}}{{.Name}} {{end}}", net, timeout=timeout)
    ok = p is not None
    for member in p.stdout.decode().split() if p is not None and p.returncode == 0 else []:
        ok = _try("network", "disconnect", "-f", net, member, timeout=timeout) is not None and ok
    return _try("network", "rm", net, timeout=timeout) is not None and ok


def _teardown(sid: str) -> bool:
    """拆掉一个沙箱名下的全部东西：带它标签的容器（执行容器、闸门）与网络。目标容器只摘网，不删。

    不抛。每条命令各自接住超时，做完能做的，继续下一条；删除先按名字发，不依赖查询结果（容器服务无响应时，
    超时的删除请求事后仍会被它执行，超时的查询只是白等）。返回 True：每条命令都答了；False：有没答的，
    调用方把这个名字记进待确认表，之后再查再删。"""
    wait = [CLEAN_S]
    answered = True

    def run(*args: str) -> subprocess.CompletedProcess[Any] | None:
        nonlocal answered
        p = _try(*args, timeout=wait[0])
        if p is None:
            answered = False
            wait[0] = CLEAN_FAST_S  # 已经没在答了：剩下的只发不久等
        return p

    def listed(*args: str) -> list[str] | None:
        p = run(*args)
        return None if p is None else [n for n in p.stdout.decode().split() if n]

    run("rm", "-f", "-v", sid)
    for role in ("sandbox", "gate"):
        ps = "ps", "-a", "--format", "{{.Names}}"
        found = listed(*ps, "--filter", f"label={LABEL}={sid}", "--filter", f"label={ROLE}={role}")
        for name in found or []:
            if name != sid:
                run("rm", "-f", "-v", name)
    nets = listed("network", "ls", "--filter", f"label={LABEL}={sid}", "--format", "{{.Name}}")
    for net in nets if nets is not None else [f"{sid}-net", f"{sid}-up-net"]:  # 没问到就按名字删
        if not _drop_net(net, wait[0]):
            answered = False
            wait[0] = CLEAN_FAST_S
    return answered


def _running(name: str) -> bool:
    p = _docker("inspect", "--type", "container", "--format", "{{.State.Running}}", name, check=False)
    return p.returncode == 0 and p.stdout.decode().strip() == "true"


def _owned(name: str) -> str | None:
    """容器带本层标签时返回它的属主，否则 None：不是本层建的东西一律不碰。"""
    p = _docker(
        "inspect",
        "--type",
        "container",
        "--format",
        f'{{{{index .Config.Labels "{LABEL}"}}}}|{{{{index .Config.Labels "{OWNER}"}}}}',
        name,
        check=False,
    )
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
        self._envs: dict[str, dict[str, Any]] = {}

    def start(
        self,
        name: str,
        image: str,
        env: dict[str, str] | None = None,
        command: list[str] | None = None,
        ready_port: int | None = None,
        ready_timeout_s: float = 30.0,
    ) -> str:
        if name in self._envs or _docker("inspect", "--type", "container", name, check=False).returncode == 0:
            raise ValueError(f"环境容器 {name} 已存在")
        args = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{LABEL}={name}",
            "--label",
            f"{OWNER}={self.owner}",
            "--label",
            f"{ROLE}=env",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            "512m",
        ]
        for k, v in sorted((env or {}).items()):
            args += ["--env", f"{k}={v}"]
        try:
            _docker(*args, image, *(command or []))
        except BaseException:
            _docker("rm", "-f", "-v", name, check=False)
            raise
        self._envs[name] = {
            "image": image,
            "env": dict(env or {}),
            "command": list(command or []),
            "ready_port": ready_port,
            "ready_timeout_s": ready_timeout_s,
        }
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
        p = _docker(
            "inspect",
            "--type",
            "container",
            "--format",
            "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}",
            name,
            check=False,
        )
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

    def __exit__(self, *exc: object) -> None:
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

    ps = _docker(
        "ps", "-a", "--filter", f"label={LABEL}", "--format", f'{{{{.Names}}}} {{{{.Label "{OWNER}"}}}}', check=False
    )
    names = dead(ps.stdout.decode())
    for n in names:
        _docker("rm", "-f", "-v", n, check=False)
    nets = _docker(
        "network",
        "ls",
        "--filter",
        f"label={LABEL}",
        "--format",
        f'{{{{.Name}}}} {{{{.Label "{OWNER}"}}}}',
        check=False,
    )
    for n in dead(nets.stdout.decode()):
        for member in _net_members(n):  # 目标容器还接在上面时网络删不掉
            _docker("network", "disconnect", "-f", n, member, check=False)
        _docker("network", "rm", n, check=False)
    return names
