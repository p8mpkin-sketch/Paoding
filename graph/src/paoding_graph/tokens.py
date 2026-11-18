"""组件令牌（规格 §3.2.4 第 2 层）：登记与提议的身份只来自令牌，不来自请求体。

令牌按组件分发，都不进入模型容器与执行容器。任务令牌（Adapter 代 Worker 提交时用的会话令牌）
解析出的 actor 带 session 与 role，role 由租约决定，非模型自报。本模块是有状态的服务端对象，
不在 reducer 里；reducer 只看解析后的 actor。
"""
from __future__ import annotations

import hmac
import secrets
from typing import cast

from .envelope import check_actor
from .state import Actor


class UnknownToken(Exception):
    code = "forbidden_op"


class TokenRegistry:
    def __init__(self) -> None:
        self._by_token: dict[str, Actor] = {}

    def issue(self, actor: Actor, token: str | None = None) -> str:
        """token 只在测试与重启恢复时显式给出；缺省随机生成。"""
        check_actor(actor)
        tok = token or secrets.token_urlsafe(32)
        self._by_token[tok] = cast(Actor, dict(actor))
        return tok

    def revoke(self, token: str) -> None:
        self._by_token.pop(token, None)

    def resolve(self, token: str) -> Actor:
        for known, actor in self._by_token.items():
            if hmac.compare_digest(known, token):
                return cast(Actor, dict(actor))
        raise UnknownToken("未知令牌")
