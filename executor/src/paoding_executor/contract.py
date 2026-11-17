"""对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""
from typing import Protocol

from .compile import ExecSpec, ScopeError, compile_spec  # noqa: F401
from .runtime import ECHO_LIMIT, DockerExecutor, ExecResult, sweep_orphans  # noqa: F401


class ExecPort(Protocol):
    """Adapter 的 exec 代理工具转到这里：在该租约的执行容器里运行，本层登记 exec 类 Artifact。"""

    def exec(self, sid: str, cmd: str, pid: str, idem_key: str, timeout_s: int = 60, cwd: str = "/workspace",
             register_as: str = "exec") -> ExecResult: ...

    def destroy(self, sid: str) -> None:
        """哮天犬叫停任务时销毁该租约的执行容器。"""
