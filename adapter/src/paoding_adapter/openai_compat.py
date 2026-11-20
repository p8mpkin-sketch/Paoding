"""OpenAI 兼容端点的格式转换（前端 v5 裁决“OpenAI 兼容=做”）。

命令行只会说 Anthropic Messages（POST /v1/messages）。模型档案的 format 是 openai 时，端点代理把请求改写成
Chat Completions（POST {endpoint}/chat/completions，Bearer 密钥），再把响应改写回 Messages 的形状：
非流式整体改写；流式逐块改写成 message_start / content_block_* / message_delta / message_stop。

只转两边都有的东西：文字、图片（base64 与 URL）、工具定义与调用、工具结果、停止原因、用量。
Anthropic 独有的（thinking、缓存控制、引用）丢掉，不假装转过去了。计量不在这里：代理照旧从上游原始字节取用量
（normalize_usage 认 OpenAI 的字段名），这里只负责让命令行读得懂。
"""

from __future__ import annotations

import json
import math
from typing import Any

STOP_REASON = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}

ERROR_TYPE = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
}


# ---------- 请求：Messages → Chat Completions ----------


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _image_part(b: dict[str, Any]) -> dict[str, Any] | None:
    src = b.get("source")
    if not isinstance(src, dict):
        return None
    if src.get("type") == "base64":
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"},
        }
    if src.get("type") == "url" and isinstance(src.get("url"), str):
        return {"type": "image_url", "image_url": {"url": src["url"]}}
    return None


def _user_messages(content: Any) -> list[dict[str, Any]]:
    """一条 user 消息可能夹着工具结果：工具结果各成一条 role=tool，其余的拼成一条 user。

    工具结果在前（OpenAI 要求紧跟调用）。"""
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    tools: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "tool_result":
            text = _text_of(b.get("content"))
            if b.get("is_error"):
                text = f"[error] {text}"
            tools.append({"role": "tool", "tool_call_id": str(b.get("tool_use_id", "")), "content": text})
        elif t == "text":
            parts.append({"type": "text", "text": str(b.get("text", ""))})
        elif t == "image":
            img = _image_part(b)
            if img:
                parts.append(img)
        elif t == "document":
            src = b.get("source")
            if isinstance(src, dict) and src.get("type") == "text":
                parts.append({"type": "text", "text": str(src.get("data", ""))})
    out = list(tools)
    if parts:
        only_text = all(p["type"] == "text" for p in parts)
        out.append({"role": "user", "content": "\n".join(p["text"] for p in parts) if only_text else parts})
    return out


def _assistant_message(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"role": "assistant", "content": content}
    texts: list[str] = []
    calls: list[dict[str, Any]] = []
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            texts.append(str(b.get("text", "")))
        elif b.get("type") == "tool_use":
            calls.append(
                {
                    "id": str(b.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(b.get("name", "")),
                        "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False),
                    },
                }
            )
    m: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) if texts else None}
    if calls:
        m["tool_calls"] = calls
    return m


def _tool_choice(tc: Any) -> Any:
    if not isinstance(tc, dict):
        return None
    t = tc.get("type")
    if t == "auto":
        return "auto"
    if t == "any":
        return "required"
    if t == "none":
        return "none"
    if t == "tool" and isinstance(tc.get("name"), str):
        return {"type": "function", "function": {"name": tc["name"]}}
    return None


