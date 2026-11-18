"""CLI 后端绑定（§3.4.2 十项表）。只构造命令；模型容器的命令由 container.py 执行，离线预备阶段不运行真 CLI。

依据：该 CLI 2.1.326 的帮助文本（`claude --help`，2026-11-17 读取）。帮助文本里没有 `--max-turns`，
回合上限因此默认由 Adapter 从事件流计数执行，见 docs/m0/dissent-002-adapter.md；D4 真机核对后再定。

容器内只有任务令牌：ANTHROPIC_API_KEY=任务令牌，ANTHROPIC_BASE_URL=端点代理。真实密钥只在代理进程里。
"""

from __future__ import annotations

import json
import shlex
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

FILE_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep")  # 文件读写与检索；不含任何命令执行工具
PROXY_TOOLS = ("exec", "submit", "show")
MCP_NAME = "paoding"
CLOSING_PROMPT = (
    "收尾：本任务即将结束。请用 submit 提交你已有的结论；"
    "若没有结论，提交 final.outcome=unsolved 并在 suggestions 里写下排除过的方向。"
)


def session_uuid(lease_id: str) -> str:
    """--session-id 取租约派生的 UUID：同一租约恒得同一 UUID，收尾轮据此 --resume。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"paoding:lease:{lease_id}"))


@dataclass
class LaunchPlan:
    lease_id: str
    workspace: Path
    system_prompt_file: Path  # ①–⑤
    user_prompt: str  # ⑥⑦，或收尾轮提示
    mcp_config_file: Path
    proxy_tools: tuple = PROXY_TOOLS  # reason 不挂 exec
    proxy_url: str = ""
    task_token: str = ""
    max_budget_usd: float = 0.0
    max_turns: int = 0
    resume: bool = False


@dataclass
class CliBinding:
    program: list = field(default_factory=lambda: ["claude"])
    max_turns_flag: bool = False  # 帮助文本未列出 --max-turns；D4 真机核对前不传
    model: str = ""  # 非空时传 --model（例如 Anthropic 兼容端点上的别家模型名）

    def command(self, plan: LaunchPlan) -> tuple[list[str], dict[str, str]]:
        allowed = list(FILE_TOOLS) + [f"mcp__{MCP_NAME}__{t}" for t in plan.proxy_tools]
        sid = session_uuid(plan.lease_id)
        argv = [
            *self.program,
            "-p",
            plan.user_prompt,  # 1 无交互运行与事件流
            "--output-format",
            "stream-json",
            "--verbose",
            "--bare",  # 2 可复现启动，鉴权只认 API 密钥
            "--tools",
            ",".join(FILE_TOOLS),  # 3 去掉命令执行能力
            "--restricted",
            "--mcp-config",
            str(plan.mcp_config_file),  # 4 挂载代理工具
            "--strict-mcp-config",
            "--allowedTools",
            ",".join(allowed),  # 5 工具放行
            "--permission-prompts",
            "none",
            "--append-system-prompt-file",
            str(plan.system_prompt_file),  # 6 注入任务包
            *(["--resume", sid] if plan.resume else ["--session-id", sid]),  # 7 会话标识与续接
        ]
        if plan.max_budget_usd:  # 8 花费上限（客户端估算，可能略超）
            argv += ["--max-budget-usd", f"{plan.max_budget_usd:.2f}"]
        if self.model:
            argv += ["--model", self.model]
        if plan.max_turns and self.max_turns_flag:
            argv += ["--max-turns", str(plan.max_turns)]
        env = {
            "ANTHROPIC_BASE_URL": plan.proxy_url,
            "ANTHROPIC_API_KEY": plan.task_token,
            "HOME": str(plan.workspace.parent / "home"),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
        }
        return argv, env  # 9 计量对照与 10 终止由运行器处理


def mcp_config(url: str) -> str:
    return json.dumps({"mcpServers": {MCP_NAME: {"type": "http", "url": url}}}, sort_keys=True)


def container_argv(
    image: str,
    name: str,
    network: str,
    workspace: Path,
    session_dir: Path,
    argv: list[str],
    env: dict[str, str],
    *,
    home: Path | None = None,
    user: str | None = None,
    labels: dict | None = None,
    mounts: tuple = (),
    memory: str | None = None,
    pids: int | None = None,
) -> list[str]:
    """模型容器的 docker run 命令：只挂工作区、会话目录（只读）与它自己的 HOME；出站只到工具端点与代理所在网络。

    由 container.py 的 ContainerLauncher 执行。argv 与 env 里的路径须已换成容器内的路径。
    `--init`：CLI 不当 1 号进程，SIGTERM/SIGINT 按默认语义送到（1 号进程会忽略没装处理器的信号）。"""
    out = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--name",
        name,
        "--label",
        "paoding.model=1",
        "--network",
        network,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--mount",
        f"type=bind,src={workspace},dst=/workspace,bind-propagation=rprivate",
        "--mount",
        f"type=bind,src={session_dir},dst=/session,readonly",
        "-w",
        "/workspace",
    ]
    if home is not None:  # 会话状态（--resume 要读）跨两轮保留；套在只读的 /session 之外
        out += ["--mount", f"type=bind,src={home},dst=/home/pd"]
    for src, dst in mounts:
        out += ["--mount", f"type=bind,src={src},dst={dst},readonly"]
    if user:
        out += ["--user", user]
    if memory:
        out += ["--memory", memory]
    if pids:
        out += ["--pids-limit", str(pids)]
    for k, v in sorted((labels or {}).items()):
        out += ["--label", f"{k}={v}"]
    for k, v in sorted(env.items()):
        out += ["-e", f"{k}={v}"]
    return out + [image, *argv]


FAKE_CLI = Path(__file__).with_name("fakecli.py")
FAKE_CLI_IN_CONTAINER = "/opt/paoding/fakecli.py"


def fake_program(in_container: bool = False) -> list[str]:
    """脚本化假 CLI：接受与真 CLI 同一组参数，脚本由 PD_FAKE_SCRIPT 指定。
    in_container：在模型容器（通用 Python 镜像）里跑，假 CLI 由启动器只读挂到固定路径。"""
    if in_container:
        return ["python", "-I", FAKE_CLI_IN_CONTAINER]
    return [sys.executable, "-I", str(FAKE_CLI)]


def describe(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)
