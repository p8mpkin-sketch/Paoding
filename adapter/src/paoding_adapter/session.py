"""会话运行器（§3.4.2 的五件职责、3.4.4 的容错三级与心跳）。

状态机：leased → preparing → running → collecting → released；
异常出口：expired（Adapter 自身死掉，由哮天犬回收）、killed(budget)、failed(原因)。

1. 渲染任务包并留档（authored，producer.session = 租约 id）。
2. 起停 CLI，读事件流：只用于存档与存活判断，不从中解析结论。
3. 托管三个代理工具（ToolHost 挂到工具端点）。
4. 续租：进程存活且事件流 stall_s 内有新事件，每 renew_s 续一次；否则终止，failed(stalled)。
5. 收尾：从未 submit 过 → 追加一轮收尾（--resume）；仍无 → failed(no_output)。保存会话记录，释放租约。
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from paoding_executor.contract import ExecPort, compile_spec
from paoding_graph.contract import BlobPort, GraphPort, GraphReader, TokenIssuer

from . import backend as be
from .mcp import ToolEndpoint
from .package import MEDIA_TYPE, render
from .proxy import EndpointProxy
from .tools import Session, ToolHost

TTL_S = 120
OUTCOME = {"found": "done", "nothing": "nothing", "unsolved": "nothing", "failed": "failed"}


@dataclass
class AdapterConfig:
    root: Path                              # 每个会话一个子目录：workspace/ 与会话文件
    adapter_id: str = "ad1"
    renew_s: float = 60.0
    stall_s: float = 600.0
    max_turns: int = 40
    binding: be.CliBinding = field(default_factory=be.CliBinding)
    extra_env: dict = field(default_factory=dict)       # 只供假 CLI 的脚本路径等测试用途
    judges_cfg: dict = field(default_factory=dict)
    bases: dict = field(default_factory=dict)           # Problem.env.base（基础规格名）→ 镜像；没有登记的按原名用
    env_for: Callable[[dict], dict] | None = None       # 按租约追加 CLI 进程的环境变量（假 CLI 按角色取脚本）


@dataclass
class SessionRecord:
    lease_id: str
    status: str = "leased"
    events: list = field(default_factory=list)
    rounds: int = 0
    exit_codes: list = field(default_factory=list)
    package_ref: str | None = None
    transcript_ref: str | None = None
    release: dict | None = None


def local_launcher(argv: list[str], env: dict, cwd: Path) -> subprocess.Popen:
    """宿主机子进程：只给假 CLI 的测试台与空配置的组装根用。真实后端走 container.py 的 ContainerLauncher。

    launcher 的约定：调用返回与 Popen 同形的对象（stdout、poll、wait）。它还可以带三样可选的东西，
    会话运行器有就用：属性 proxy_url 与 mcp_base（CLI 所在位置看到的端点代理与工具端点地址，缺省即本机回环上的
    真实地址）；方法 release(lease_id)（会话结束时收回它为这个会话建的东西）。返回的对象可以带
    interrupt() 与 terminate()，缺省用进程组信号。"""
    return subprocess.Popen(argv, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, start_new_session=True)


class SessionRunner:
    def __init__(self, cfg: AdapterConfig, graph: GraphPort, reader: GraphReader, blobs: BlobPort,
                 issuer: TokenIssuer, proxy: EndpointProxy, endpoint: ToolEndpoint,
                 executor: ExecPort | None = None,
                 launcher: Callable[[list, dict, Path], subprocess.Popen] = local_launcher,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg, self.graph, self.reader, self.blobs = cfg, graph, reader, blobs
        self.issuer, self.proxy, self.endpoint, self.executor = issuer, proxy, endpoint, executor
        self.launcher, self.clock = launcher, clock
        self.live: dict[str, dict] = {}         # 在途会话：哮天犬经 soft_line / kill 操作它们

    # ---------- 哮天犬的两个动作（watchdog.contract.TaskControl，结构化实现） ----------

    def soft_line(self, lease_id: str) -> None:
        """越过软线：SIGINT 结束当前回合，运行器随后以 --resume 追加一轮收尾。"""
        lv = self.live.get(lease_id)
        if lv is None or lv["closing"]:
            return
        lv["closing"] = True
        _signal(lv.get("proc"), signal.SIGINT)

    def kill(self, lease_id: str, reason: str) -> None:
        """越过硬顶、题预算耗尽、墙钟用尽或租约已过期：终止进程树，销毁执行容器。"""
        lv = self.live.get(lease_id)
        if lv is None:
            return
        lv["killed"] = reason
        if lv.get("proc") is not None:
            _terminate(lv["proc"])
        if lv.get("sandbox_id") and self.executor is not None:
            self.executor.destroy(lv["sandbox_id"])

    def run(self, pid: str, lease_id: str, *, statement: str, kits: list | None = None,
            focus: dict | None = None, sandbox_id: str | None = None) -> SessionRecord:
        rec = SessionRecord(lease_id, "preparing")
        lease = self.reader.state["leases"][lease_id]
        role = lease["kind"]
        actor = {"kind": "adapter", "id": self.cfg.adapter_id, "session": lease_id, "role": role}
        token = self.issuer.issue(actor)
        task_token = "pdt-" + secrets.token_urlsafe(24)
        sdir = self.cfg.root / lease_id
        ws = sdir / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        (sdir / "home").mkdir(exist_ok=True)
        tools = ("submit", "show") if role == "reason" else ("exec", "submit", "show")
        owned = None                                    # 本会话自己起的执行容器：会话结束即销毁（3.5.5 的 3）
        if "exec" in tools and sandbox_id is None and hasattr(self.executor, "launch"):
            sandbox_id = owned = self._launch_sandbox(pid, lease, ws)
        s = Session(pid, lease_id, role, token, ws, tools, sandbox_id if "exec" in tools else None)
        host = ToolHost(s, self.graph, self.reader, self.blobs, self.executor)
        url = self.endpoint.mount(host)
        lv = self.live[lease_id] = {"proc": None, "closing": False, "killed": None, "sandbox_id": s.sandbox_id,
                                    "env": {**self.cfg.extra_env, **(self.cfg.env_for(lease) if self.cfg.env_for else {})}}
        try:
            limits = {"budget": lease["reserve"], "max_turns": self.cfg.max_turns,
                      "ops_quota": {"facts": 20, "intents": 8}, "tools": list(tools)}
            pkg = render(self.reader.state, pid, lease, statement=statement, judges_cfg=self.cfg.judges_cfg,
                         budget=self.reader.budget(pid), kits=kits, focus=focus, limits=limits)
            rec.package_ref = self._register(token, pid, f"package:{lease_id}", pkg.as_bytes(), MEDIA_TYPE)
            (sdir / "system.md").write_text(pkg.system, encoding="utf-8")
            # CLI 在模型容器里时，它看到的端点是内部网络上的中继，不是本机回环
            seen_url = url.replace(self.endpoint.base, getattr(self.launcher, "mcp_base", None) or self.endpoint.base, 1)
            (sdir / "mcp.json").write_text(be.mcp_config(seen_url), encoding="utf-8")
            self.proxy.register_task(task_token, lease_id, pid, lease["reserve"]["usd_milli"])
            plan = be.LaunchPlan(lease_id, ws, sdir / "system.md", pkg.user, sdir / "mcp.json",
                                 proxy_tools=tools, proxy_url=getattr(self.launcher, "proxy_url", None) or self.proxy.url,
                                 task_token=task_token,
                                 max_budget_usd=lease["reserve"]["usd_milli"] / 1000, max_turns=self.cfg.max_turns)
            rec.status = "running"
            exit_status = self._round(plan, rec, pid, token)
            if exit_status is None and not lv["killed"] and (lv["closing"] or not s.submitted):
                plan.resume, plan.user_prompt = True, be.CLOSING_PROMPT        # 软线或从未 submit：收尾轮
                exit_status = self._round(plan, rec, pid, token)
            rec.status = "collecting"
            t = self.proxy.task(task_token)
            if lv["killed"]:
                exit_status = "expired" if lv["killed"] == "expired" else f"killed({lv['killed']})"
                # 过期、停机（组装根退出时收掉在途会话）与关题（并行的另一个会话已把题解掉）不是花超了：
                # 记 failed，不记 budget_exhausted
                outcome = "failed" if lv["killed"] in ("expired", "shutdown", "problem_closed") else "budget_exhausted"
            elif exit_status:
                outcome = "failed"
            elif t and t.spent_usd_milli >= t.reserve_usd_milli:
                exit_status, outcome = "killed(budget)", "budget_exhausted"
            elif not s.submitted:
                exit_status, outcome = "failed(no_output)", "failed"           # 容错第三级
            else:
                outcome = OUTCOME[s.final["outcome"]] if s.final else "done"
            final_status = exit_status or "released"
            transcript = {"lease": lease_id, "role": role, "status": final_status, "rounds": rec.rounds,
                          "exit_codes": rec.exit_codes, "events": rec.events, "tool_calls": s.calls,
                          "final": s.final, "package_ref": rec.package_ref,
                          "proxy": {"requests": t.requests if t else 0, "usd_milli": t.spent_usd_milli if t else 0}}
            data = json.dumps(transcript, ensure_ascii=False, sort_keys=True).encode()
            body = {"lease": lease_id, "outcome": outcome}
            try:
                rec.transcript_ref = self._register(token, pid, f"transcript:{lease_id}", data,
                                                    "application/vnd.paoding.session-record+json")
                body["transcript_ref"] = rec.transcript_ref
            except RegisterRefused:
                # 会话收尾时题目已关（判官或并行的另一个会话先把题解掉了）：关题后内核不再收登记，
                # 但收释放。记录已在 Blob 仓库里，租约照常释放，不留悬着的租约。
                if not self.reader.state["problems"][pid].get("closed"):
                    raise
            if s.final and s.final.get("suggestions"):
                body["suggestions"] = s.final["suggestions"]
            out = self.graph.submit(token, pid, f"release:{lease_id}", [{"op": "release", "body": body}])
            rec.release = {"outcome": outcome, "ok": out["ok"], "results": out["results"]}
            rec.status = final_status
            return rec
        finally:
            self.live.pop(lease_id, None)
            release = getattr(self.launcher, "release", None)
            if release is not None:                     # 模型容器、端点中继与它们的内部网络
                release(lease_id)
            self.proxy.revoke(task_token)
            self.endpoint.unmount(url)
            self.issuer.revoke(token)
            if owned is not None:
                self.executor.destroy(owned)

    def _launch_sandbox(self, pid: str, lease: dict, ws: Path) -> str:
        """按租约编译授权并起执行容器（§3.6.2）。上限取所服务 Intent 的 risk，Bootstrap 取 r0；
        r2 规则只在该 Intent 已获批准时编入。reason 会话不走到这里。"""
        st = self.reader.state
        p = st["problems"][pid]
        intent = st["intents"].get(lease.get("target") or "")
        ceiling = intent["risk"] if intent else "r0"
        approved = bool(intent and st.get("approvals", {}).get(intent["id"]))
        env = {**p["env"], "base": self.cfg.bases.get(p["env"]["base"], p["env"]["base"])}
        ws.chmod(0o777)                                 # 容器内进程丢了全部能力，靠目录权限写工作区
        spec = compile_spec(lease["id"].replace("_", "-"), p["scope"], env, ceiling, approved, str(ws))
        return self.executor.launch(spec, lease["id"])

    # ---------- 一轮 CLI ----------

    def _round(self, plan: be.LaunchPlan, rec: SessionRecord, pid: str, token: str) -> str | None:
        """跑一轮 CLI 到退出。返回 None 表示正常结束，否则是异常出口的状态名。"""
        rec.rounds += 1
        argv, env = self.cfg.binding.command(plan)
        lv = self.live.get(plan.lease_id, {})
        proc = self.launcher(argv, {**env, **lv.get("env", self.cfg.extra_env)}, plan.workspace)
        lv["proc"] = proc
        if lv.get("killed"):                            # 起进程前已被叫停
            _terminate(proc)
        last = [self.clock()]
        turns = [0]

        def reader():
            for line in proc.stdout:
                last[0] = self.clock()
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                rec.events.append({"round": rec.rounds, **ev})
                if ev.get("type") == "assistant":
                    turns[0] += 1
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        status = None
        next_renew = self.clock() + self.cfg.renew_s
        while proc.poll() is None:
            if lv.get("killed"):
                break
            now = self.clock()
            if now - last[0] > self.cfg.stall_s:
                status = "failed(stalled)"
            elif turns[0] > self.cfg.max_turns:
                status = "failed(max_turns)"                # 回合上限由 Adapter 计数执行（见 backend.py）
            if status:
                _terminate(proc)
                break
            if now >= next_renew:
                self.graph.submit(token, pid, f"renew:{plan.lease_id}:{rec.rounds}:{int(now * 1000)}",
                                  [{"op": "renew", "body": {"lease": plan.lease_id}}])   # TTL 沿用租约自身
                next_renew = now + self.cfg.renew_s
            time.sleep(0.05)
        t.join(timeout=5)
        rec.exit_codes.append(proc.wait())
        return status

    def _register(self, token: str, pid: str, idem: str, data: bytes, media_type: str) -> str:
        h = self.blobs.put(data)
        out = self.graph.submit(token, pid, idem, [{"op": "register_artifact", "body": {
            "hash": h, "size": len(data), "media_type": media_type, "class": "authored"}}])
        if not out["ok"]:
            raise RegisterRefused(f"登记失败：{out['results']}")
        return out["results"][0]["id"]


class RegisterRefused(RuntimeError):
    pass


def _signal(proc: subprocess.Popen | None, sig: int) -> None:
    if proc is None or proc.poll() is not None:
        return
    if sig == signal.SIGINT and hasattr(proc, "interrupt"):      # 模型容器：信号要送进容器
        proc.interrupt()
        return
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def _terminate(proc: subprocess.Popen) -> None:
    """终止：SIGTERM 终止进程树（真 CLI 退出码 143），5 秒不退再 SIGKILL。"""
    if hasattr(proc, "terminate") and not isinstance(proc, subprocess.Popen):   # 模型容器：停容器，不只是停客户端
        proc.terminate()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
