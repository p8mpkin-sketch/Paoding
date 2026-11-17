"""对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""
from typing import Protocol


class TaskControl(Protocol):
    """哮天犬对在途会话的两个动作。由 Adapter 的会话运行器实现（结构化类型，无需 import 本模块），组装根接线。"""

    def soft_line(self, lease_id: str) -> None:
        """任务越过软线：结束当前回合，追加一轮收尾。"""

    def kill(self, lease_id: str, reason: str) -> None:
        """越过硬顶、题预算耗尽、墙钟用尽或租约已过期：终止进程树、销毁容器。"""


from .dog import DogConfig, TickReport, Watchdog  # noqa: E402,F401
