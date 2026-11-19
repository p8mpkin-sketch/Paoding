"""评测运行器（规格 §8 D14）：baseline 与 full 两种模式。一次运行产出一条固定格式的记录。

- baseline（单 CLI 直连，即规格里的 B1）：单个 CLI 会话，原生工具面，直连端点代理计量；没有图服务编排。
  终态由本地 exact_match 判定（答案的 sha256 与题目判据相等即 solved）。进程内，干跑不需要 Docker。
- full（全栈流程，M0 报告里的 B1b）：起 scripts/run.py 的整套系统（图服务、判官、司南、哮天犬、Adapter、执行层），
  人经 HTTP 开题，之后旁观到终态。终态由判官独立裁决、图服务写出；读数（事件数、花费）从图服务读。需要 Docker。

两种模式同仓、同端点代理、同价目表计量（红线 5）。干跑（假后端）用脚本化假 CLI，不需要真模型、真密钥。
"""

from __future__ import annotations

import json
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

from paoding_adapter.contract import EndpointProxy, FakeUpstream, PriceTable, ProxyConfig, fake_program
from paoding_tongjian.contract import MODES as MEMORY_MODES
from paoding_tongjian.contract import with_recall

from .harness import (
    PRICES,
    ROOT,
    MeteringLedger,
    collect,
    empty_mcp_config,
    match_memory,
    open_problem,
    run_cli,
    wait_terminal,
)
from .record import Record, log_dir_field, run_dirname, stamp
from .spec import ProblemSpec, sha256_hex


def run_baseline(
    spec: ProblemSpec,
    run_no: int,
    *,
    out_root: Path,
    model: str = "",
    real_program: list[str] | None = None,
    upstream_url: str = "",
    api_key: str = "",
    usage: dict | None = None,
    fake_steps: list | None = None,
    timeout_s: float = 300,
) -> Record:
    """baseline 模式（单 CLI 直连）。real_program 为 None 时干跑（假 CLI + 假上游）；否则用真 CLI 直连 upstream_url。

    fake_steps 只用于干跑测试：覆盖假 CLI 的步骤（默认是把 spec.answer 写进 answer.txt）。"""
    t0 = time.monotonic()
    log_dir = out_root / run_dirname("baseline", spec.id, run_no, stamp())
    workspace = log_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    dry = real_program is None

    ledger = MeteringLedger()
    upstream = None
    if dry:
        upstream = FakeUpstream(usage)
        up_url, key, program = upstream.url, "sk-fake-upstream", fake_program()
        steps = fake_steps or [{"tool": "Write", "input": {"file_path": "answer.txt", "content": spec.answer}}]
        script: Path | None = log_dir / "baseline.script.json"
        script.write_text(json.dumps({"steps": steps}), encoding="utf-8")
        model_name = model or "fake/claude-sonnet-5-5"
        cli_model = ""
    else:
        up_url, key, program, script = upstream_url, api_key, list(real_program), None
        model_name = cli_model = model

    proxy = EndpointProxy(
        ProxyConfig(up_url, key, "eval-baseline", global_cap_usd_milli=1_000_000_000), PriceTable.load(PRICES), ledger
    )
    proxy.serve()
    proxy_url = proxy.url
    token = secrets.token_urlsafe(16)
    proxy.register_task(
        token, "baseline", spec.id, reserve_usd_milli=max(int(spec.budget.get("usd_milli", 5000)), 1_000_000)
    )

    try:
        res = run_cli(
            program,
            spec.goal_prompt,
            workspace=workspace,
            proxy_url=proxy_url,
            token=token,
            mcp_config=empty_mcp_config(log_dir / "mcp.json"),
            model=cli_model,
            fake_script=script,
            timeout_s=timeout_s,
        )
    finally:
        proxy.close()
        if upstream is not None:
            upstream.close()

    produced = workspace / "answer.txt"
    if res["timed_out"] or not res["ok"]:
        terminal = "failed"
    else:
        got = produced.read_text(encoding="utf-8").strip() if produced.exists() else None
        terminal = "solved" if got is not None and sha256_hex(got) == spec.expect()["sha256"] else "unsolved"

    (log_dir / "cli.stream-json").write_text(res["stdout"], encoding="utf-8")
    if res["stderr"]:
        (log_dir / "cli.stderr").write_text(res["stderr"], encoding="utf-8")
    rec = Record(
        mode="baseline",
        problem=spec.id,
        run=run_no,
        model=model_name,
        duration_s=time.monotonic() - t0,
        terminal=terminal,
        cost_usd=ledger.usd_milli / 1000,
        events=res["turns"],
        log_dir=log_dir_field(out_root, log_dir.name),
    )
    rec.write(log_dir)
    return rec


