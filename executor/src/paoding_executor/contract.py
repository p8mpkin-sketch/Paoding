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


class HotGates(Protocol):
    """运行时扩权（docs/design/runtime-grants/ §5）：把在跑的沙箱的出站闸门对齐到新编出的 spec。
    执行器可以不实现它（例如将来的虚拟机隔离），那时退回租约边界：下一个租约起沙箱时才生效。"""

    def reconcile(self, sid: str, spec: ExecSpec) -> dict[str, list[str]]: ...
