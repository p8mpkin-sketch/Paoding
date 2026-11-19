"""密钥钥匙环（宪章 03 §4，裁决 D4）：真实模型密钥只活在端点代理这一个进程的内存里。

与人的令牌同级管理：
- 不落盘：没有任何方法把钥匙环写到文件；进程退出即消失，下次启动由设置页或环境变量重新注入。
- 不回显：对外只给 status()——槽名、是否已设、指纹、设置时间、来源；没有读回密钥的接口（get 只供代理换密钥）。
- 不进日志：install_redaction() 把钥匙环登记进进程级遮盖，按已注入的密钥逐字替换成指纹：记录产生时替换一次，
  根记录器的处理器上再挂一道过滤器管异常栈。

指纹 = sha256(进程盐 ‖ 密钥) 的前 8 位 + 密钥末 4 位。盐每个进程随机，指纹只在本次运行内可比。
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Any

SOURCES = ("page", "env", "config", "fake")  # 设置页、环境变量、配置文件（D4 过渡期）、假上游


@dataclass
class _Entry:
    key: str
    source: str
    set_at: int  # 毫秒


class KeyRing:
    def __init__(self, slots: dict[str, str] | None = None) -> None:
        """slots：槽名 → 对应的环境变量名（只用于提示“可用环境变量持久注入”）。"""
        self._env: dict[str, str] = dict(slots or {})
        self._keys: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._salt = secrets.token_bytes(16)

    # ---------- 写 ----------

    def set(self, slot: str, key: str, source: str = "page") -> dict[str, Any]:
        if source not in SOURCES:
            raise ValueError(f"来源取 {SOURCES}，不是 {source!r}")
        key = key.strip()
        if not key or any(c.isspace() for c in key) or len(key) > 4096:
            raise ValueError("密钥须为非空、不含空白、不超过 4096 字符的串")
        with self._lock:
            self._env.setdefault(slot, "")
            self._keys[slot] = _Entry(key, source, int(time.time() * 1000))
        return self.slot_status(slot)

    def declare(self, slot: str, env: str = "") -> None:
        """登记一个槽位（不设值）：status() 里列出来，设置页可见“还没设”与可用的环境变量名。"""
        with self._lock:
            self._env.setdefault(slot, env)

    def clear(self, slot: str) -> None:
        with self._lock:
            self._keys.pop(slot, None)

    def clear_all(self) -> None:
        with self._lock:
            self._keys.clear()

    # ---------- 读 ----------

    def get(self, slot: str) -> str | None:
        """只给要用真实密钥出站的组件：端点代理转发时换密钥、外部裁决的连接器、起草服务（宪章 Q28）。
        都在组装根这一个进程里，密钥不落盘、不进日志；别的调用方一律用 status()。"""
        e = self._keys.get(slot)
        return e.key if e else None

    def ready(self, slot: str) -> bool:
        return slot in self._keys

    def fingerprint(self, key: str) -> str:
        return hashlib.sha256(self._salt + key.encode()).hexdigest()[:8] + "…" + key[-4:]

    def slot_status(self, slot: str) -> dict[str, Any]:
        e = self._keys.get(slot)
        return {
            "slot": slot,
            "set": e is not None,
            "fingerprint": self.fingerprint(e.key) if e else None,
            "set_at": e.set_at if e else None,
            "source": e.source if e else None,
            "env": self._env.get(slot, ""),
        }

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            slots = sorted(set(self._env) | set(self._keys))
        return [self.slot_status(s) for s in slots]

    # ---------- 日志遮盖 ----------

    def redact(self, text: str) -> str:
        for e in list(self._keys.values()):
            if e.key in text:
                text = text.replace(e.key, f"<密钥 {self.fingerprint(e.key)}>")
        return text

    def install_redaction(self) -> None:
        """把本钥匙环登记进进程级的遮盖：日志记录产生时就替换（挡住之后才挂上的处理器，包括测试框架的），
        另在根记录器现有的处理器上挂一道过滤器（异常栈在格式化时才生成，记录工厂管不到）。
        进程里只装一层，可重复调用；钥匙环被回收后自动退出遮盖。"""
        _RINGS.add(self)
        global _installed
        if not _installed:
            old = logging.getLogRecordFactory()

            def factory(*a: Any, **kw: Any) -> logging.LogRecord:
                rec = old(*a, **kw)
                _scrub(rec)
                return rec

            logging.setLogRecordFactory(factory)
            _installed = True
        for h in logging.getLogger().handlers:
            if _FILTER not in h.filters:
                h.addFilter(_FILTER)


_RINGS: weakref.WeakSet[KeyRing] = weakref.WeakSet()
_installed = False


def redact_all(text: str) -> str:
    for ring in list(_RINGS):
        text = ring.redact(text)
    return text


def _scrub(rec: logging.LogRecord) -> None:
    if not any(r._keys for r in list(_RINGS)):
        return
    try:
        msg = rec.getMessage()
    except (TypeError, ValueError):
        msg = str(rec.msg)
    clean = redact_all(msg)
    if clean != msg:
        rec.msg, rec.args = clean, ()


class _Redactor(logging.Filter):
    """处理器级的遮盖：消息与异常文本都过一遍。"""

    def filter(self, record: logging.LogRecord) -> bool:
        _scrub(record)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_all(record.exc_text)
            record.exc_info = None  # 之后的格式化器只用遮盖过的 exc_text，不再从异常对象重新生成
        return True


_FILTER = _Redactor()