def to_openai_request(body: dict[str, Any], model: str = "") -> dict[str, Any]:
    """Messages 请求体 → Chat Completions 请求体。model 非空时覆盖请求里的（档案里写的模型 ID）。"""
    msgs: list[dict[str, Any]] = []
    system = _text_of(body.get("system"))
    if system:
        msgs.append({"role": "system", "content": system})
    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant":
            msgs.append(_assistant_message(m.get("content")))
        else:
            msgs.extend(_user_messages(m.get("content")))
    out: dict[str, Any] = {"model": model or body.get("model", ""), "messages": msgs}
    if isinstance(body.get("max_tokens"), int):
        out["max_tokens"] = body["max_tokens"]
    for k in ("temperature", "top_p"):
        if isinstance(body.get(k), (int, float)) and not isinstance(body.get(k), bool):
            out[k] = body[k]
    if isinstance(body.get("stop_sequences"), list) and body["stop_sequences"]:
        out["stop"] = body["stop_sequences"][:4]
    tools = [
        {
            "type": "function",
            "function": {
                "name": str(t.get("name", "")),
                "description": str(t.get("description", "")),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in body.get("tools") or []
        if isinstance(t, dict) and t.get("name") and "input_schema" in t  # 服务端工具（无 input_schema）转不过去
    ]
    if tools:
        out["tools"] = tools
        choice = _tool_choice(body.get("tool_choice"))
        if choice is not None:
            out["tool_choice"] = choice
        if isinstance(body.get("tool_choice"), dict) and body["tool_choice"].get("disable_parallel_tool_use"):
            out["parallel_tool_calls"] = False
    if body.get("stream"):
        out["stream"] = True
        out["stream_options"] = {"include_usage": True}  # 不要这个，流式响应里没有用量
    return out


# ---------- 用量 ----------


def anthropic_usage(u: Any) -> dict[str, int]:
    """OpenAI 用量 → Messages 用量（input_tokens 不含缓存命中，与 Anthropic 的口径一致）。"""
    if not isinstance(u, dict):
        return {"input_tokens": 0, "output_tokens": 0}

    def num(x: Any) -> int:
        return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else 0

    det = u.get("prompt_tokens_details")
    hit = num(det.get("cached_tokens")) if isinstance(det, dict) else 0
    hit = hit or num(u.get("prompt_cache_hit_tokens"))
    prompt = num(u.get("prompt_tokens"))
    out = {"input_tokens": max(0, prompt - hit), "output_tokens": num(u.get("completion_tokens"))}
    if hit:
        out["cache_read_input_tokens"] = hit
    return out


# ---------- 非流式响应 ----------


def _args(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {"_raw": raw}  # 模型给了不是 JSON 的参数：原样交给命令行，让它报错
    return v if isinstance(v, dict) else {"_raw": v}


def from_openai_response(d: dict[str, Any], model: str = "") -> dict[str, Any]:
    choice = (d.get("choices") or [{}])[0] if isinstance(d.get("choices"), list) else {}
    msg = choice.get("message") if isinstance(choice, dict) else None
    msg = msg if isinstance(msg, dict) else {}
    content: list[dict[str, Any]] = []
    text = msg.get("content")
    if isinstance(text, str) and text:
        content.append({"type": "text", "text": text})
    for c in msg.get("tool_calls") or []:
        if isinstance(c, dict) and isinstance(c.get("function"), dict):
            f = c["function"]
            content.append(
                {
                    "type": "tool_use",
                    "id": str(c.get("id") or ""),
                    "name": str(f.get("name", "")),
                    "input": _args(f.get("arguments")),
                }
            )
    if not content:
        content.append({"type": "text", "text": ""})
    reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    return {
        "id": str(d.get("id") or "msg_openai"),
        "type": "message",
        "role": "assistant",
        "model": str(d.get("model") or model),
        "content": content,
        "stop_reason": STOP_REASON.get(str(reason), "end_turn"),
        "stop_sequence": None,
        "usage": anthropic_usage(d.get("usage")),
    }


def error_body(status: int, raw: bytes) -> bytes:
    """上游的错误 → Messages 的错误形状，命令行据此显示原因。"""
    message = raw.decode("utf-8", "replace")[:2000]
    try:
        e = json.loads(raw).get("error")
        if isinstance(e, dict) and e.get("message"):
            message = str(e["message"])
        elif isinstance(e, str):
            message = e
    except (ValueError, AttributeError):
        pass
    kind = ERROR_TYPE.get(status, "api_error" if status >= 500 else "invalid_request_error")
    return json.dumps({"type": "error", "error": {"type": kind, "message": message}}, ensure_ascii=False).encode()


def count_tokens(body: bytes | None, bytes_per_token: int) -> bytes:
    """/v1/messages/count_tokens 在 Chat Completions 里没有对应：按字节估一个数（宁多勿少）。"""
    return json.dumps({"input_tokens": math.ceil(len(body or b"") / bytes_per_token)}).encode()


# ---------- 流式响应 ----------


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


class StreamTranslator:
    """Chat Completions 的 SSE 字节 → Messages 的 SSE 字节。feed 给多少吐多少，finish 收尾。

    文字与每个工具调用各开一个内容块；工具参数按 input_json_delta 逐段转发。上游的用量在最后一块（include_usage），
    message_delta 里带出去。上游没给 [DONE] 就断了，finish 也照样把块关好、发 message_stop。"""

    def __init__(self, model: str = ""):
        self.model = model
        self.buf = b""
        self.started = False
        self.done = False
        self.index = -1  # 当前打开的内容块
        self.open: str | None = None  # "text" | "tool:<openai 下标>"
        self.tool_blocks: dict[int, int] = {}  # OpenAI 工具下标 → 内容块下标
        self.stop: str | None = None
        self.usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self.id = "msg_openai"

    def _start(self) -> bytes:
        if self.started:
            return b""
        self.started = True
        return _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": self.id,
                    "type": "message",
                    "role": "assistant",
                    "model": self.model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )

    def _close(self) -> bytes:
        if self.open is None:
            return b""
        self.open = None
        return _sse("content_block_stop", {"type": "content_block_stop", "index": self.index})

    def _chunk(self, d: dict[str, Any]) -> bytes:
        out = b""
        if isinstance(d.get("id"), str) and not self.started:
            self.id = d["id"]
        if isinstance(d.get("model"), str) and d["model"]:
            self.model = self.model or d["model"]
        out += self._start()
        if isinstance(d.get("usage"), dict):
            self.usage = anthropic_usage(d["usage"])
        for ch in d.get("choices") or []:
            if not isinstance(ch, dict):
                continue
            raw_delta = ch.get("delta")
            delta: dict[str, Any] = raw_delta if isinstance(raw_delta, dict) else {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                if self.open != "text":
                    out += self._close()
                    self.index += 1
                    self.open = "text"
                    out += _sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": self.index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                out += _sse(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": self.index, "delta": {"type": "text_delta", "text": text}},
                )
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                k = int(tc.get("index", 0)) if isinstance(tc.get("index", 0), int) else 0
                raw_f = tc.get("function")
                f: dict[str, Any] = raw_f if isinstance(raw_f, dict) else {}
                if k not in self.tool_blocks:
                    out += self._close()
                    self.index += 1
                    self.tool_blocks[k] = self.index
                    self.open = f"tool:{k}"
                    block = {
                        "type": "tool_use",
                        "id": str(tc.get("id") or f"call_{k}"),
                        "name": str(f.get("name", "")),
                        "input": {},
                    }
                    out += _sse(
                        "content_block_start",
                        {"type": "content_block_start", "index": self.index, "content_block": block},
                    )
                elif self.open != f"tool:{k}":
                    continue  # 已经关掉的工具块又来参数：Messages 里块不能重开，丢掉（各家实际都按序给）
                args = f.get("arguments")
                if isinstance(args, str) and args:
                    out += _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": self.index,
                            "delta": {"type": "input_json_delta", "partial_json": args},
                        },
                    )
            if ch.get("finish_reason"):
                self.stop = STOP_REASON.get(str(ch["finish_reason"]), "end_turn")
        return out

    def feed(self, chunk: bytes) -> bytes:
        if self.done:
            return b""
        self.buf += chunk
        if b"\r" in self.buf:
            self.buf = self.buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        out = b""
        while b"\n\n" in self.buf:
            event, self.buf = self.buf.split(b"\n\n", 1)
            out += self._event(event)
        return out

    def _event(self, event: bytes) -> bytes:
        out = b""
        for line in event.split(b"\n"):
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                return out + self.finish()
            try:
                d = json.loads(data)
            except ValueError:
                continue
            if isinstance(d, dict) and isinstance(d.get("error"), dict):
                self.done = True
                return out + _sse(
                    "error",
                    {"type": "error", "error": {"type": "api_error", "message": str(d["error"].get("message", ""))}},
                )
            if isinstance(d, dict):
                out += self._chunk(d)
        return out

    def finish(self) -> bytes:
        if self.done:
            return b""
        out = b""
        if self.buf.strip():
            ev, self.buf = self.buf, b""
            out += self._event(ev)
            if self.done:
                return out
        self.done = True
        out += self._start() + self._close()
        out += _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": self.stop or "end_turn", "stop_sequence": None},
                "usage": self.usage,
            },
        )
        return out + _sse("message_stop", {"type": "message_stop"})
