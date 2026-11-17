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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from paoding_executor.contract import ExecPort
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
        s = Session(pid, lease_id, role, token, ws, tools, sandbox_id if "exec" in tools else None)
        host = ToolHost(s, self.graph, self.reader, self.blobs, self.executor)
        url = self.endpoint.mount(host)
        try:
            limits = {"budget": lease["reserve"], "max_turns": self.cfg.max_turns,
                      "ops_quota": {"facts": 20, "intents": 8}, "tools": list(tools)}
            pkg = render(self.reader.state, pid, lease, statement=statement, judges_cfg=self.cfg.judges_cfg,
                         budget=self.reader.budget(pid), kits=kits, focus=focus, limits=limits)
            rec.package_ref = self._register(token, pid, f"package:{lease_id}", pkg.as_bytes(), MEDIA_TYPE)
            (sdir / "system.md").write_text(pkg.system, encoding="utf-8")
            (sdir / "mcp.json").write_text(be.mcp_config(url), encoding="utf-8")
            self.proxy.register_task(task_token, lease_id, pid, lease["reserve"]["usd_milli"])
            plan = be.LaunchPlan(lease_id, ws, sdir / "system.md", pkg.user, sdir / "mcp.json",
                                 proxy_tools=tools, proxy_url=self.proxy.url, task_token=task_token,
                                 max_budget_usd=lease["reserve"]["usd_milli"] / 1000, max_turns=self.cfg.max_turns)
            rec.status = "running"
            exit_status = self._round(plan, rec, pid, token)
            if exit_status is None and not s.submitted:
                plan.resume, plan.user_prompt = True, be.CLOSING_PROMPT        # 容错第二级：收尾轮
                exit_status = self._round(plan, rec, pid, token)
            rec.status = "collecting"
            t = self.proxy.task(task_token)
            if exit_status:
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
            rec.transcript_ref = self._register(token, pid, f"transcript:{lease_id}",
                                                json.dumps(transcript, ensure_ascii=False, sort_keys=True).encode(),
                                                "application/vnd.paoding.session-record+json")
            body = {"lease": lease_id, "outcome": outcome, "transcript_ref": rec.transcript_ref}
            if s.final and s.final.get("suggestions"):
                body["suggestions"] = s.final["suggestions"]
            out = self.graph.submit(token, pid, f"release:{lease_id}", [{"op": "release", "body": body}])
            rec.release = {"outcome": outcome, "ok": out["ok"], "results": out["results"]}
            rec.status = final_status
            return rec
        finally:
            self.proxy.revoke(task_token)
            self.endpoint.unmount(url)
            self.issuer.revoke(token)

    # ---------- 一轮 CLI ----------

    def _round(self, plan: be.LaunchPlan, rec: SessionRecord, pid: str, token: str) -> str | None:
        """跑一轮 CLI 到退出。返回 None 表示正常结束，否则是异常出口的状态名。"""
        rec.rounds += 1
        argv, env = self.cfg.binding.command(plan)
        proc = self.launcher(argv, {**env, **self.cfg.extra_env}, plan.workspace)
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
            raise RuntimeError(f"登记失败：{out['results']}")
        return out["results"][0]["id"]


def _terminate(proc: subprocess.Popen) -> None:
    """终止：SIGTERM 终止进程树（真 CLI 退出码 143），5 秒不退再 SIGKILL。"""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
