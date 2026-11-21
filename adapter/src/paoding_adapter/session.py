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
import logging
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from paoding_executor.contract import ExecSpec, SandboxPort, compile_spec
from paoding_fenjue.contract import form, in_holdout, params
from paoding_graph.contract import Actor, BlobPort, GraphPort, GraphReader, TokenIssuer

from . import activity as act
from . import backend as be
from . import creds
from .mcp import ToolEndpoint
from .package import MEDIA_TYPE, render
from .proxy import EndpointProxy
from .tools import KnowledgePort, Session, ToolHost, solve_ceiling

LOG = logging.getLogger("adapter")
CLI_STDERR = "cli.stderr.log"  # 会话目录里：CLI 的 stderr（两轮追加写）。CLI 出错时只在这里留话


def stderr_file(cwd: Path) -> IO[bytes]:
    """CLI 的 stderr 落到会话目录（cwd 是工作区，它的上一级）。调用方把返回的文件交给 Popen 后自己关掉。"""
    return open(cwd.parent / CLI_STDERR, "ab")  # noqa: SIM115  交给子进程后由调用方关


TTL_S = 120
OUTCOME = {"found": "done", "nothing": "nothing", "unsolved": "nothing", "failed": "failed"}


_LEDGER = params("H6", "h6.activity-ledger")  # 观察面上那团入账的火（炼档 001）


@dataclass
class AdapterConfig:
    root: Path  # 每个会话一个子目录：workspace/ 与会话文件
    adapter_id: str = "ad1"
    renew_s: float = 60.0
    stall_s: float = 600.0
    max_turns: int = 100  # 真实测试：40 回合不够“探索+提取+验证+提交”全流程
    binding: be.CliBinding = field(default_factory=be.CliBinding)
    extra_env: dict[str, Any] = field(default_factory=dict)  # 只供假 CLI 的脚本路径等测试用途
    judges_cfg: dict[str, Any] = field(default_factory=dict)
    bases: dict[str, Any] = field(default_factory=dict)  # Problem.env.base（基础规格名）→ 镜像；没有登记的按原名用
    env_for: Callable[[Mapping[str, Any]], dict[str, Any]] | None = (
        None  # 按租约追加 CLI 进程的环境变量（假 CLI 按角色取脚本）
    )
    # 运行时扩权开没开（设置层 grants.runtime，组装根给出读当前 Config 的函数）；开着才给会话 request_access 工具
    grants_runtime: Callable[[], bool] | None = None
    # 热加闸门（设计 §12.2 的退路）：关掉时批下来的规则不进在跑的沙箱，等下一个租约起沙箱时生效
    grants_hot: bool = True
    # 模型档案解析（宪章 03 §3.2）：(角色, 任务的 prefs.model) → 档案 {model, endpoint, key_slot}，或 None 用缺省。
    # 会话开起时解析一次，中途不变；组装根给出读设置存储的函数
    resolve_model: Callable[[str, str | None], Mapping[str, Any] | None] | None = None
    # 查资料的端口（资料库第二期）：任务有可查的资料时给会话 kb_search / kb_read；组装根接上书库
    knowledge: KnowledgePort | None = None
    # 活动入账（焚决首炼“可回放的实时性”，炼档 001）：哪些席位的会话把活动分段登记进事件账。
    # 缺省只有开放道的 solve；严格道缺省不入账，事件日志与今天逐字节相同。
    # 缺省值取功法 H6 上 h6.activity-ledger 的清单；散火（指回 h6.activity）即 ledger_roles=()。
    ledger_roles: tuple[str, ...] = field(default_factory=lambda: tuple(_LEDGER["ledger_roles"]))
    anchor_interval_s: float = float(_LEDGER["anchor_interval_s"])  # 两次入账至多隔这么久（cz 2026-11-20 定）
    anchor_cap: int = int(_LEDGER["anchor_cap"])  # 每题因入账新增的事件上限（cz 2026-11-20 定）；到了只在轮末与收尾入账