def _write_meta(log_dir: Path, meta: dict) -> None:
    (log_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")


def _wait_ready(proc: subprocess.Popen, ready: Path, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ready.exists() and ready.read_text(encoding="utf-8").strip():
            return ready.read_text(encoding="utf-8").strip()
        if proc.poll() is not None:
            raise RuntimeError(f"全栈进程提前退出（code={proc.returncode}）")
        time.sleep(0.2)
    raise RuntimeError("全栈没在超时内就绪")


def run_full(
    spec: ProblemSpec,
    run_no: int,
    *,
    out_root: Path,
    config: dict,
    port: int = 0,
    model: str = "",
    boot_timeout_s: float = 60,
    timeout_s: float = 300,
    memory: str = "off",
    drop: tuple[str, ...] = (),
    home: Path | None = None,
) -> Record:
    """full 模式（全栈流程）。config 是写给 scripts/run.py 的栈配置（backend/executor/…）。

    memory（v1.5 能力一）：off | recall | noverify（消融 recall_noverify）。开题前向通鉴要匹配结果，按开关
    把召回清单写进开题批次；drop 是人去掉的条目。home 给出时复用这个数据目录（复做题组：A 先跑、B 后跑，
    共用一份通鉴）。开关取值写进 meta.json 的 switches。"""
    if memory not in MEMORY_MODES:
        raise ValueError(f"memory 取 {MEMORY_MODES} 之一，不是 {memory!r}")
    t0 = time.monotonic()
    log_dir = out_root / run_dirname("full", spec.id, run_no, stamp())
    log_dir.mkdir(parents=True, exist_ok=True)
    home = home or log_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ready = home / "ready"
    ready.unlink(missing_ok=True)  # 复用的数据目录里有上一次的就绪文件
    switches = {
        "memory": memory,
        "recall_noverify": memory == "noverify",
        "case_seal": bool((config.get("memory") or {}).get("case_seal", True)),
    }
    recall_info: dict = {}

    argv = [
        sys.executable,
        str(ROOT / "scripts" / "run.py"),
        "--home",
        str(home),
        "--config",
        str(home / "config.yaml"),
        "--port",
        str(port),
        "--no-static",
        "--ready-file",
        str(ready),
    ]
    stack_log = open(log_dir / "stack.log", "w", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen(argv, cwd=str(ROOT), stdout=stack_log, stderr=subprocess.STDOUT)
    terminal, events, cost = "failed", 0, 0.0
    try:
        url = _wait_ready(proc, ready, boot_timeout_s)
        human_token = (home / "human.token").read_text(encoding="utf-8").strip()
        ops = spec.open_ops()
        if memory != "off":
            m = match_memory(url, ops[-1]["body"])
            ops = with_recall(ops, m, memory, drop)
            recall_info = {"match_digest": m["digest"], "facts": len(m["facts"]), "dropped": sorted(drop)}
        opened = open_problem(url, human_token, spec.id, ops, spec.statement_bytes())
        if not opened.get("ok"):
            (log_dir / "open-rejected.json").write_text(json.dumps(opened, ensure_ascii=False, indent=2))
        else:
            wait_terminal(url, spec.id, timeout_s)
            got = collect(url, spec.id)
            events, cost = len(got["events"]), got["spent_usd_milli"] / 1000
            terminal = got["terminal"] if got["closed"] and got["terminal"] in ("solved", "unsolved") else "failed"
            (log_dir / "events.json").write_text(
                json.dumps(got["events"], ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        stack_log.close()

    rec = Record(
        mode="full",
        problem=spec.id,
        run=run_no,
        model=model or config.get("backend", {}).get("model", "fake"),
        duration_s=time.monotonic() - t0,
        terminal=terminal,
        cost_usd=cost,
        events=events,
        log_dir=log_dir_field(out_root, log_dir.name),
    )
    rec.write(log_dir)
    _write_meta(log_dir, {"switches": switches, **({"recall": recall_info} if recall_info else {})})
    return rec
