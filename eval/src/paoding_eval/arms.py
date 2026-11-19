"""瘦基线的三条对照臂（规格 A2、§8.3）：baseline（B1）、Bk、Bn。三者共用一个核心：若干轮、每轮若干个
独立的 CLI 尝试，每个尝试都在 baseline 沙箱里跑（box.py：与 full 同一套执行层网络与闸门），同一个端点代理计量。

| 臂 | 每轮 | 轮数 | 共享 | 何时停 |
| --- | --- | --- | --- | --- |
| baseline（B1） | 1 个尝试 | 1 | 无 | 跑完 |
| Bk（等成本独立重试） | 1 个尝试 | 到预算或上限 | 无：每次新沙箱、新工作区 | 任一次解出，或花费到预算 |
| Bn（共享笔记） | W 个并行尝试 | 到预算或上限 | 只追加的 NOTES.md：轮初拷进各工作区，轮末收回追加部分 | 同上 |

规格的用意：独立重试本身就能涨解题率，所以庖丁要赢 Bk 才说明共享状态有价值；赢 Bn 才说明图和等级有价值。
Bk 与 Bn 的预算取 full 臂的每题成本（`--budget-usd`），这就是"等成本"。预算在每轮开始前检查；轮内每个尝试的
端点代理预留取剩余预算的均分，代理到额即拒（429），所以一臂的总花费不会明显越过预算。

终态：任一尝试解出即 solved；全部尝试都 failed（CLI 出错、超时、被代理拒）即 failed；否则 unsolved。
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paoding_adapter.contract import FAKE_CLI, EndpointProxy, FakeUpstream, PriceTable, ProxyConfig, fake_program

from .box import PD_DIR, BaselineBox, write_connects
from .harness import NATIVE_TOOLS, PRICES, MeteringLedger, empty_mcp_config, run_cli
from .record import Record, log_dir_field, run_dirname, stamp
from .spec import ProblemSpec, sha256_hex

NOTES = "NOTES.md"
NOTES_PROMPT = (
    f"协作：工作目录里的 {NOTES} 是与其他协作者共享的笔记（他们在别的环境里同时解同一道题）。"
    f"先读它；有了发现（试过什么、结果如何、下一步建议）就追加到 {NOTES} 末尾。只追加，不要改动已有内容。"
)
Steps = list[dict[str, Any]] | Callable[[int, int], list[dict[str, Any]]]  # 假 CLI 的步骤，或 (轮, 第几个) → 步骤


@dataclass
class Backend:
    """一臂共用的上游、端点代理与计量账。干跑时是假上游与假 CLI。"""

    dry: bool
    program: list[str]
    model_name: str
    cli_model: str
    ledger: MeteringLedger = field(default_factory=MeteringLedger)
    proxy: Any = None
    proxy_port: int = 0
    upstream: Any = None

    @classmethod
    def open(
        cls,
        mode: str,
        *,
        real_program: list[str] | None,
        upstream_url: str,
        api_key: str,
        model: str,
        usage: dict[str, Any] | None,
        pid: str = "",
        cap_milli: int | None = None,
    ) -> Backend:
        """cap_milli：一臂的等成本预算。交给代理作这道题的硬顶，全臂的尝试共用：累计花费到额后代理不再放行新请求。"""
        dry = real_program is None
        if dry:
            up = FakeUpstream(usage)
            b = cls(True, fake_program(), model or "fake/claude-sonnet-5-5", "", upstream=up)
            url, key = up.url, "sk-fake-upstream"
        else:
            b = cls(False, list(real_program or []), model, model)
            url, key = upstream_url, api_key
        b.proxy = EndpointProxy(
            ProxyConfig(
                url,
                key,
                f"eval-{mode}",
                global_cap_usd_milli=1_000_000_000,
                problem_caps={pid: cap_milli} if cap_milli is not None else {},
            ),
            PriceTable.load(PRICES),
            b.ledger,
        )
        _, b.proxy_port = b.proxy.serve()
        return b

    def spent_milli(self, task_id: str | None = None) -> int:
        if task_id is None:
            return self.ledger.usd_milli
        return sum(int(c.get("usd_milli", 0)) for c in self.ledger.costs if c.get("task_id") == task_id)

    def max_request_milli(self) -> int:
        """本臂至今单次请求的最高花费：下一轮按它估每个尝试至少要多少钱。还没有请求时为 0。"""
        return max((int(c.get("usd_milli", 0)) for c in self.ledger.costs), default=0)

    def close(self) -> None:
        if self.proxy is not None:
            self.proxy.close()
        if self.upstream is not None:
            self.upstream.close()


@dataclass
class Attempt:
    round: int
    worker: int
    dir: Path
    terminal: str
    turns: int
    usd_milli: int
    connects: int | None
    duration_s: float

    def summary(self, root: Path) -> dict[str, Any]:
        return {
            "round": self.round,
            "worker": self.worker,
            "dir": str(self.dir.relative_to(root)) if self.dir != root else ".",
            "terminal": self.terminal,
            "turns": self.turns,
            "cost_usd": self.usd_milli / 1000,
            "target_connects": self.connects,
            "duration_s": round(self.duration_s, 2),
        }


def _attempt(
    b: Backend,
    spec: ProblemSpec,
    adir: Path,
    *,
    task_id: str,
    prompt: str,
    reserve_milli: int,
    image: str,
    transport: str,
    timeout_s: float,
    steps: list[dict[str, Any]] | None,
    seed: dict[str, str] | None,
    rnd: int,
    worker: int,
) -> Attempt:
    """一个 CLI 尝试：新工作区（可预置文件），新沙箱，跑完按工作区里的 answer.txt 判定。"""
    t0 = time.monotonic()
    workspace = adir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    for name, text in (seed or {}).items():
        (workspace / name).write_text(text, encoding="utf-8")
    script: Path | None = None
    if b.dry:
        script = adir / "baseline.script.json"
        default = [{"tool": "Write", "input": {"file_path": "answer.txt", "content": spec.answer}}]
        script.write_text(json.dumps({"steps": steps or default}), encoding="utf-8")
    token = secrets.token_urlsafe(16)
    b.proxy.register_task(token, task_id, spec.id, reserve_usd_milli=reserve_milli)
    program = list(b.program)
    box: BaselineBox | None = None
    connects: int | None = None
    try:
        if image:
            box = BaselineBox(
                spec.scope,
                image,
                workspace,
                b.proxy_port,
                name=f"{adir.name[-20:]}-{secrets.token_hex(2)}",
                wall_s=int(timeout_s) + 120,
                transport=transport,
            ).__enter__()
            if b.dry:
                box.copy_in(FAKE_CLI, f"{PD_DIR}/fakecli.py")
                program = ["python", "-I", f"{PD_DIR}/fakecli.py"]
        res = run_cli(
            program,
            prompt,
            workspace=workspace,
            proxy_url=b.proxy.url,
            token=token,
            mcp_config=empty_mcp_config(adir / "mcp.json"),
            model=b.cli_model,
            fake_script=script,
            timeout_s=timeout_s,
            box=box,
        )
        if box is not None:
            connects = write_connects(box, adir / "gate.jsonl")
    finally:
        if box is not None:
            box.close()
    (adir / "cli.stream-json").write_text(res["stdout"], encoding="utf-8")
    if res["stderr"]:
        (adir / "cli.stderr").write_text(res["stderr"], encoding="utf-8")
    produced = workspace / "answer.txt"
    if res["timed_out"] or not res["ok"]:
        terminal = "failed"
    else:
        got = produced.read_text(encoding="utf-8").strip() if produced.exists() else None
        terminal = "solved" if got is not None and sha256_hex(got) == spec.expect()["sha256"] else "unsolved"
    return Attempt(rnd, worker, adir, terminal, res["turns"], b.spent_milli(task_id), connects, time.monotonic() - t0)


def round_width(
    workers: int, budget_milli: int | None, spent_milli: int, unit_milli: int, default_reserve: int
) -> tuple[int, int]:
    """本轮开几个尝试、每个的代理预留（毫美元）。返回 (0, 0) 表示预算已不够再开一轮。

    没有预算（只给了轮数）时照开 workers 个、预留取缺省。有预算时：剩余 ≤ 0 就停；
    否则按"至今单次请求的最高花费"（还没有请求时按 1 毫美元）估每个尝试至少要多少钱，剩余不够分给 workers 个
    就收窄到够分的个数，一个都不够就停。各尝试的预留之和不超过剩余，没有向上兜底。"""
    if budget_milli is None:
        return workers, default_reserve
    left = budget_milli - spent_milli
    width = min(workers, left // max(unit_milli, 1)) if left > 0 else 0
    if width <= 0:
        return 0, 0
    return width, left // width


def merge_notes(shared: str, worker_files: list[tuple[int, str | None]], rnd: int) -> tuple[str, list[int]]:
    """轮末把各 Worker 追加的部分接到共享笔记后面；改动了已有内容的，那一份整个不收（只追加）。

    返回（新的共享笔记，改动了已有内容的 Worker 序号）。"""
    out, rewrote = shared, []
    for w, text in worker_files:
        if text is None:
            continue
        if not text.startswith(shared):
            rewrote.append(w)
            continue
        add = text[len(shared) :].strip()
        if add:
            out = out.rstrip("\n") + ("\n\n" if out.strip() else "") + f"## w{w} · 第 {rnd} 轮\n\n{add}\n"
    return out, rewrote


def run_arm(
    mode: str,
    spec: ProblemSpec,
    run_no: int,
    *,
    out_root: Path,
    workers: int = 1,
    rounds: int = 1,
    budget_usd: float | None = None,
    model: str = "",
    real_program: list[str] | None = None,
    upstream_url: str = "",
    api_key: str = "",
    usage: dict[str, Any] | None = None,
    fake_steps: Steps | None = None,
    timeout_s: float = 300,
    image: str = "",
    transport: str = "",
    meta: dict[str, Any] | None = None,
) -> Record:
    """跑一条瘦基线对照臂，产出一条记录。mode 取 baseline | bk | bn；三者的差别只在 workers、rounds 与共享笔记。"""
    if mode not in ("baseline", "bk", "bn"):
        raise ValueError(f"瘦基线臂只有 baseline、bk、bn：{mode!r}")
    if real_program is not None and not image:
        raise ValueError("真题瘦基线要给沙箱镜像（--image）：CLI 在宿主上连不到题目环境，对照不成立")
    if mode != "baseline" and budget_usd is None and rounds <= 1:
        raise ValueError(f"{mode} 要给等成本预算（--budget-usd，取 full 臂的每题成本）或轮数上限（--rounds）")
    notes = mode == "bn"
    t0 = time.monotonic()
    log_dir = out_root / run_dirname(mode, spec.id, run_no, stamp())
    log_dir.mkdir(parents=True, exist_ok=True)
    budget_milli = None if budget_usd is None else int(round(budget_usd * 1000))
    default_reserve = max(int(spec.budget.get("usd_milli", 5000)), 1_000_000)
    b = Backend.open(
        mode,
        real_program=real_program,
        upstream_url=upstream_url,
        api_key=api_key,
        model=model,
        usage=usage,
        pid=spec.id,
        cap_milli=budget_milli,
    )
    attempts: list[Attempt] = []
    shared, rewrote_all, stop = "", [], ""
    widths: list[int] = []
    try:
        for rnd in range(1, rounds + 1):
            width, reserve = round_width(workers, budget_milli, b.spent_milli(), b.max_request_milli(), default_reserve)
            if width == 0:
                stop = "budget"
                break
            widths.append(width)
            prompt = spec.goal_prompt + ("\n\n" + NOTES_PROMPT if notes else "")
            seed = {NOTES: shared} if notes else None

            def go(w: int, rnd: int = rnd, reserve: int = reserve, prompt: str = prompt, seed: Any = seed) -> Attempt:
                return _attempt(
                    b,
                    spec,
                    log_dir if mode == "baseline" else log_dir / f"r{rnd}-w{w}",
                    task_id=f"{mode}-r{rnd}-w{w}",
                    prompt=prompt,
                    reserve_milli=reserve,
                    image=image,
                    transport=transport,
                    timeout_s=timeout_s,
                    steps=fake_steps(rnd, w) if callable(fake_steps) else fake_steps,
                    seed=seed,
                    rnd=rnd,
                    worker=w,
                )

            done = _round(go, width)
            attempts += done
            if notes:
                files = [(a.worker, _read(a.dir / "workspace" / NOTES)) for a in done]
                shared, rewrote = merge_notes(shared, files, rnd)
                rewrote_all += [(rnd, w) for w in rewrote]
                (log_dir / NOTES).write_text(shared, encoding="utf-8")
            if any(a.terminal == "solved" for a in done):
                stop = "solved"
                break
        else:
            stop = stop or "rounds"
    finally:
        b.close()

    if any(a.terminal == "solved" for a in attempts):
        terminal = "solved"
    elif attempts and all(a.terminal == "failed" for a in attempts):
        terminal = "failed"
    else:
        terminal = "unsolved" if attempts else "failed"
    rec = Record(
        mode=mode,
        problem=spec.id,
        run=run_no,
        model=b.model_name,
        duration_s=time.monotonic() - t0,
        terminal=terminal,
        cost_usd=b.spent_milli() / 1000,
        events=sum(a.turns for a in attempts),
        log_dir=log_dir_field(out_root, log_dir.name),
    )
    rec.write(log_dir)
    connects = [a.connects for a in attempts]
    info: dict[str, Any] = {
        **(meta or {}),
        "image": image or None,
        "sandbox": bool(image),
        "tools": list(NATIVE_TOOLS),
        "target_connects": (sum(c for c in connects if c is not None) if image else None),
    }
    if mode != "baseline":
        info |= {
            "arm": {
                "workers": workers,
                "rounds_max": rounds,
                "budget_usd": budget_usd,
                "stopped_by": stop,
                "widths": widths,
                "over_budget_milli": None if budget_milli is None else max(0, b.spent_milli() - budget_milli),
            },
            "attempts": [a.summary(log_dir) for a in attempts],
        }
        if notes:
            info["notes"] = {"bytes": len(shared.encode()), "rewrites_dropped": rewrote_all}
    (log_dir / "meta.json").write_text(json.dumps(info, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    return rec


def _round(go: Callable[[int], Attempt], workers: int) -> list[Attempt]:
    """一轮：workers 个尝试并行跑（1 个时就在本线程）。线程里的异常带回本线程再抛。"""
    if workers == 1:
        return [go(1)]
    results: list[Attempt | None] = [None] * workers
    errors: list[BaseException] = []

    def one(w: int) -> None:
        try:
            results[w - 1] = go(w)
        except BaseException as e:  # noqa: BLE001  带回主线程再抛
            errors.append(e)

    threads = [threading.Thread(target=one, args=(w,)) for w in range(1, workers + 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]
    return [a for a in results if a is not None]


def _read(p: Path) -> str | None:
    return p.read_text(encoding="utf-8") if p.exists() else None
