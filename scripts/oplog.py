"""结构化日志（P2-3）：一行一个 JSON 对象，同时写 stderr 与 <home>/logs/stack.log。

每条记录的字段：
    ts         事件发生的时刻，UTC，ISO 8601，毫秒
    level      debug | info | warning | error | critical
    component  组件名：graph、judge、sinan、adapter、watchdog、stack、http（访问日志）
    msg        给人读的一句话
    …上下文 ID  problem_id、lease_id、request_id、seq、kind、actor 等，由调用方经 `extra=ctx(...)` 给出
    exc        异常的回溯（只在带异常的记录上）

上下文 ID 只收 CONTEXT_KEYS 里列出的键，别的 extra 一律不输出：日志里不会意外带出令牌或请求体。
组件自己不依赖本模块：它们只用标准库的 logging，格式由组装根在这里统一决定。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

CONTEXT_KEYS = (
    "problem_id",
    "lease_id",
    "request_id",
    "seq",
    "kind",
    "actor",
    "session_id",
    "sandbox_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "bytes",
    "remote",
)
LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5


def ctx(**ids) -> dict:
    """logging 的 extra：只留非空的上下文 ID。用法：L.info("…", extra=ctx(problem_id=pid, lease_id=lid))。"""
    bad = set(ids) - set(CONTEXT_KEYS)
    if bad:
        raise KeyError(f"不是登记过的上下文键：{sorted(bad)}")
    return {k: v for k, v in ids.items() if v is not None}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "component": record.name,
            "msg": record.getMessage(),
        }
        for k in CONTEXT_KEYS:
            v = record.__dict__.get(k)
            if v is not None:
                out[k] = v
        if record.exc_text:  # 遮盖过滤器（钥匙环）已经生成并遮盖过
            out["exc"] = record.exc_text.rstrip()
        elif record.exc_info:
            out["exc"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(out, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """给人在终端看的旧格式：时间 组件名 消息 [键=值 …]，一行一条。"""

    def __init__(self):
        super().__init__("%(asctime)s %(name)-8s %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record).replace("\r", " ").replace("\n", " ⏎ ")
        ids = " ".join(f"{k}={record.__dict__[k]}" for k in CONTEXT_KEYS if record.__dict__.get(k) is not None)
        return f"{line} [{ids}]" if ids and record.name == "http" else line


def setup_logging(*, level: str = "info", fmt: str = "json", file: Path | None = None) -> None:
    """stderr 一路，另加一路文件（按大小轮转，10 MB × 5）。文件恒为 JSON；fmt 只管 stderr（json | text）。"""
    if level not in LEVELS:
        raise ValueError(f"日志级别取 {sorted(LEVELS)}，不是 {level!r}")
    if fmt not in ("json", "text"):
        raise ValueError(f"日志格式取 json 或 text，不是 {fmt!r}")
    err = logging.StreamHandler(sys.stderr)
    err.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handlers: list[logging.Handler] = [err]
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(file, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        handlers.append(fh)
    root = logging.getLogger()
    for h in root.handlers:
        h.close()
    root.handlers[:] = handlers
    root.setLevel(LEVELS[level])
