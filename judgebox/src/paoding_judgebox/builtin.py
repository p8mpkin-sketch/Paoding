"""内建判官（§3.3.2）：只有领域中立的两个，`exact_match` 与 `replay`（`seal_check` 随 M3）。

每个判官是一个函数 `(ctx) → Outcome`。它不写日志、不登记：产出交回判官运行器，由运行器登记为 judge 类并提交裁决。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from paoding_executor.contract import SandboxGone, ScopeError, compile_spec

from .vault import Vault, VaultError

RISK_RANK = {"r0": 0, "r1": 1, "r2": 2}


@dataclass
class Outcome:
    result: str  # pass | fail | flaky | inconclusive
    reason: str = "ok"  # ok | timeout | env_error | flaky | unsupported | untouched
    output: bytes = b""  # 判官输出：登记为 judge 类 Artifact 的正文
    provenance: dict = field(default_factory=dict)
    wall_s: int = 0


@dataclass
class Ctx:
    spec: dict  # 注册表条目
    check: dict  # 登记在目标上的判据
    problem: dict
    target: str
    target_risk: str
    candidate: bytes | None
    candidate_ref: str | None
    spec_bytes: bytes | None  # check.spec_ref 的字节（按哈希读出，读取时校验）
    spec_hash: str | None
    vault: Vault | None
    executor: Any  # SandboxPort；内建的纯计算判官不用
    request_id: str
    lease_id: str
    bases: dict
    now_ms: int


def _prov(tool: str, command: str, exit_code: int | None, now: int, touched: list[str] | None = None) -> dict:
    return {
        "sandbox_id": "builtin",
        "base": "builtin",
        "baseline_ref": "builtin",
        "tool": tool,
        "command": command,
        "cwd": "",
        "exit_code": exit_code,
        "touched": touched or [],
        "started_at": now,
        "ended_at": now,
        "truncated": False,
    }


def _report(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False, sort_keys=True).encode()


def exact_match(c: Ctx) -> Outcome:
    """候选与答案逐字节相同（都去掉首尾空白）。答案来自保密库（Check.sealed），或公开的摘要 expect.sha256。
    输出里只有候选的摘要与结论，从不出现答案。"""
    cmd = f"exact_match {c.candidate_ref or '-'}"
    if c.candidate is None:
        return Outcome(
            "inconclusive",
            "unsupported",
            _report(judge="exact_match", reason="unsupported", detail="没有候选"),
            _prov("exact_match", cmd, None, c.now_ms),
        )
    cand = c.candidate.strip()
    digest = hashlib.sha256(cand).hexdigest()
    sealed = c.check.get("sealed") or []
    touched: list[str] = []
    if sealed:
        if c.vault is None:
            return Outcome(
                "inconclusive",
                "env_error",
                _report(judge="exact_match", reason="env_error", detail="没有保密库"),
                _prov("exact_match", cmd, None, c.now_ms),
            )
        try:
            answer = c.vault.open(sealed[0]).strip()
        except VaultError as e:
            return Outcome(
                "inconclusive",
                "env_error",
                _report(judge="exact_match", reason="env_error", detail=str(e)),
                _prov("exact_match", cmd, None, c.now_ms),
            )
        touched = [f"vault:{sealed[0]['vault']}"]
        ok = cand == answer
    elif isinstance(c.check.get("expect", {}).get("sha256"), str):
        ok = digest == c.check["expect"]["sha256"].lower()
    else:
        return Outcome(
            "inconclusive",
            "unsupported",
            _report(judge="exact_match", reason="unsupported", detail="判据里既没有 sealed 也没有 expect.sha256"),
            _prov("exact_match", cmd, None, c.now_ms),
        )
    result = "pass" if ok else "fail"
    return Outcome(
        result,
        "ok",
        _report(judge="exact_match", result=result, candidate_sha256=digest),
        _prov("exact_match", cmd, 0 if ok else 1, c.now_ms, touched),
    )


def _matches(expect: dict, exit_code: int | None, text: str) -> bool:
    keys = {"exit_code", "stdout_contains", "stdout_regex"} & set(expect)
    if not keys:
        return exit_code == 0  # 没写期望：以正常退出为准
    if "exit_code" in expect and exit_code != expect["exit_code"]:
        return False
    if "stdout_contains" in expect and str(expect["stdout_contains"]) not in text:
        return False
    if "stdout_regex" in expect and not re.search(str(expect["stdout_regex"]), text):
        return False
    return True


def _put(name: str, data: bytes) -> str:
    return f"printf %s {base64.b64encode(data).decode()} | base64 -d > /workspace/{name}"


def _replay_once(c: Ctx, n: int) -> Outcome:
    script = c.spec_bytes if c.spec_bytes is not None else c.candidate
    if script is None:
        return Outcome("inconclusive", "unsupported", b"no spec and no candidate")
    p = c.problem
    env = {**p["env"], "base": c.bases.get(p["env"]["base"], p["env"]["base"])}
    ceiling = c.target_risk if RISK_RANK[c.target_risk] <= 1 else "r1"  # 不可逆动作从不重放
    try:
        spec = compile_spec(f"{c.lease_id.replace('_', '-')}-{n}", p["scope"], env, ceiling, False, "")
        sid = c.executor.launch(spec, c.lease_id, mount_workspace=False)  # 洁净容器：不挂 Worker 的工作区
    except (ScopeError, OSError, subprocess.SubprocessError, RuntimeError) as e:  # 起不来是环境错误（无结论）
        return Outcome("inconclusive", "env_error", f"launch failed: {type(e).__name__}: {e}".encode())
    try:
        setup = _put("spec", script)
        if c.candidate is not None and c.spec_bytes is not None:
            setup += " && " + _put("candidate", c.candidate)
        pre = c.executor.exec(
            sid, setup, p["id"], f"judge-setup:{c.request_id}:{c.lease_id}:{n}", timeout_s=30, register_as="judge"
        )
        if pre.exit_code != 0:
            return Outcome("inconclusive", "env_error", pre.output.encode(), pre.provenance)
        r = c.executor.exec(
            sid,
            "sh /workspace/spec",
            p["id"],
            f"judge-run:{c.request_id}:{c.lease_id}:{n}",
            timeout_s=int(c.spec.get("timeout_s", 60)),
            register_as="judge",
        )
    except SandboxGone as e:
        return Outcome("inconclusive", "env_error", str(e).encode())
    finally:
        c.executor.destroy(sid)
    prov = {**r.provenance, "tool": "replay", "command": f"sh /workspace/spec  # spec={c.spec_hash or c.candidate_ref}"}
    wall = max(0, (r.provenance["ended_at"] - r.provenance["started_at"]) // 1000)
    data = _blob(c, r)
    if r.exit_code is None:
        return Outcome("inconclusive", "timeout", data, prov, wall)
    if c.spec.get("params", {}).get("require_touch") and not r.provenance.get("touched"):
        return Outcome("inconclusive", "untouched", data, prov, wall)  # 空谓词：运行没碰任何授权资源
    ok = _matches(c.check.get("expect") or {}, r.exit_code, data.decode("utf-8", "replace"))
    return Outcome("pass" if ok else "fail", "ok", data, prov, wall)


def _blob(c: Ctx, r) -> bytes:
    get = getattr(getattr(c.executor, "blobs", None), "get", None)
    return get(r.blob) if get else r.output.encode()


def replay(c: Ctx) -> Outcome:
    """在洁净容器里重新执行规格（没有规格时执行候选本身），按 expect 比对。
    一次请求内连续运行 1 + flake.reruns 次：按 require 全部或多数一致给出结论，否则 flaky（§3.3.4）。"""
    if c.executor is None:
        return Outcome("inconclusive", "env_error", b"no executor")
    flake = c.spec.get("flake") or {}
    runs = [_replay_once(c, n) for n in range(1 + int(flake.get("reruns", 0)))]
    hard = [o for o in runs if o.result == "inconclusive"]
    if hard:
        return hard[0]
    passes = sum(o.result == "pass" for o in runs)
    last = runs[-1]
    last.wall_s = sum(o.wall_s for o in runs)
    if passes in (0, len(runs)):
        return last
    if flake.get("require", "all") == "majority" and passes * 2 != len(runs):
        want = "pass" if passes * 2 > len(runs) else "fail"
        return next(o for o in reversed(runs) if o.result == want)
    return Outcome("flaky", "flaky", last.output, last.provenance, last.wall_s)


BUILTINS = {"exact_match": exact_match, "replay": replay}
