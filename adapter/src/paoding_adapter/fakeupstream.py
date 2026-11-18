"""假模型端点：本机回环上的一个 /v1/messages，用来在没有真模型、没有真密钥时把端点代理那一段接通。

收到请求就按请求体的 stream 字段回 JSON 或 SSE，usage 是定好的数（可改）。不看请求内容、不生成任何内容，
只让代理有东西可计量。测试台与组装根（scripts/run.py 的空配置）共用这一份。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_USAGE = {"input_tokens": 1000, "output_tokens": 200,
                 "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 100}


class FakeUpstream:
    """记录收到的请求头，按请求体 stream 字段回 JSON 或 SSE。"""

    def __init__(self, usage: dict | None = None, model: str = "claude-sonnet-5-5", port: int = 0):
        self.seen: list[dict] = []
        self.usage = dict(usage or DEFAULT_USAGE)
        self.model = model
        up = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                up.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                if body.get("stream"):
                    u_in = {k: v for k, v in up.usage.items() if k != "output_tokens"}
                    events = [
                        ("message_start", {"type": "message_start", "message": {
                            "id": "m1", "model": up.model, "usage": {**u_in, "output_tokens": 1}}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                 "delta": {"type": "text_delta", "text": "hi"}}),
                        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                                           "usage": {"output_tokens": up.usage["output_tokens"]}}),
                        ("message_stop", {"type": "message_stop"}),
                    ]
                    data = b"".join(b"event: %s\ndata: %s\n\n" % (n.encode(), json.dumps(d).encode())
                                    for n, d in events)
                    ctype = "text/event-stream"
                else:
                    data = json.dumps({"id": "m1", "type": "message", "model": up.model,
                                       "content": [{"type": "text", "text": "hi"}], "usage": up.usage}).encode()
                    ctype = "application/json"
                self.send_response(200)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
