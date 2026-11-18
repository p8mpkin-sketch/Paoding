"""工具端点（§3.4.2）：把三个代理工具以 MCP 的 HTTP 传输挂给 CLI。

只实现 CLI 用到的最小子集：initialize、notifications/*、tools/list、tools/call、ping。
每个会话一个路径 /mcp/<key>，key 随机且只写进该会话的 --mcp-config 文件；
一个 Adapter 进程可以并行托管多个会话（3.4.4）。响应一律 application/json（不开 SSE 推送）。
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .tools import ToolHost, as_text, tool_schemas

PROTOCOL_VERSION = "2025-06-18"


class ToolEndpoint:
    def __init__(self) -> None:
        self._hosts: dict[str, ToolHost] = {}
        self._lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.base = ""

    def mount(self, host: ToolHost) -> str:
        key = secrets.token_urlsafe(24)
        with self._lock:
            self._hosts[key] = host
        return f"{self.base}/mcp/{key}"

    def unmount(self, url: str) -> None:
        with self._lock:
            self._hosts.pop(url.rsplit("/", 1)[-1], None)

    def handle(self, key: str, msg: dict) -> dict | None:
        host = self._hosts.get(key)
        mid, method = msg.get("id"), msg.get("method", "")
        if host is None:
            return _rpc_err(mid, -32001, "会话不存在或已结束")
        if mid is None:  # 通知不回
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "paoding", "version": "0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_schemas(host.s.tools)}}
        if method == "tools/call":
            p = msg.get("params") or {}
            try:
                out = host.call(str(p.get("name")), p.get("arguments") or {})
            except Exception as e:  # noqa: BLE001  进程边界：本组件或下游的缺陷，留栈并如实报成内部错误
                traceback.print_exc(file=sys.stderr)
                return _rpc_err(mid, -32603, f"内部错误：{type(e).__name__}")
            is_err = out.get("ok") is False
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": as_text(out)}],
                    "structuredContent": out,
                    "isError": is_err,
                },
            }
        return _rpc_err(mid, -32601, f"未实现 {method}")

    def serve(self, host: str = "127.0.0.1", port: int = 0) -> str:
        ep = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code: int, obj: dict | None) -> None:
                data = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                if obj is not None:
                    self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                parts = self.path.split("/")
                if len(parts) != 3 or parts[1] != "mcp":
                    return self._send(404, _rpc_err(None, -32001, "未知路径"))
                try:
                    msg = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
                except ValueError:
                    return self._send(400, _rpc_err(None, -32700, "JSON 解析失败"))
                if isinstance(msg, list):
                    outs = [o for o in (ep.handle(parts[2], m) for m in msg) if o is not None]
                    return self._send(200, outs) if outs else self._send(202, None)
                out = ep.handle(parts[2], msg)
                self._send(202, None) if out is None else self._send(200, out)

            def do_GET(self):  # 不提供服务端推送流
                self._send(405, None)

            def do_DELETE(self):
                self._send(200, None)

        self.server = ThreadingHTTPServer((host, port), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        h, p = self.server.server_address[:2]
        self.base = f"http://{h}:{p}"
        return self.base

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def _rpc_err(mid, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}
