"""对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""
from typing import Protocol

from .backend import CliBinding, fake_program  # noqa: F401
from .fakeupstream import FakeUpstream  # noqa: F401
from .mcp import ToolEndpoint  # noqa: F401
from .proxy import EndpointProxy, PriceTable, ProxyConfig  # noqa: F401
from .session import AdapterConfig, SessionRecord, SessionRunner  # noqa: F401


class SessionPort(Protocol):
    """司南按租约启动会话的入口（§3.4.2）。一次调用 = 一个任务 = 一个租约；返回时租约已释放。

    实现方：SessionRunner。司南只读返回的 SessionRecord.status 与 release，不读 Adapter 的内部状态。"""

    def run(self, pid: str, lease_id: str, *, statement: str, kits: list | None = None,
            focus: dict | None = None, sandbox_id: str | None = None) -> SessionRecord: ...
