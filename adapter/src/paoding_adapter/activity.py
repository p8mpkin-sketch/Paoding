"""会话的实时活动（开放道进度可见性；open-lane 设计 §3.1“创建后能看到智能体在做什么”）。

CLI 以 stream-json 把每一回合的工具调用、自述（assistant 的文字块）与工具结果逐行写到 stdout，
会话运行器的读线程本来就逐行收着（SessionRecord.events，会话结束才进会话记录）。这里把同一条流
折成人看得懂的条目，边收边追加到会话目录的 activity.jsonl，供工作台按游标轮询：

    {"n": 序号, "round": 第几轮, "kind": "call", "tool": "exec", "gist": "python repro.py", "id": 工具调用 id}
    {"n": …, "kind": "result", "id": 工具调用 id, "ok": true|false, "gist": 结果的头几行}
    {"n": …, "kind": "say", "text": 自述}
    {"n": …, "kind": "end", "ok": …, "turns": …, "gist": 本轮结束的说法}

只排版、不推断：条目只来自 CLI 的事件，花费与耗时取端点代理与会话运行器自己的量。
原话里认出的凭据（creds.found）写进条目之前逐字遮盖；条目长度有上限，全文仍在会话记录里。
确定性代码，不调模型。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from . import creds

FILE = "activity.jsonl"  # 会话目录里：活动条目，一行一条
END_FILE = "activity.end.json"  # 会话目录里：会话结束时的耗时、花费与出口状态
GIST = 240  # 工具调用的摘要
OUT = 400  # 工具结果的摘要
SAY = 2000  # 一段自述
_KEYS = ("cmd", "command", "file_path", "path", "pattern", "target", "url", "query", "q", "outcome", "id", "list")


def tool_word(name: str) -> str:
    """mcp__paoding__exec → exec；内置工具（Read、Bash…）原样。"""
    return name.split("__", 2)[2] if name.startswith("mcp__") and name.count("__") >= 2 else name


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def gist_of(inp: object) -> str:
    """工具输入的一行摘要：先认常见的键（命令、路径、地址），认不到就给紧凑的 JSON。"""
    if isinstance(inp, Mapping):
        for k in _KEYS:
            v = inp.get(k)
            if isinstance(v, str) and v.strip():
                return _clip(v, GIST)
        if not inp:
            return ""
    try:
        return _clip(json.dumps(inp, ensure_ascii=False, sort_keys=True, separators=(",", ":")), GIST)
    except (TypeError, ValueError):
        return _clip(str(inp), GIST)


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(c.get("text", "")) if isinstance(c, Mapping) else str(c) for c in content)
    return "" if content is None else str(content)


def fold(ev: Mapping[str, Any], rnd: int) -> list[dict[str, Any]]:
    """一行 stream-json 事件 → 零到多条活动条目（不带序号）。认不得的事件忽略。"""
    t = ev.get("type")
    msg = ev.get("message") if isinstance(ev.get("message"), Mapping) else {}
    content = msg.get("content") if isinstance(msg, Mapping) else None
    out: list[dict[str, Any]] = []
    if t == "assistant" and isinstance(content, list):
        for c in content:
            if not isinstance(c, Mapping):
                continue
            if c.get("type") == "text" and str(c.get("text", "")).strip():
                out.append({"round": rnd, "kind": "say", "text": _clip(str(c["text"]), SAY)})
            elif c.get("type") == "tool_use":
                name = str(c.get("name", ""))
                out.append(
                    {
                        "round": rnd,
                        "kind": "call",
                        "tool": tool_word(name),
                        "gist": gist_of(c.get("input")),
                        "id": str(c.get("id", "")),
                    }
                )
    elif t == "user" and isinstance(content, list):
        for c in content:
            if isinstance(c, Mapping) and c.get("type") == "tool_result":
                out.append(
                    {
                        "round": rnd,
                        "kind": "result",
                        "id": str(c.get("tool_use_id", "")),
                        "ok": not c.get("is_error"),
                        "gist": _clip(_text_of(c.get("content")), OUT),
                    }
                )
    elif t == "result":
        out.append(
            {
                "round": rnd,
                "kind": "end",
                "ok": not ev.get("is_error"),
                "turns": ev.get("num_turns"),
                "gist": _clip(str(ev.get("subtype") or ""), 60),
            }
        )
    return out


def _mask(item: dict[str, Any], secrets: tuple[str, ...]) -> dict[str, Any]:
    if not secrets:
        return item
    for k in ("text", "gist"):
        if isinstance(item.get(k), str):
            item[k] = creds.mask(item[k], secrets)[0]
    return item


class ActivityLog:
    """一个会话的活动条目：内存里一份（在途时读），同时追加到会话目录（会话结束后读）。线程安全。"""

    def __init__(self, sdir: Path, secrets: tuple[str, ...] = ()):
        self.path = sdir / FILE
        self.secrets = secrets
        self.items: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def feed(self, ev: Mapping[str, Any], rnd: int) -> None:
        new = [_mask(x, self.secrets) for x in fold(ev, rnd)]
        if not new:
            return
        with self.lock:
            for x in new:
                x["n"] = len(self.items) + 1
                self.items.append(x)
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in new)
            except OSError:
                pass  # 落盘失败不影响会话本身；在途时仍可从内存读

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.items)


def read_items(sdir: Path) -> list[dict[str, Any]]:
    try:
        lines = (sdir / FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def read_end(sdir: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads((sdir / END_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def view(items: Iterable[Mapping[str, Any]], after: int, limit: int = 200) -> dict[str, Any]:
    """游标之后的条目，外加“正在做”（最近一次还没回结果的工具调用）与“最近自述”。
    后两项按全部条目算，不受游标影响：轮询的人只拿增量，也总能看到这两样。"""
    xs = list(items)
    done = {x.get("id") for x in xs if x.get("kind") == "result"}
    pending = [x for x in xs if x.get("kind") == "call" and x.get("id") not in done]
    ended = bool(xs) and xs[-1].get("kind") == "end"
    says = [x for x in xs if x.get("kind") == "say"]
    page = [dict(x) for x in xs if int(x.get("n", 0)) > after][:limit]
    return {
        "items": page,
        "next_after": page[-1]["n"] if page else after,
        "total": len(xs),
        "calls": sum(1 for x in xs if x.get("kind") == "call"),
        "now": dict(pending[-1]) if pending and not ended else None,
        "last_say": dict(says[-1]) if says else None,
    }
