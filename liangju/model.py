"""盲判自己的模型调用：直接连人指定的端点，不经过引擎，也不经过引擎的端点代理与预算账。

两种线格式都说（`anthropic`：Messages；`openai`：Chat Completions），因为盲判的模型要与各臂不同，可能在另一家。
密钥只从环境变量取，不进任何文件。每次调用的用量记进盲判自己的流水（`judge_calls.jsonl`），与各臂的花费分开。

还有一套只读工具（`Toolbox`），给回原文抽样核对用：列目录、读文件的一段、按正则搜。它只看得到定版快照那个目录。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from liangju import sousuo
from liangju.common import Refused
from liangju.sousuo import FILE_BYTES, SEARCH_HITS

ROOT = Path(__file__).resolve().parents[1]
READ_LINES = 200  # 一次至多读这么多行
SEARCH_SECONDS = 10.0  # 一次搜索的时间上限：超了按「没有搜到」处理，并记一笔


@dataclass(frozen=True)
class JudgeModel:
    name: str
    version: str
    wire: str  # anthropic | openai
    url: str  # 端点根地址，例如 https://api.anthropic.com 或 https://…/v1
    key_env: str  # 放密钥的环境变量名
    max_tokens: int = 4096
    temperature: float = 0.0

    @classmethod
    def load(cls, doc: dict[str, Any]) -> JudgeModel:
        missing = [k for k in ("name", "version", "wire", "url", "key_env") if not str(doc.get(k) or "").strip()]
        if missing:
            raise Refused(f"盲判的模型没有登记全，缺 {missing}：盲判不启动")
        if doc["wire"] not in ("anthropic", "openai"):
            raise Refused(f"wire 只取 anthropic 或 openai，不是 {doc['wire']!r}")
        keys = ("name", "version", "wire", "url", "key_env", "max_tokens", "temperature")
        return cls(**{k: doc[k] for k in keys if k in doc})


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Turn:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "cached_input": 0, "output": 0})
    model: str = ""


class Client(Protocol):
    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> Turn: ...


class ModelError(Exception):
    """端点没给出能用的回答（盲判没做成，不算任何一条臂的错）。"""


# 内部的消息形状：{"role": "user", "text": …}、{"role": "assistant", "text": …, "calls": [ToolCall]}、
# {"role": "tool", "id": …, "text": …}。两种线格式各自转换。


class HttpClient:
    def __init__(self, cfg: JudgeModel, timeout: float = 600.0) -> None:
        self.cfg, self.timeout = cfg, timeout
        key = os.environ.get(cfg.key_env, "")
        if not key:
            raise Refused(f"环境变量 {cfg.key_env} 里没有密钥：盲判不启动")
        self._key = key

    def _post(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        req = urllib.request.Request(  # noqa: S310  地址由人登记
            self.cfg.url.rstrip("/") + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
                doc = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise ModelError(f"{type(e).__name__}: {e}") from None
        if not isinstance(doc, dict):
            raise ModelError("端点回的不是一个 JSON 对象")
        return doc

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> Turn:
        return (
            self._anthropic(system, messages, tools)
            if self.cfg.wire == "anthropic"
            else self._openai(system, messages, tools)
        )

    def _anthropic(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> Turn:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                blocks: list[dict[str, Any]] = [{"type": "text", "text": m["text"]}] if m["text"] else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in m["calls"]]
                out.append({"role": "assistant", "content": blocks})
            else:  # 工具结果并进同一条 user 消息
                block = {"type": "tool_result", "tool_use_id": m["id"], "content": m["text"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        body: dict[str, Any] = {
            "model": self.cfg.name,
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "system": system,
            "messages": out,
        }
        if tools:
            body["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in tools
            ]
        doc = self._post("/v1/messages", body, {"x-api-key": self._key, "anthropic-version": "2023-06-01"})
        content = doc.get("content") or []
        u = doc.get("usage") or {}
        return Turn(
            text="".join(b.get("text", "") for b in content if b.get("type") == "text"),
            calls=[ToolCall(b["id"], b["name"], b.get("input") or {}) for b in content if b.get("type") == "tool_use"],
            usage={
                "input": int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0)),
                "cached_input": int(u.get("cache_read_input_tokens", 0)),
                "output": int(u.get("output_tokens", 0)),
            },
            model=str(doc.get("model", "")),
        )

    def _openai(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> Turn:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                row: dict[str, Any] = {"role": "assistant", "content": m["text"] or None}
                if m["calls"]:
                    row["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)},
                        }
                        for c in m["calls"]
                    ]
                out.append(row)
            else:
                out.append({"role": "tool", "tool_call_id": m["id"], "content": m["text"]})
        body: dict[str, Any] = {
            "model": self.cfg.name,
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "messages": out,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]},
                }
                for t in tools
            ]
        doc = self._post("/chat/completions", body, {"authorization": f"Bearer {self._key}"})
        try:
            msg = doc["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError("端点的回答里没有 choices[0].message") from None
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append(
                ToolCall(str(c.get("id", "")), str(c["function"]["name"]), args if isinstance(args, dict) else {})
            )
        u = doc.get("usage") or {}
        cached = int(
            (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or u.get("prompt_cache_hit_tokens", 0)
        )
        return Turn(
            text=str(msg.get("content") or ""),
            calls=calls,
            usage={
                "input": int(u.get("prompt_tokens", 0)) - cached,
                "cached_input": cached,
                "output": int(u.get("completion_tokens", 0)),
            },
            model=str(doc.get("model", "")),
        )


class Ledger:
    """盲判自己的调用流水：哪一段、哪份（盲号）、用量、端点报回的模型标识。不带提示词，不带模型的输出。"""

    def __init__(self, path: Path | None) -> None:
        self.path, self._lock = path, threading.Lock()
        self.rows: list[dict[str, Any]] = []

    def add(self, stage: str, blind: str, turn: Turn) -> None:
        row = {"stage": stage, "blind": blind, "model": turn.model, **turn.usage}
        with self._lock:
            self.rows.append(row)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------- 只读工具（只看得到快照目录）

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_dir",
        "description": '列出快照里一个目录下的文件与子目录。path 相对快照根，根目录写 "."。',
        "schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "read_file",
        "description": f"读快照里一个文件的一段，带行号。一次至多 {READ_LINES} 行；start 从 1 起。",
        "schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "search",
        "description": f"在快照的文本文件里按正则搜，回 路径:行号:该行。至多 {SEARCH_HITS} 处。可用 under 限定子目录。",
        "schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "under": {"type": "string"}},
            "required": ["pattern"],
        },
    },
]


class Toolbox:
    def __init__(self, root: Path, search_seconds: float = SEARCH_SECONDS) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise Refused(f"快照目录不在：{root}")
        self.search_seconds = search_seconds
        self.timeouts = 0  # 有几次搜索超过了时间上限

    def _path(self, rel: str) -> Path:
        return sousuo.inside(self.root, rel)

    def _search(self, under: str, pattern: str) -> str:
        """子进程里搜，到时限就杀掉。超时的那一次按「没有搜到」回给模型（注明是超时），次数记在 `timeouts`。"""
        ask = json.dumps({"root": str(self.root), "under": under, "pattern": pattern})
        try:
            done = subprocess.run(  # noqa: S603  固定的命令：本解释器跑量具自己的搜索模块
                [sys.executable, "-m", "liangju.sousuo"],
                input=ask.encode("utf-8"),
                capture_output=True,
                cwd=ROOT,
                timeout=self.search_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.timeouts += 1
            limit = f"这次搜索超过了 {self.search_seconds:g} 秒的上限，已经停下"
            return f"{sousuo.MISS}（{limit}；换一个更简单的模式或缩小范围）"
        if done.returncode != 0:
            return "没做成：搜索进程没有正常结束"
        return done.stdout.decode("utf-8", "replace")

    def run(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "list_dir":
                d = self._path(args.get("path", "."))
                rows = [f"{p.name}/" if p.is_dir() else p.name for p in sorted(d.iterdir()) if p.name != ".git"]
                return "\n".join(rows) or "（空目录）"
            if name == "read_file":
                p = self._path(args["path"])
                if p.stat().st_size > FILE_BYTES:
                    return "文件太大，不读"
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(1, int(args.get("start") or 1))
                end = min(len(lines), int(args.get("end") or start + READ_LINES - 1), start + READ_LINES - 1)
                body = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1))
                return f"{args['path']} 第 {start}–{end} 行（共 {len(lines)} 行）\n{body}"
            if name == "search":
                return self._search(str(args.get("under") or "."), str(args["pattern"]))
            return f"没有这个工具：{name}"
        except (OSError, ValueError, KeyError, re.error, TypeError) as e:
            return f"没做成：{type(e).__name__}: {e}"


LAST_ROUND = "\n\n（查阅次数已到上限：现在直接给出结论，不要再调用工具。）"


def with_tools(client: Client, system: str, user: str, box: Toolbox, steps: int) -> tuple[str, list[Turn]]:
    """带只读工具的一次核对：模型想查就查，至多 `steps` 轮查阅；最后一轮的结果后面注明该下结论了。"""
    messages: list[dict[str, Any]] = [{"role": "user", "text": user}]
    turns: list[Turn] = []
    for i in range(steps + 1):
        turn = client.chat(system, messages, TOOLS)
        turns.append(turn)
        if not turn.calls or i == steps:
            break
        messages.append({"role": "assistant", "text": turn.text, "calls": turn.calls})
        note = LAST_ROUND if i == steps - 1 else ""
        for c in turn.calls:
            messages.append({"role": "tool", "id": c.id, "text": box.run(c.name, c.args) + note})
    return turns[-1].text, turns
