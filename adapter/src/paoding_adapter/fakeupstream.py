"""假模型端点：本机回环上的一个 /v1/messages，用来在没有真模型、没有真密钥时把端点代理那一段接通。

收到请求就按请求体的 stream 字段回 JSON 或 SSE，usage 是定好的数（可改）。不看请求内容、不生成任何内容，
只让代理有东西可计量。测试台与组装根（scripts/run.py 的空配置）共用这一份。

dialect 模拟别家 Anthropic 兼容端点（真实测试报告 P0-C，DeepSeek 上计量全为零）：
- crlf：SSE 用 \r\n 分行、\r\n\r\n 分事件
- gzip：不理会请求的 accept-encoding，响应一律 gzip
- usage_at：start（缺省，输入侧在 message_start、输出在 message_delta）| delta（全部在 message_delta）
- no_usage：响应里不带 usage
usage 原样回报：可以用 OpenAI 式或 DeepSeek 式的字段名，也可以带 null。
"""

from __future__ import annotations

import gzip
import json
import ssl
import threading
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
    ):
        self.seen: list[dict[str, Any]] = []
        self.usage = dict(usage or DEFAULT_USAGE)
        self.model = model
        self.dialect = dict(dialect or {})
        up = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                up.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                dl = up.dialect
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
                    data = json.dumps(
                        {
                            "id": "m1",
                            "type": "message",
                            "model": up.model,
                            "content": [{"type": "text", "text": "hi"}],
                            **({} if dl.get("no_usage") else {"usage": up.usage}),
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
