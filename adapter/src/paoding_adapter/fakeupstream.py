"""假模型端点：本机回环上的一个 /v1/messages，用来在没有真模型、没有真密钥时把端点代理那一段接通。

收到请求就按请求体的 stream 字段回 JSON 或 SSE，usage 是定好的数（可改）。不看请求内容、不生成任何内容，
只让代理有东西可计量。测试台与组装根（scripts/run.py 的空配置）共用这一份。

dialect 模拟别家 Anthropic 兼容端点（真实测试报告 P0-C，DeepSeek 上计量全为零）：
- crlf：SSE 用 \r\n 分行、\r\n\r\n 分事件
- gzip：不理会请求的 accept-encoding，响应一律 gzip
- usage_at：start（缺省，输入侧在 message_start、输出在 message_delta）| delta（全部在 message_delta）
- no_usage：响应里不带 usage
路径以 /chat/completions 结尾时按 OpenAI Chat Completions 回（openai_tool、error 两个 dialect 键见 _openai）。
usage 原样回报：可以用 OpenAI 式或 DeepSeek 式的字段名，也可以带 null。

reply 给出时（方案分析的测试：按请求回放录好的输出），/v1/messages 先问它：它拿到请求体，交回
None（照旧回 "hi"）或一个字典：text（回文）、content（内容块）、usage、stop_reason、model 各自覆盖缺省；带 status 时
回那个状态码，响应体取 body。请求是流式的就把同一份回答拆成 SSE 事件回（思考块、文字块各按增量给），另认几个只管
“流怎么走”的键，用来演上游的毛病：
- stall_s：收到请求后先睡这么久再回响应头（上游挂住）
- gap_s：message_start 之后睡这么久再给内容（流上静默）
- drip_s：每个增量之间睡这么久（慢速生成）；pings：每个增量前先发一个 ping
- cut：给了一部分内容就把连接断掉，不给停止原因（流中断）
- stream_error：内容之后发一个 error 事件（值是错误类型）而不是停止原因
- no_stop_event：不发 message_stop（有的兼容端点这样）；as_json：不理会 stream，照旧回整个 JSON
它只是测试替身的出口，仍然不生成任何内容。
"""

from __future__ import annotations

import gzip
import json
import ssl
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_USAGE = {
    "input_tokens": 1000,
    "output_tokens": 200,
    "cache_read_input_tokens": 5000,
    "cache_creation_input_tokens": 100,
}


