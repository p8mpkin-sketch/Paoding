"""对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""

from typing import Protocol

from .compile import ExecSpec, Limits, ScopeError, compile_spec  # noqa: F401
from .runtime import (  # noqa: F401
    ECHO_LIMIT,
    DockerExecutor,
    EnvManager,
    ExecResult,
    SandboxGone,
    gate_log,
    sweep_orphans,
)


class ExecPort(Protocol):
    """Adapter 的 exec 代理工具转到这里：在该租约的执行容器里运行，本层登记 exec 类 Artifact。"""

    def exec(
        self,
        sid: str,
        cmd: str,
        pid: str,
        idem_key: str,
        timeout_s: int = 60,
        cwd: str = "/workspace",
        register_as: str = "exec",
    ) -> ExecResult: ...

    def destroy(self, sid: str) -> None:
        """哮天犬叫停任务时销毁该租约的执行容器。"""


class SandboxPort(ExecPort, Protocol):
    """会话运行器按租约起执行容器用：launch 之后的 sid 交给 exec，会话结束时 destroy。"""

    def launch(self, spec: ExecSpec, lease_id: str, mount_workspace: bool = True) -> str: ...