@dataclass
class SessionRecord:
    lease_id: str
    status: str = "leased"
    events: list[Any] = field(default_factory=list)
    rounds: int = 0
    exit_codes: list[Any] = field(default_factory=list)
    package_ref: str | None = None
    transcript_ref: str | None = None
    release: dict[str, Any] | None = None
    model: str = ""  # 这个会话实际用的模型 id（按任务的模型档案解析，AC6.1）
    model_profile: str | None = None


def local_launcher(argv: list[str], env: dict[str, Any], cwd: Path) -> subprocess.Popen[Any]:
    """宿主机子进程：只给假 CLI 的测试台与空配置的组装根用。真实后端走 container.py 的 ContainerLauncher。

    launcher 的约定：调用返回与 Popen 同形的对象（stdout、poll、wait）。它还可以带三样可选的东西，
    会话运行器有就用：属性 proxy_url 与 mcp_base（CLI 所在位置看到的端点代理与工具端点地址，缺省即本机回环上的
    真实地址）；方法 release(lease_id)（会话结束时收回它为这个会话建的东西）。返回的对象可以带
    interrupt() 与 terminate()，缺省用进程组信号。"""
    with stderr_file(cwd) as err:
        return subprocess.Popen(
            argv,
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=err,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


class SessionRunner:
    def __init__(
        self,
        cfg: AdapterConfig,
        graph: GraphPort,
        reader: GraphReader,
        blobs: BlobPort,
        issuer: TokenIssuer,
        proxy: EndpointProxy,
        endpoint: ToolEndpoint,
        executor: SandboxPort | None = None,
        launcher: Callable[[list[Any], dict[str, Any], Path], subprocess.Popen[Any]] = local_launcher,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cfg, self.graph, self.reader, self.blobs = cfg, graph, reader, blobs
        self.issuer, self.proxy, self.endpoint, self.executor = issuer, proxy, endpoint, executor
        self.launcher, self.clock = launcher, clock
        self.live: dict[str, dict[str, Any]] = {}  # 在途会话：哮天犬经 soft_line / kill 操作它们

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

    def run(
        self,
        pid: str,
        lease_id: str,
        *,
        statement: str,
        kits: list[Any] | None = None,
        focus: dict[str, Any] | None = None,
        sandbox_id: str | None = None,
    ) -> SessionRecord:
        rec = SessionRecord(lease_id, "preparing")
        lease = self.reader.state["leases"][lease_id]
        role = lease["kind"]
        actor: Actor = {"kind": "adapter", "id": self.cfg.adapter_id, "session": lease_id, "role": role}
        token = self.issuer.issue(actor)
        task_token = "pdt-" + secrets.token_urlsafe(24)
        sdir = self.cfg.root / lease_id
        ws = sdir / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        (sdir / "home").mkdir(exist_ok=True)
        # 会话形态（功法 H1 的清单，paoding_fenjue）：带哪些工具、要不要接力、以什么收尾。
        # 独行（开放道，open-lane §3.2）一个会话做到底，交付即结束，接力时拷上一个会话的工作区；三段式写论断、交判官
        shape = form(role, pid)
        tools: tuple[str, ...] = tuple(shape["tools"])
        if shape["relay"]:
            self._relay(pid, lease_id, ws, shape["relay"])
        face = params("H3", "h3.base")
        if self.cfg.grants_runtime and self.cfg.grants_runtime():  # 运行时扩权开着才给申请工具
            tools += (face["grant_tool"],)
        kb = self.cfg.knowledge
        if kb is not None and kb.available(pid):  # 知识选项不是“不用”、范围里有可检索的资料
            tools += tuple(params("H3", "h3.kb")["tools"])
        owned = None  # 本会话自己起的执行容器：会话结束即销毁（3.5.5 的 3）
        if "exec" in tools and sandbox_id is None and hasattr(self.executor, "launch"):
            sandbox_id = owned = self._launch_sandbox(pid, lease, ws)
        s = Session(pid, lease_id, role, token, ws, tools, sandbox_id if "exec" in tools else None)
        s.kb_cite = shape["kb_cite"]
        s.secrets = creds.found(statement)  # 原话里的凭据：写进扩权申请与交付之前逐字遮盖（creds.py）
        host = ToolHost(
            s,
            self.graph,
            self.reader,
            self.blobs,
            self.executor,
            access=lambda: self.reconcile(lease_id),
            knowledge=kb if "kb_search" in tools else None,
        )
        url = self.endpoint.mount(host)
        log = act.ActivityLog(sdir, s.secrets, lease_id)  # 实时活动（工作台轮询 activity()；原话里的凭据先遮盖）
        lv = self.live[lease_id] = {
            "proc": None,
            "closing": False,
            "killed": None,
            "sandbox_id": s.sandbox_id,
            "ws": ws,
            "env": {**self.cfg.extra_env, **(self.cfg.env_for(lease) if self.cfg.env_for else {})},
            "activity": log,
            "started": time.time(),
            "task_token": task_token,
            "rec": rec,
            "role": role,
            # 入账与否：部署的开关（散火即 ledger_roles=()），再看这道题在 H6 上是否分在常设留出（F5，留出的是
            # #115 原样的 h6.activity，不入账）
            "ledger": self._ledgered(pid, role),
            "ledgered": self._ledgered(pid, role),
            "anchor_at": self.clock(),
            "anchor_lock": threading.Lock(),
        }
        try:
            limits = {
                "budget": lease["reserve"],
                "max_turns": self.cfg.max_turns,
                "ops_quota": {"facts": 20, "intents": 8},
                "tools": list(tools),
            }
            pkg = render(
                self.reader.state,
                pid,
                lease,
                statement=statement,
                judges_cfg=self.cfg.judges_cfg,
                budget=self.reader.budget(pid),
                kits=kits,
                focus=focus,
                limits=limits,
            )
            rec.package_ref = self._register(token, pid, f"package:{lease_id}", pkg.as_bytes(), MEDIA_TYPE)
            (sdir / "system.md").write_text(pkg.system, encoding="utf-8")
            # CLI 在模型容器里时，它看到的端点是内部网络上的中继，不是本机回环
            seen_url = url.replace(
                self.endpoint.base, getattr(self.launcher, "mcp_base", None) or self.endpoint.base, 1
            )
            (sdir / "mcp.json").write_text(be.mcp_config(seen_url), encoding="utf-8")
            prof = self._model(pid, role)
            rec.model = str(prof.get("model") or self.cfg.binding.model)
            rec.model_profile = prof.get("name")
            self.proxy.register_task(
                task_token,
                lease_id,
                pid,
                lease["reserve"]["usd_milli"],
                upstream=str(prof.get("endpoint") or ""),
                key_slot=str(prof.get("key_slot") or ""),
                fmt=str(prof.get("format") or "anthropic"),
            )
            plan = be.LaunchPlan(
                lease_id,
                ws,
                sdir / "system.md",
                pkg.user,
                sdir / "mcp.json",
                proxy_tools=tools,
                proxy_url=getattr(self.launcher, "proxy_url", None) or self.proxy.url,
                task_token=task_token,
                max_budget_usd=lease["reserve"]["usd_milli"] / 1000,
                max_turns=self.cfg.max_turns,
                model=str(prof.get("model") or ""),
            )
            rec.status = "running"
            exit_status = self._round(plan, rec, pid, token)
            delivers = shape["ends_on"] == "deliver"
            reviews = shape["ends_on"] == "review"
            if delivers:
                # 开放道的收尾轮（open-lane §3.3）：软线（预算或墙钟到 90%）→ 立即交付；没交付就结束 → 交付或留笔记接力
                if exit_status is None and not lv["killed"] and (lv["closing"] or not s.delivered):
                    plan.resume = True
                    plan.user_prompt = be.SOLVE_CLOSING_BUDGET if lv["closing"] else be.SOLVE_CLOSING_RELAY
                    exit_status = self._round(plan, rec, pid, token)
            elif reviews:
                # 复核会话（体质修炼 002）：软线或没交回读数就结束 → 一轮收尾，交回已核到的部分。不接力、不重试
                if exit_status is None and not lv["killed"] and (lv["closing"] or not s.reviewed):
                    plan.resume, plan.user_prompt = True, be.REVIEW_CLOSING
                    exit_status = self._round(plan, rec, pid, token)
            elif exit_status is None and not lv["killed"] and (lv["closing"] or not s.submitted):
                plan.resume, plan.user_prompt = True, be.CLOSING_PROMPT  # 软线或从未 submit：收尾轮
                exit_status = self._round(plan, rec, pid, token)
            rec.status = "collecting"
            self._anchor(lease_id, pid, token)  # 收尾：没入账的活动最后入一次，赶在释放租约之前（关题后内核不收登记）
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
            elif delivers:  # 交付了即 done；没交付即 nothing，司南按接力上限再派下一个求解会话
                outcome = "done" if s.delivered else "nothing"
            elif reviews:  # 交回读数即 done；没交回即 nothing，这次交付不再复核（/work 不再派）
                outcome = "done" if s.reviewed else "nothing"
            elif not s.submitted:
                exit_status, outcome = "failed(no_output)", "failed"  # 容错第三级
            else:
                outcome = OUTCOME[s.final["outcome"]] if s.final else "done"
            final_status = exit_status or "released"
            transcript = {
                "lease": lease_id,
                "role": role,
                "status": final_status,
                "rounds": rec.rounds,
                "exit_codes": rec.exit_codes,
                "events": rec.events,
                "tool_calls": s.calls,
                "final": s.final,
                **({"delivered": s.delivered} if delivers else {}),
                **({"reviewed": s.reviewed} if reviews else {}),
                "package_ref": rec.package_ref,
                "proxy": {"requests": t.requests if t else 0, "usd_milli": t.spent_usd_milli if t else 0},
            }
            data = json.dumps(transcript, ensure_ascii=False, sort_keys=True).encode()
            body = {"lease": lease_id, "outcome": outcome}
            try:
                rec.transcript_ref = self._register(
                    token, pid, f"transcript:{lease_id}", data, "application/vnd.paoding.session-record+json"
                )
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
            self._end_activity(lease_id, sdir)
            self.live.pop(lease_id, None)
            release = getattr(self.launcher, "release", None)
            if release is not None:  # 模型容器、端点中继与它们的内部网络
                release(lease_id)
            self.proxy.revoke(task_token)
            self.endpoint.unmount(url)
            self.issuer.revoke(token)
            if owned is not None and self.executor is not None:  # owned 只在起过执行容器时才有
                self.executor.destroy(owned)

    # ---------- 实时活动（工作台的“会话活动”面板） ----------

    def activity(self, lease_id: str, after: int = 0, as_of: int | None = None) -> dict[str, Any] | None:
        """一个会话的活动：在途的从内存读，结束了的从会话目录读。没有这个会话（或目录已清掉）返回 None。
        耗时按本进程的墙钟、花费取端点代理给这个任务令牌记的账（与 cost 事件同一个计量）。

        as_of 给出时是回放：只从事件账里那个 seq 及之前入账的段重建（链校验不过抛 activity.ChainBroken），
        与实时面板当时已入账的部分逐字节相同。`anchored_through` 是已入账的最后一个序号（None：这个会话不入账）。"""
        lease = self.reader.state["leases"].get(lease_id)
        if as_of is not None:
            items = self.ledger_items(lease_id, as_of)
            if items is None:
                return None
            head = {
                "lease": lease_id,
                "role": lease["kind"] if lease else None,
                "live": False,
                "status": "replay",
                "as_of": as_of,
                "rounds": max((int(x.get("round", 0)) for x in items), default=0),
                "model": "",
                "elapsed_s": 0,
                "spent_usd_milli": 0,
                "closing": False,
            }
            return {**head, **act.view(items, after, anchored=len(items)), "now": None}
        lv = self.live.get(lease_id)
        sdir = self.cfg.root / lease_id
        if lv is not None and "activity" in lv:
            t = self.proxy.task(lv["task_token"])
            rec = lv["rec"]
            log: act.ActivityLog = lv["activity"]
            head = {
                "lease": lease_id,
                "role": lv["role"],
                "live": True,
                "status": rec.status,
                "rounds": rec.rounds,
                "model": rec.model,
                "elapsed_s": max(0, int(time.time() - lv["started"])),
                "spent_usd_milli": t.spent_usd_milli if t else 0,
                "closing": bool(lv["closing"]),
            }
            anchored = log.anchored if lv.get("ledgered") else None
            return {**head, **act.view(log.snapshot(), after, anchored=anchored)}
        try:
            ledger = self.ledger_items(lease_id)
        except act.ChainBroken:
            ledger = None  # 账上的段对不上：不认它，退回会话目录里的流水，且不标“已入账”
        files = act.read_items(sdir) if sdir.is_dir() else []
        if ledger is None and (not sdir.is_dir() or not (sdir / act.FILE).exists() and act.read_end(sdir) is None):
            return None
        items = files
        if ledger is not None and [x.get("h") for x in files[: len(ledger)]] != [x["h"] for x in ledger]:
            items = ledger  # 会话目录里的流水与账上的对不上（或已清掉）：以账为准
        end = (act.read_end(sdir) if sdir.is_dir() else None) or {}
        head = {
            "lease": lease_id,
            "role": end.get("role", lease["kind"] if lease else None),
            "live": False,
            "status": end.get("status", "ended"),
            "rounds": end.get("rounds", 0),
            "model": end.get("model", ""),
            "elapsed_s": end.get("elapsed_s", 0),
            "spent_usd_milli": end.get("spent_usd_milli", 0),
            "closing": False,
        }
        anchored = len(ledger) if ledger is not None else None
        return {**head, **act.view(items, after, anchored=anchored), "now": None}  # 结束了就没有“正在做”

    def _maybe_anchor(self, lease_id: str, pid: str, token: str, new: list[dict[str, Any]]) -> None:
        """锚点：exec 返回、一轮结束、或距上次入账已满间隔。每题入账数到了上限，就只在一轮结束时入账。"""
        lv = self.live.get(lease_id)
        if lv is None:
            return
        round_end = any(x["kind"] == "end" for x in new)
        exec_back = any(x["kind"] == "result" and "artifact" in x for x in new)
        due = self.clock() - lv["anchor_at"] >= self.cfg.anchor_interval_s
        if not (round_end or exec_back or due):
            return
        if not round_end and self._segments_in(pid) >= self.cfg.anchor_cap:
            return
        self._anchor(lease_id, pid, token)

    def _ledgered(self, pid: str, role: str) -> bool:
        roles = self.cfg.ledger_roles
        if in_holdout(pid, "H6"):  # 留出的火（h6.activity）在这道题上顶替入账的那团：照它的清单
            roles = tuple(r for r in roles if r in params("H6", "h6.activity-ledger", pid).get("ledger_roles", []))
        return role in roles

    def _segments_in(self, pid: str) -> int:
        arts = self.reader.state["artifacts"].values()
        return sum(1 for a in arts if a["problem_id"] == pid and a.get("media_type") == act.SEGMENT_MEDIA)

    def _anchor(self, lease_id: str, pid: str, token: str) -> None:
        """把自上一锚点以来的活动作为一段登记（authored 类，parents 指上一段）。题已关、登记被拒就停止入账。"""
        lv = self.live.get(lease_id)
        if lv is None or not lv.get("ledger"):
            return
        log: act.ActivityLog = lv["activity"]
        with lv["anchor_lock"]:
            seg = log.segment()
            if seg is None:
                return
            data, last = seg
            try:
                aid = self._register(
                    token, pid, f"activity:{lease_id}:{last}", data, act.SEGMENT_MEDIA, parents=log.segments[-1:]
                )
            except RegisterRefused:
                lv["ledger"] = False  # 题已关或令牌已撤：这一会话不再入账，活动仍在会话目录里
                return
            log.mark(last, aid)
            lv["anchor_at"] = self.clock()

    def segments(self, lease_id: str, as_of: int | None = None) -> list[str]:
        """事件账里这个会话的入账段（按登记顺序）；as_of 给出时只认那个 seq 及之前登记的。"""
        lease = self.reader.state["leases"].get(lease_id)
        if lease is None:
            return []
        out = [
            a
            for a in self.reader.state["artifacts"].values()
            if a["problem_id"] == lease["problem_id"]
            and a.get("media_type") == act.SEGMENT_MEDIA
            and a.get("producer", {}).get("session") == lease_id
            and (as_of is None or int(a["id"][2:]) <= as_of)
        ]
        return [a["id"] for a in sorted(out, key=lambda a: int(a["id"][2:]))]

    def ledger_items(self, lease_id: str, as_of: int | None = None) -> list[dict[str, Any]] | None:
        """从事件账重建的活动条目；没有入账段返回 None。链对不上抛 activity.ChainBroken。"""
        ids = self.segments(lease_id, as_of)
        if not ids:
            return None
        arts = self.reader.state["artifacts"]
        return act.replay_segments(self.blobs.get(arts[i]["hash"]) for i in ids)

    def _end_activity(self, lease_id: str, sdir: Path) -> None:
        lv = self.live.get(lease_id)
        if lv is None or "activity" not in lv:
            return
        t = self.proxy.task(lv["task_token"])
        rec = lv["rec"]
        doc = {
            "role": lv["role"],
            "status": rec.status,
            "rounds": rec.rounds,
            "model": rec.model,
            "elapsed_s": max(0, int(time.time() - lv["started"])),
            "spent_usd_milli": t.spent_usd_milli if t else 0,
        }
        try:
            (sdir / act.END_FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _relay(self, pid: str, lease_id: str, ws: Path, how: bool | str = True) -> None:
        """开放道的接力（open-lane §3.2）：把本题上一个求解会话的工作区（含它的 NOTES.md）拷进新会话的工作区。
        每个会话仍有自己的会话目录与工作区（容器启动器按目录名认租约），接力只是拷贝，不共用目录。
        how="delivery"（复核会话）：拷的是交出租约目标那次交付的求解会话的工作区，复核在副本上重跑，不碰原件。"""
        st = self.reader.state
        lease = st["leases"][lease_id]
        if how == "delivery":
            d = next((x for x in st["problems"][pid].get("deliveries") or [] if x["id"] == lease.get("target")), None)
            src_id = d.get("lease") if d else None
            prev = [st["leases"][src_id]] if src_id and src_id in st["leases"] else []
        else:
            kind = lease["kind"]  # 同一席位的上一个会话
            prev = sorted(
                (
                    l
                    for l in st["leases"].values()
                    if l["problem_id"] == pid and l["kind"] == kind and l["id"] != lease_id and not l["active"]
                ),
                key=lambda l: l["ended_seq"],
            )
        if not prev:
            return
        src = self.cfg.root / prev[-1]["id"] / "workspace"
        if src.is_dir():
            shutil.copytree(src, ws, dirs_exist_ok=True, symlinks=True)

    def _model(self, pid: str, role: str) -> Mapping[str, Any]:
        """这个会话用哪个模型档案：任务的 prefs.model 优先，否则按设置层的角色路由（宪章 03 §3.2）。
        没有接设置层（resolve_model 为 None）或解析不到时返回空，沿用 CliBinding 与代理的缺省。"""
        if self.cfg.resolve_model is None:
            return {}
        want = (self.reader.state["problems"][pid].get("prefs") or {}).get("model")
        try:
            return self.cfg.resolve_model(role, want) or {}
        except KeyError as e:  # 开题后档案被删掉：按角色路由退回，记一笔
            LOG.warning("会话的模型档案解析不到（%s），按角色路由", e)
            try:
                return self.cfg.resolve_model(role, None) or {}
            except KeyError:
                return {}

    def _launch_sandbox(self, pid: str, lease: Mapping[str, Any], ws: Path) -> str:
        """按租约编译授权并起执行容器（§3.6.2）。reason 会话不走到这里。"""
        ws.chmod(0o777)  # 容器内进程丢了全部能力，靠目录权限写工作区
        spec = self._spec(pid, lease, ws)
        assert self.executor is not None  # 调用方已查过 executor 有 launch
        sid: str = self.executor.launch(spec, lease["id"])
        return sid

    def reconcile(self, lease_id: str) -> dict[str, Any] | None:
        """运行时扩权（docs/design/runtime-grants/ §5）：按当前的 Problem.scope 重编这个会话的授权，
        把在跑的沙箱的闸门对齐过去（热加、热撤销）。执行器不支持热对齐时返回 None，等下一个租约。"""
        lv = self.live.get(lease_id)
        hot = getattr(self.executor, "reconcile", None)
        if lv is None or not lv.get("sandbox_id") or hot is None or not self.cfg.grants_hot:
            return None
        lease = self.reader.state["leases"][lease_id]
        out: dict[str, Any] = hot(lv["sandbox_id"], self._spec(lease["problem_id"], lease, lv["ws"]))
        if out.get("added") or out.get("removed"):
            LOG.info("会话 %s 的出站闸门已对齐：新增 %s，撤下 %s", lease_id, out.get("added"), out.get("removed"))
        return out

    def _spec(self, pid: str, lease: Mapping[str, Any], ws: Path) -> ExecSpec:
        """编译授权：上限取所服务 Intent 的 risk，Bootstrap 取 r0，开放道的 solve 取 r1（只含人批过的规则）；
        r2 规则只在该 Intent 已获批准时编入；
        Intent 声明了 touches 时只编入其中的规则；已撤销的规则不编入（compile_spec 跳过）。"""
        st = self.reader.state
        p = st["problems"][pid]
        intent = st["intents"].get(lease.get("target") or "")
        ceiling = intent["risk"] if intent else solve_ceiling(lease)
        approved = bool(intent and st.get("approvals", {}).get(intent["id"]))
        env = {**p["env"], "base": self.cfg.bases.get(p["env"]["base"], p["env"]["base"])}
        touches = intent.get("touches") if intent else None  # add_intent 已校验，这里只取用
        only = None if touches is None else frozenset(t["rule"] for t in touches)
        return compile_spec(lease["id"].replace("_", "-"), p["scope"], env, ceiling, approved, str(ws), only=only)

    # ---------- 一轮 CLI ----------

    def _round(self, plan: be.LaunchPlan, rec: SessionRecord, pid: str, token: str) -> str | None:
        """跑一轮 CLI 到退出。返回 None 表示正常结束，否则是异常出口的状态名。"""
        rec.rounds += 1
        argv, env = self.cfg.binding.command(plan)
        lv = self.live.get(plan.lease_id, {})
        try:
            proc = self.launcher(argv, {**env, **lv.get("env", self.cfg.extra_env)}, plan.workspace)
        except OSError as e:  # 命令不存在、没有执行权限等：记下来，按失败释放租约，不让租约悬到过期
            msg = f"CLI 起不来：{argv[0]}：{type(e).__name__}: {e}\n"
            with stderr_file(plan.workspace) as err:
                err.write(msg.encode("utf-8"))
            LOG.error("会话 %s %s", plan.lease_id, msg.strip())
            rec.exit_codes.append(-1)
            return "failed(launch)"
        lv["proc"] = proc
        if lv.get("killed"):  # 起进程前已被叫停
            _terminate(proc)
        last = [self.clock()]
        turns = [0]

        stdout = proc.stdout
        assert stdout is not None  # 启动器总以 stdout=PIPE 起 CLI

        def reader() -> None:
            for line in stdout:
                last[0] = self.clock()
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                rec.events.append({"round": rec.rounds, **ev})
                if "activity" in lv and isinstance(ev, dict):
                    new = lv["activity"].feed(ev, rec.rounds)
                    if new and lv.get("ledger"):
                        self._maybe_anchor(lv["activity"].lease, pid, token, new)
                if ev.get("type") == "assistant":
                    turns[0] += 1

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        status = None
        next_renew = self.clock() + self.cfg.renew_s
        scope_seen = _scope_sig(self.reader.state, pid)
        while proc.poll() is None:
            if lv.get("killed"):
                break
            sig = _scope_sig(self.reader.state, pid)
            if sig != scope_seen:  # 有人批了或撤了一条规则：在跑的沙箱即时对齐（热加、热撤销）
                scope_seen = sig
                self.reconcile(plan.lease_id)
            now = self.clock()
            if now - last[0] > self.cfg.stall_s:
                status = "failed(stalled)"
            elif turns[0] > self.cfg.max_turns:
                status = "failed(max_turns)"  # 回合上限由 Adapter 计数执行（见 backend.py）
            if status:
                _terminate(proc)
                break
            if now >= next_renew:
                self.graph.submit(
                    token,
                    pid,
                    f"renew:{plan.lease_id}:{rec.rounds}:{int(now * 1000)}",
                    [{"op": "renew", "body": {"lease": plan.lease_id}}],
                )  # TTL 沿用租约自身
                next_renew = now + self.cfg.renew_s
            time.sleep(0.05)
        t.join(timeout=5)
        rec.exit_codes.append(proc.wait())
        if status or rec.exit_codes[-1] != 0:
            tail = _tail(plan.workspace.parent / CLI_STDERR)
            LOG.warning(
                "会话 %s 第 %d 轮异常结束（%s，退出码 %s）。CLI stderr 在 %s%s",
                plan.lease_id,
                rec.rounds,
                status or "exit",
                rec.exit_codes[-1],
                plan.workspace.parent / CLI_STDERR,
                f"，末尾：{tail}" if tail else "（空）",
            )
        return status

    def _register(
        self, token: str, pid: str, idem: str, data: bytes, media_type: str, parents: list[str] | None = None
    ) -> str:
        h = self.blobs.put(data)
        out = self.graph.submit(
            token,
            pid,
            idem,
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": h,
                        "size": len(data),
                        "media_type": media_type,
                        "class": "authored",
                        **({"parents": parents} if parents else {}),
                    },
                }
            ],
        )
        if not out["ok"]:
            raise RegisterRefused(f"登记失败：{out['results']}")
        aid: str = out["results"][0]["id"]
        return aid


def _scope_sig(state: Mapping[str, Any], pid: str) -> tuple[Any, ...]:
    """授权范围的指纹：规则条数与已撤销的下标。范围只追加、撤销只打标记，所以这两样变了范围才变了。"""
    scope = state["problems"][pid]["scope"]
    return (len(scope), tuple(k for k, r in enumerate(scope) if "revoked" in r))


class RegisterRefused(RuntimeError):
    pass


def _signal(proc: subprocess.Popen[Any] | None, sig: int) -> None:
    if proc is None or proc.poll() is not None:
        return
    if sig == signal.SIGINT and hasattr(proc, "interrupt"):  # 模型容器：信号要送进容器
        proc.interrupt()
        return
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def _terminate(proc: subprocess.Popen[Any]) -> None:
    """终止：SIGTERM 终止进程树（真 CLI 退出码 143），5 秒不退再 SIGKILL。"""
    if hasattr(proc, "terminate") and not isinstance(proc, subprocess.Popen):  # 模型容器：停容器，不只是停客户端
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


def _tail(path: Path, n: int = 800) -> str:
    try:
        data = path.read_bytes()[-n:]
    except OSError:
        return ""
    return data.decode("utf-8", "replace").strip()