class FakeUpstream:
    """记录收到的请求头，按请求体 stream 字段回 JSON 或 SSE。"""

    def __init__(
        self,
        usage: dict[str, Any] | None = None,
        model: str = "claude-sonnet-5-5",
        port: int = 0,
        dialect: dict[str, Any] | None = None,
        tls: tuple[str, str] | None = None,
        reply: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ):
        self.seen: list[dict[str, Any]] = []
        self.usage = dict(usage or DEFAULT_USAGE)
        self.model = model
        self.dialect = dict(dialect or {})
        self.reply = reply
        up = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                up.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                dl = up.dialect
                if self.path.endswith("/chat/completions"):
                    return self._openai(body)
                if body.get("stream") and up.reply is not None:
                    said = up.reply(body) or {}
                    if not said.get("status") and not said.get("as_json"):
                        return self._stream(said)
                    body = {**body, "stream": False, "_said": said}
                if body.get("stream"):
                    out_keys = ("output_tokens", "completion_tokens")
                    if dl.get("usage_at") == "delta":
                        u_start, u_delta = {}, dict(up.usage)
                    else:
                        u_start = {**{k: v for k, v in up.usage.items() if k not in out_keys}, "output_tokens": 1}
                        u_delta = {k: v for k, v in up.usage.items() if k in out_keys}
                    start_msg = {"id": "m1", "model": up.model, **({} if dl.get("no_usage") else {"usage": u_start})}
                    events = [
                        ("message_start", {"type": "message_start", "message": start_msg}),
                        (
                            "content_block_delta",
                            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
                        ),
                        (
                            "message_delta",
                            {
                                "type": "message_delta",
                                "delta": {"stop_reason": "end_turn"},
                                **({} if dl.get("no_usage") else {"usage": u_delta}),
                            },
                        ),
                        ("message_stop", {"type": "message_stop"}),
                    ]
                    nl = b"\r\n" if dl.get("crlf") else b"\n"
                    data = b"".join(
                        b"event: %s%sdata: %s%s%s" % (n.encode(), nl, json.dumps(d).encode(), nl, nl) for n, d in events
                    )
                    ctype = "text/event-stream"
                else:
                    if "_said" in body:
                        said = body["_said"]
                    else:
                        said = (up.reply(body) if up.reply is not None else None) or {}
                    if said.get("status"):
                        data = json.dumps(said.get("body") or {}).encode()
                        self.send_response(int(said["status"]))
                        self.send_header("content-type", "application/json")
                        self.send_header("content-length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return None
                    data = json.dumps(
                        {
                            "id": "m1",
                            "type": "message",
                            "model": said.get("model", up.model),
                            "stop_reason": said.get("stop_reason", "end_turn"),
                            "content": said.get("content") or [{"type": "text", "text": said.get("text", "hi")}],
                            **({} if dl.get("no_usage") else {"usage": said.get("usage", up.usage)}),
                        }
                    ).encode()
                    ctype = "application/json"
                if dl.get("gzip"):
                    data = gzip.compress(data)
                self.send_response(200)
                self.send_header("content-type", ctype)
                if dl.get("gzip"):
                    self.send_header("content-encoding", "gzip")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _stream(self, said: dict[str, Any]) -> None:
                """按 reply 给的回答回一条 SSE 流（分块传输，逐事件写出，所以客户端真的是边收边读）。"""
                if said.get("stall_s"):
                    time.sleep(float(said["stall_s"]))
                usage = {} if up.dialect.get("no_usage") else dict(said.get("usage", up.usage))
                out_n = usage.pop("output_tokens", None)
                blocks = said.get("content")
                if blocks is None:
                    blocks = [{"type": "text", "text": said.get("text", "hi")}]
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()

                def emit(name: str, d: dict[str, Any]) -> None:
                    data = b"event: %s\ndata: %s\n\n" % (name.encode(), json.dumps(d, ensure_ascii=False).encode())
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                    self.wfile.flush()

                def pieces(text: str) -> list[str]:
                    n = max(1, len(text) // 3)
                    return [text[i : i + n] for i in range(0, len(text), n)] or [""]

                try:
                    start = {"id": "m1", "type": "message", "role": "assistant", "model": said.get("model", up.model)}
                    if usage or out_n is not None:
                        start["usage"] = {**usage, "output_tokens": 1}
                    emit("message_start", {"type": "message_start", "message": start})
                    if said.get("gap_s"):
                        time.sleep(float(said["gap_s"]))
                    for i, b in enumerate(blocks):
                        kind = b.get("type")
                        field = "thinking" if kind == "thinking" else "text" if kind == "text" else None
                        head = {**b, field: ""} if field else dict(b)
                        emit("content_block_start", {"type": "content_block_start", "index": i, "content_block": head})
                        for part in pieces(str(b.get(field, ""))) if field else []:
                            if said.get("pings"):
                                emit("ping", {"type": "ping"})
                            if said.get("drip_s"):
                                time.sleep(float(said["drip_s"]))
                            delta = {"type": f"{field}_delta", field: part}
                            emit("content_block_delta", {"type": "content_block_delta", "index": i, "delta": delta})
                            if said.get("cut"):
                                self.close_connection = True
                                return  # 不写收尾的零长块：连接就这么断了
                        emit("content_block_stop", {"type": "content_block_stop", "index": i})
                    if said.get("stream_error"):
                        err = {"type": str(said["stream_error"]), "message": "fake upstream error"}
                        emit("error", {"type": "error", "error": err})
                    else:
                        stop = {"stop_reason": said.get("stop_reason", "end_turn"), "stop_sequence": None}
                        final: dict[str, Any] = {"type": "message_delta", "delta": stop}
                        if out_n is not None:
                            final["usage"] = {"output_tokens": out_n}
                        emit("message_delta", final)
                        if not said.get("no_stop_event"):
                            emit("message_stop", {"type": "message_stop"})
                    self.wfile.write(b"0\r\n\r\n")
                except OSError:  # 客户端等不及先走了
                    self.close_connection = True

            def _openai(self, body: dict[str, Any]) -> None:
                """OpenAI Chat Completions：dialect 的 openai_tool=True 时回一个工具调用，error=状态码 时回错误。"""
                dl = up.dialect
                if dl.get("error"):
                    data = json.dumps({"error": {"message": "bad model", "type": "invalid_request_error"}}).encode()
                    self.send_response(int(dl["error"]))
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                tool = bool(dl.get("openai_tool"))
                usage = dict(up.usage)
                if body.get("stream"):
                    chunks: list[dict[str, Any]] = [
                        {
                            "id": "c1",
                            "model": up.model,
                            "choices": [{"index": 0, "delta": {"role": "assistant", "content": "h"}}],
                        },
                        {"id": "c1", "model": up.model, "choices": [{"index": 0, "delta": {"content": "i"}}]},
                    ]
                    if tool:
                        call = {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "Bash", "arguments": '{"comm'},
                        }
                        chunks.append({"id": "c1", "choices": [{"index": 0, "delta": {"tool_calls": [call]}}]})
                        more = {"index": 0, "function": {"arguments": 'and": "ls"}'}}
                        chunks.append({"id": "c1", "choices": [{"index": 0, "delta": {"tool_calls": [more]}}]})
                    reason = "tool_calls" if tool else "stop"
                    chunks.append({"id": "c1", "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]})
                    if not dl.get("no_usage"):
                        chunks.append({"id": "c1", "choices": [], "usage": usage})
                    data = b"".join(b"data: %s\n\n" % json.dumps(c).encode() for c in chunks) + b"data: [DONE]\n\n"
                    ctype = "text/event-stream"
                else:
                    msg: dict[str, Any] = {"role": "assistant", "content": "hi"}
                    if tool:
                        msg["tool_calls"] = [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "Bash", "arguments": '{"command": "ls"}'},
                            }
                        ]
                    out = {
                        "id": "c1",
                        "object": "chat.completion",
                        "model": up.model,
                        "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool else "stop"}],
                        **({} if dl.get("no_usage") else {"usage": usage}),
                    }
                    data = json.dumps(out).encode()
                    ctype = "application/json"
                self.send_response(200)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.server.daemon_threads = True
        scheme = "http"
        if tls is not None:  # (证书, 私钥)：模拟 https 的模型端点
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*tls)
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
            scheme = "https"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "%s://%s:%d" % (scheme, "localhost" if tls else "127.0.0.1", self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
