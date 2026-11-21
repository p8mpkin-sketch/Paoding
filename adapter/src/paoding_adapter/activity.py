"""会话的实时活动（开放道进度可见性；open-lane 设计 §3.1“创建后能看到智能体在做什么”）。

CLI 以 stream-json 把每一回合的工具调用、自述（assistant 的文字块）与工具结果逐行写到 stdout，
会话运行器的读线程本来就逐行收着（SessionRecord.events，会话结束才进会话记录）。这里把同一条流
折成人看得懂的条目，边收边追加到会话目录的 activity.jsonl，供工作台按游标轮询：

    {"n": 序号, "round": 第几轮, "kind": "call", "tool": "exec", "gist": "python repro.py", "id": 工具调用 id}
    {"n": …, "kind": "result", "id": 工具调用 id, "ok": true|false, "gist": 结果的头几行}
    {"n": …, "kind": "say", "text": 自述}
    {"n": …, "kind": "end", "ok": …, "turns": …, "gist": 本轮结束的说法}
    {"n": …, "kind": "turn", "model": 模型, "in": 输入 token, "out": 输出 token,
     "cache_read": …, "cache_write": …, "stop": 停止原因}
    {"n": …, "kind": "think", "text": 思考（扩展思考块；被上游遮蔽的记 redacted）}

任务详情（结构/过程两栏）还要两样：每次模型调用一条 `turn`（取 assistant 消息自带的 model 与 usage，
不另算）、扩展思考一条 `think`。每条另带 `t`：自会话起算的毫秒数，供排时间轴与算工具耗时；
`t` 是本机墙钟，不进链哈希、不进入账段（同一剧本跑两遍，入账段仍逐字节相同），回放时没有它。

只排版、不推断：条目只来自 CLI 的事件，花费与耗时取端点代理与会话运行器自己的量。
原话里认出的凭据（creds.found）写进条目之前逐字遮盖；条目长度有上限，全文仍在会话记录里。
确定性代码，不调模型。

可回放的实时性（焚决首炼，炼档 001：docs/design/fenjue/dossiers/001-replayable-live.md）在此之上加三处：

1. **条目成链。** 每条带 `h = sha256(上一条的 h ‖ JCS(本条除 h 外))`，第一条的上一条取 64 个 0。遮盖在成链之前。
2. **分段入账。** 运行器在锚点处取 `segment()`：自上一锚点以来的条目连同首尾序号与链头，规范化成一段，
   以 authored 类登记进事件账（parents 指上一段）。事件只记 Blob 的哈希，这段内容就钉在了那个 seq 上。
   `replay_segments` 按段校验链，回放 `as_of` 时只认那时已入账的段。
3. **执行行可点。** exec 的结果条目带上执行层返回的 ArtifactId（`artifact`），工作台据此打开那次执行的留档。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from paoding_graph.contract import canonicalize

from . import creds

FILE = "activity.jsonl"  # 会话目录里：活动条目，一行一条
END_FILE = "activity.end.json"  # 会话目录里：会话结束时的耗时、花费与出口状态
GIST = 240  # 工具调用的摘要
OUT = 400  # 工具结果的摘要
SAY = 2000  # 一段自述
THINK = 4000  # 一段思考
SEGMENT_MEDIA = "application/vnd.paoding.activity-segment+json"  # 入账段的媒体类型（authored 类）
GENESIS = "0" * 64
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


def _artifact_of(text: str) -> str | None:
    """exec 的结果是一段 JSON，带执行层登记的 ArtifactId；认不出就是没有。"""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    aid = doc.get("artifact") if isinstance(doc, dict) else None
    return aid if isinstance(aid, str) and aid.startswith("a_") else None


_LOCAL = ("h", "t")  # 不进链哈希、不进入账段的键：链哈希本身与本机墙钟


def chained(item: Mapping[str, Any]) -> dict[str, Any]:
    """一条条目进链、进入账段的部分：去掉本机墙钟 t。回放所见与实时所见按这部分逐字节相同。"""
    return {k: v for k, v in item.items() if k != "t"}


def item_hash(prev: str, item: Mapping[str, Any]) -> str:
    body = {k: v for k, v in item.items() if k not in _LOCAL}
    return hashlib.sha256(prev.encode() + canonicalize(body)).hexdigest()


def fold(ev: Mapping[str, Any], rnd: int) -> list[dict[str, Any]]:
    """一行 stream-json 事件 → 零到多条活动条目（不带序号）。认不得的事件忽略。"""
    t = ev.get("type")
    raw = ev.get("message")
    msg: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    content = msg.get("content")
    out: list[dict[str, Any]] = []
    if t == "assistant" and isinstance(content, list):
        usage = msg.get("usage") if isinstance(msg.get("usage"), Mapping) else None
        if usage is not None or msg.get("model"):
            u: Mapping[str, Any] = usage or {}

            def num(k: str) -> int:
                v = u.get(k)
                return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0

            out.append(
                {
                    "round": rnd,
                    "kind": "turn",
                    "model": _clip(str(msg.get("model") or ""), 80),
                    "in": num("input_tokens"),
                    "out": num("output_tokens"),
                    "cache_read": num("cache_read_input_tokens"),
                    "cache_write": num("cache_creation_input_tokens"),
                    "stop": _clip(str(msg.get("stop_reason") or ""), 40),
                }
            )
        for c in content:
            if not isinstance(c, Mapping):
                continue
            if c.get("type") == "thinking" and str(c.get("thinking", "")).strip():
                out.append({"round": rnd, "kind": "think", "text": _clip(str(c["thinking"]), THINK)})
            elif c.get("type") == "redacted_thinking":
                out.append({"round": rnd, "kind": "think", "text": "", "redacted": True})
            elif c.get("type") == "text" and str(c.get("text", "")).strip():
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
                text = _text_of(c.get("content"))
                item = {
                    "round": rnd,
                    "kind": "result",
                    "id": str(c.get("tool_use_id", "")),
                    "ok": not c.get("is_error"),
                    "gist": _clip(text, OUT),
                    "size": len(text),
                }
                aid = _artifact_of(text)
                if aid:
                    item["artifact"] = aid  # 只给 exec 的结果留（ActivityLog.feed 按调用的工具名再筛一次）
                out.append(item)
    elif t == "result":
        out.append(
            {
                "round": rnd,
                "kind": "end",
                "ok": not ev.get("is_error"),
                "turns": ev.get("num_turns"),
                "gist": _clip(str(ev.get("subtype") or ""), 60),
                **({"ms": ev["duration_ms"]} if isinstance(ev.get("duration_ms"), int) else {}),
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
    """一个会话的活动条目：内存里一份（在途时读），同时追加到会话目录（会话结束后读）。线程安全。

    条目成链（`h`）；`anchored` 是已入账的最后一个序号，`segment()` 取下一段、`mark()` 记下它已入账。"""

    def __init__(self, sdir: Path, secrets: tuple[str, ...] = (), lease: str = ""):
        self.path = sdir / FILE
        self.secrets = secrets
        self.lease = lease
        self.items: list[dict[str, Any]] = []
        self.tools: dict[str, str] = {}  # 工具调用 id → 工具名：只给 exec 的结果留 ArtifactId
        self.anchored = 0
        self.head = GENESIS  # 已入账的链头
        self.segments: list[str] = []  # 已入账各段的 ArtifactId
        self.lock = threading.Lock()
        self.t0 = time.monotonic()

    def feed(self, ev: Mapping[str, Any], rnd: int) -> list[dict[str, Any]]:
        new = [_mask(x, self.secrets) for x in fold(ev, rnd)]
        if not new:
            return []
        with self.lock:
            for x in new:
                if x["kind"] == "call":
                    self.tools[x["id"]] = x["tool"]
                elif x["kind"] == "result" and "artifact" in x and self.tools.get(x["id"]) != "exec":
                    del x["artifact"]
                x["n"] = len(self.items) + 1
                x["t"] = int((time.monotonic() - self.t0) * 1000)
                x["h"] = item_hash(self.items[-1]["h"] if self.items else GENESIS, x)
                self.items.append(x)
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in new)
            except OSError:
                pass  # 落盘失败不影响会话本身；在途时仍可从内存读
        return new

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.items)

    def segment(self) -> tuple[bytes, int] | None:
        """自上一锚点以来的条目，规范化成一段；没有新条目返回 None。返回（字节，这一段的末尾序号）。"""
        with self.lock:
            fresh = self.items[self.anchored :]
            if not fresh:
                return None
            doc = {
                "v": 1,
                "kind": "activity-segment",
                "lease": self.lease,
                "first": fresh[0]["n"],
                "last": fresh[-1]["n"],
                "prev": self.head,
                "head": fresh[-1]["h"],
                "items": [chained(x) for x in fresh],
            }
            return canonicalize(doc), fresh[-1]["n"]

    def mark(self, last: int, aid: str) -> None:
        with self.lock:
            self.anchored = last
            self.head = self.items[last - 1]["h"]
            self.segments.append(aid)


class ChainBroken(ValueError):
    """入账段对不上：顺序断了、链头不符，或某条条目被改过。"""


def replay_segments(blobs: Iterable[bytes]) -> list[dict[str, Any]]:
    """按入账顺序给出各段的原文，校验后拼回条目。任何一处对不上抛 ChainBroken，不给部分结果。"""
    items: list[dict[str, Any]] = []
    head = GENESIS
    for raw in blobs:
        try:
            doc = json.loads(raw)
        except ValueError:
            raise ChainBroken("段不是 JSON") from None
        if not isinstance(doc, dict) or doc.get("kind") != "activity-segment" or doc.get("prev") != head:
            raise ChainBroken("段与上一段接不上")
        if doc.get("first") != len(items) + 1:
            raise ChainBroken("段的序号不连续")
        for x in doc.get("items", []):
            if not isinstance(x, dict) or x.get("n") != len(items) + 1 or item_hash(head, x) != x.get("h"):
                raise ChainBroken(f"第 {len(items) + 1} 条与链不符")
            head = x["h"]
            items.append(x)
        if doc.get("last") != len(items) or doc.get("head") != head:
            raise ChainBroken("段尾与链头不符")
    return items


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


def view(
    items: Iterable[Mapping[str, Any]], after: int, limit: int = 200, anchored: int | None = None
) -> dict[str, Any]:
    """游标之后的条目，外加“正在做”（最近一次还没回结果的工具调用）与“最近自述”。
    后两项按全部条目算，不受游标影响：轮询的人只拿增量，也总能看到这两样。"""
    xs = list(items)
    done = {x.get("id") for x in xs if x.get("kind") == "result"}
    pending = [x for x in xs if x.get("kind") == "call" and x.get("id") not in done]
    ended = bool(xs) and xs[-1].get("kind") == "end"
    says = [x for x in xs if x.get("kind") == "say"]
    turns = [x for x in xs if x.get("kind") == "turn"]
    page = [dict(x) for x in xs if int(x.get("n", 0)) > after][:limit]
    return {
        "items": page,
        "next_after": page[-1]["n"] if page else after,
        "total": len(xs),
        "calls": sum(1 for x in xs if x.get("kind") == "call"),
        # 模型调用：次数、token 合计与用到的模型（取 assistant 消息自带的 usage，不另算）
        "turns": len(turns),
        "tokens": {k: sum(int(x.get(k, 0) or 0) for x in turns) for k in ("in", "out", "cache_read", "cache_write")},
        "models": sorted({str(x.get("model")) for x in turns if x.get("model")}),
        "now": dict(pending[-1]) if pending and not ended else None,
        "last_say": dict(says[-1]) if says else None,
        # 已入账的最后一个序号；None 表示这个会话没有入账（焚决首炼之前的会话、严格道缺省）
        "anchored_through": anchored,
    }
