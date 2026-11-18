"""两种模式共用的底座：计量账（baseline 用）、CLI 启动、以及和图服务说话的 HTTP 客户端（full 用）。

红线 5（诚实对照）：两种模式同仓、同端点代理、同价目表计量。baseline 也把 CLI 指向端点代理，
代理照常换密钥、按同一张价目表折算花费；只是没有图服务编排，花费记在一个进程内的计量账上。
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .box import HOME as BOX_HOME
from .box import PD_DIR

ROOT = Path(__file__).resolve().parents[3]  # 仓库根：eval/src/paoding_eval/harness.py → 上四层
PRICES = ROOT / "adapter" / "config" / "prices.yaml"
# baseline 的原生工具面（不挂代理工具）。规格 A2：B1 是"工具面原样"的单次瘦基线，所以含 Bash：
# 模型要连题目环境，只能经它（在沙箱里跑，出站只到授权目标；见 box.py）
NATIVE_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep")


class MeteringLedger:
    """baseline 的计量账：实现图服务的提议通道形状（GraphPort.submit），只收 cost 操作并累加毫美元。

    端点代理每计一次量就提交一条 cost 事件；这里把 body.usd_milli 累加起来，别的操作忽略。
    它不是图：baseline 没有图服务编排，只借代理的同一套计量。"""

    def __init__(self) -> None:
        self.usd_milli = 0
        self.costs: list[dict[str, Any]] = []

    def submit(self, token: str, pid: str, idem_key: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
        results = []
        for op in ops:
            if op.get("op") == "cost":
                body = op.get("body", {})
                self.usd_milli += int(body.get("usd_milli", 0))
                self.costs.append(body)
            results.append({"ok": True, "id": f"c{len(self.costs)}", "seq": len(self.costs)})
        return {"ok": True, "results": results}


def empty_mcp_config(path: Path) -> Path:
    """baseline 的原生工具面：一个不挂任何服务器的 MCP 配置（CLI 要求有这个文件）。"""
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    return path


def run_cli(
    program: list[str],
    prompt: str,
    *,
    workspace: Path,
    proxy_url: str,
    token: str,
    mcp_config: Path,
    tools: tuple[str, ...] = NATIVE_TOOLS,
    model: str = "",
    fake_script: Path | None = None,
    timeout_s: float = 300,
    box: Any = None,
) -> dict[str, Any]:
    """起一次 CLI 会话（原生工具面，直连端点代理）。返回 {ok, turns, cost_self_usd, stdout, stderr, timed_out}。

    fake_script 给出时用脚本化假 CLI（program 指向 fakecli.py），不需要真模型；否则按真 CLI 的参数起 program。
    box（BaselineBox）给出时 CLI 在沙箱里经 docker exec 起：MCP 空配置与假 CLI 的脚本先拷进去，
    代理地址换成沙箱网络上的中继，HOME 在沙箱里；program 是沙箱镜像里的命令。"""
    if box is not None:
        box.copy_in(mcp_config, f"{PD_DIR}/mcp.json")
        mcp_config = Path(f"{PD_DIR}/mcp.json")
        proxy_url = box.proxy_url
        if fake_script is not None:
            box.copy_in(fake_script, f"{PD_DIR}/script.json")
            fake_script = Path(f"{PD_DIR}/script.json")
    sid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"paoding:eval:baseline:{token}"))
    argv = [
        *program,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--bare",
        "--tools",
        ",".join(tools),
        "--restricted",
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
        "--allowedTools",
        ",".join(tools),
        "--permission-prompts",
        "none",
        "--session-id",
        sid,
    ]
    if model:
        argv += ["--model", model]
    env = {
        "ANTHROPIC_BASE_URL": proxy_url,
        "ANTHROPIC_API_KEY": token,
        "HOME": BOX_HOME if box is not None else str(workspace.parent / "home"),
        "LANG": "C.UTF-8",
    }
    if box is None:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        (workspace.parent / "home").mkdir(parents=True, exist_ok=True)
    if fake_script is not None:
        env["PD_FAKE_SCRIPT"] = str(fake_script)
    if box is not None:
        cmd, run_env, cwd = box.exec_argv(argv, env), None, None  # 沙箱镜像自己的 PATH
    else:
        cmd, run_env, cwd = argv, env, workspace
    timed_out = False
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            env=run_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        stdout, stderr, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout, stderr, rc = (
            (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
            ((e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")),
            None,
        )
    turns, cost_self, ok = 0, 0.0, False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            turns += 1
        elif ev.get("type") == "result":
            cost_self = float(ev.get("total_cost_usd") or 0.0)
            ok = not ev.get("is_error", True)
            if isinstance(ev.get("num_turns"), int):
                turns = ev["num_turns"]
    return {
        "ok": ok and not timed_out and rc == 0,
        "turns": turns,
        "cost_self_usd": cost_self,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
    }


# ---------- 和图服务说话（full；人只做开题，之后旁观） ----------


def _call(
    url: str, path: str, body: object = None, token: str | None = None, raw: bytes | None = None
) -> dict[str, Any]:
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    method = "PUT" if raw is not None else ("GET" if body is None else "POST")
    headers = {"Content-Type": "application/octet-stream" if raw is not None else "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as r:
        out: dict[str, Any] = json.loads(r.read())
        return out


def open_problem(url: str, token: str, pid: str, spec_ops: list[dict[str, Any]], statement: bytes) -> dict[str, Any]:
    """把题面 Blob 放进仓库，再提交开题操作（register_artifact + open_problem）。"""
    _call(url, "/v1/blobs", token=token, raw=statement)
    return _call(url, "/v1/problems", {"id": pid, "idem_key": f"open-{pid}", "ops": spec_ops}, token=token)


def wait_terminal(url: str, pid: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        st = _call(url, f"/v1/problems/{pid}/status")
        if st["problem"].get("closed"):
            return st
        time.sleep(0.3)
    return _call(url, f"/v1/problems/{pid}/status")


def collect(url: str, pid: str) -> dict[str, Any]:
    """终态后的读数：事件数、花费、终态。"""
    st = _call(url, f"/v1/problems/{pid}/status")
    budget = _call(url, f"/v1/problems/{pid}/budget")
    events = _call(url, f"/v1/problems/{pid}/events?after=0&limit=10000")["events"]
    return {
        "terminal": st["problem"].get("terminal"),
        "closed": bool(st["problem"].get("closed")),
        "events": events,
        "spent_usd_milli": budget["spent"]["usd_milli"],
    }
