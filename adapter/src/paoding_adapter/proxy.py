"""端点代理（§3.4.2、§3.5.2）：容器外的唯一模型出口。三件事：

1. 换密钥：会话只持有任务令牌（x-api-key 或 Authorization: Bearer），代理换成真实密钥再转发上游。
   真实密钥只在本进程里，从不进入模型容器与执行容器（I6、3.5.5 的 3）。
2. 逐请求计量：从响应的 usage 记下 input/cache_read/cache_write/output，按带版本的价目表折成毫美元，
   以 cost 事件（source=proxy）交给图服务。流式响应边转发边解析 SSE。
3. 超额拒绝：任务花费达到预留额、题花费达到题上限、或全局上限（M0 暂定 500 美元）用尽，新请求直接 429。
   任务令牌在租约释放后作废，带它的请求 401。

只用标准库：ThreadingHTTPServer 收，http.client 转发。不调用模型 SDK：代理是透明转发，客户端是 CLI。
"""
from __future__ import annotations

import http.client
import json
import threading
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from paoding_graph.contract import GraphPort

HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization",
       "proxy-authenticate", "host", "content-length", "x-api-key", "authorization"}


@dataclass
class PriceTable:
    version: str
    models: dict

    @classmethod
    def load(cls, path: str | Path) -> "PriceTable":
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(d["version"], d["models"])

    def usd_milli(self, model: str, u: dict) -> int:
        p = self.models.get(model)
        if p is None:                                   # 未知模型按最贵档计，宁多勿少
            p = max(self.models.values(), key=lambda x: x["output"])
        micro = (u.get("input_tokens", 0) * p["input"] + u.get("output_tokens", 0) * p["output"]
                 + u.get("cache_read_input_tokens", 0) * p["cache_read"]
                 + u.get("cache_creation_input_tokens", 0) * p["cache_write"])   # 美元×1e6/1e6 token
        return -(-int(round(micro * 1000)) // 1_000_000)                          # 毫美元，向上取整


@dataclass
class Task:
    token: str
    lease_id: str
    pid: str
    reserve_usd_milli: int
    spent_usd_milli: int = 0
    requests: int = 0
    revoked: bool = False


@dataclass
class ProxyConfig:
    upstream: str                       # 例如 https://api.anthropic.com
    api_key: str                        # 真实密钥，只在本进程
    adapter_token: str                  # 向图服务提交 cost 事件用的组件令牌
    global_cap_usd_milli: int = 500_000  # M0 总额上限，暂定 500 美元
    problem_caps: dict = field(default_factory=dict)   # pid → usd_milli


class EndpointProxy:
    def __init__(self, cfg: ProxyConfig, prices: PriceTable, graph: GraphPort):
        self.cfg, self.prices, self.graph = cfg, prices, graph
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self.global_spent = 0
        self.problem_spent: dict[str, int] = {}
        self.server: ThreadingHTTPServer | None = None
        self.url = ""

    # ---------- 任务令牌 ----------

    def register_task(self, token: str, lease_id: str, pid: str, reserve_usd_milli: int) -> None:
        with self._lock:
            self._tasks[token] = Task(token, lease_id, pid, reserve_usd_milli)

    def revoke(self, token: str) -> None:
        with self._lock:
            if token in self._tasks:
                self._tasks[token].revoked = True

    def task(self, token: str) -> Task | None:
        return self._tasks.get(token)

    def admit(self, token: str | None) -> tuple[int, str, Task | None, int]:
        """返回 (HTTP 状态, 原因, 任务, 本任务第几个请求)。200 表示放行。"""
        with self._lock:
            t = self._tasks.get(token or "")
            if t is None or t.revoked:
                return 401, "unknown_or_revoked_token", None, 0
            if t.spent_usd_milli >= t.reserve_usd_milli:
                return 429, "task_reserve_exhausted", t, 0
            cap = self.cfg.problem_caps.get(t.pid)
            if cap is not None and self.problem_spent.get(t.pid, 0) >= cap:
                return 429, "problem_budget_exhausted", t, 0
            if self.global_spent >= self.cfg.global_cap_usd_milli:
                return 429, "global_cap_exhausted", t, 0
            t.requests += 1
            return 200, "ok", t, t.requests

    def charge(self, t: Task, n: int, model: str, usage: dict) -> int:
        """n 取自 admit，做幂等键：同一请求重复上报只记一次。"""
        usd = self.prices.usd_milli(model, usage)
        with self._lock:
            t.spent_usd_milli += usd
            self.global_spent += usd
            self.problem_spent[t.pid] = self.problem_spent.get(t.pid, 0) + usd
        self.graph.submit(self.cfg.adapter_token, t.pid, f"cost:{t.lease_id}:{n}", [{"op": "cost", "body": {
            "task_id": t.lease_id, "source": "proxy", "model": model,
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_cached": usage.get("cache_read_input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0),
            "usd_milli": usd, "wall_s": 0, "price_table": self.prices.version}}])
        return usd

    # ---------- HTTP ----------

    def serve(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):          # 不把请求打到 stderr
                pass

            def _token(self) -> str | None:
                if self.headers.get("x-api-key"):
                    return self.headers["x-api-key"]
                auth = self.headers.get("authorization", "")
                return auth[7:] if auth.lower().startswith("bearer ") else None

            def _reject(self, code: int, why: str) -> None:
                body = json.dumps({"type": "error", "error": {"type": why, "message": why}}).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._forward(None)

            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                self._forward(self.rfile.read(n))

            def _forward(self, body: bytes | None) -> None:
                status, why, task, n = proxy.admit(self._token())
                if status != 200:
                    return self._reject(status, why)
                up = urllib.parse.urlsplit(proxy.cfg.upstream)
                conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
                conn = conn_cls(up.netloc, timeout=600)
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
                headers["x-api-key"] = proxy.cfg.api_key
                path = (up.path.rstrip("/") + self.path) if up.path else self.path
                try:
                    conn.request(self.command, path, body=body, headers=headers)
                    resp = conn.getresponse()
                except OSError as e:
                    return self._reject(502, f"upstream_error:{type(e).__name__}")
                ctype = resp.getheader("content-type", "")
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in HOP:
                        self.send_header(k, v)
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()
                meter = _Meter(ctype.startswith("text/event-stream"))
                client_gone = False
                try:
                    while chunk := resp.read1(65536):
                        meter.feed(chunk)
                        if not client_gone:
                            try:
                                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                            except OSError:          # 客户端断开：继续读完上游，用量照记
                                client_gone = True
                except OSError:
                    pass
                finally:
                    conn.close()
                    model, usage = meter.result()
                    if usage:                        # 先入账再收尾：客户端见到响应结束时 cost 事件已落盘
                        proxy.charge(task, n, model, usage)
                if not client_gone:
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                    except OSError:
                        pass

        self.server = ThreadingHTTPServer((host, port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        h, p = self.server.server_address[:2]
        self.url = f"http://{h}:{p}"
        return h, p

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


class _Meter:
    """从非流式 JSON 或 SSE 流里取出 model 与 usage。message_start 给输入侧，message_delta 给累计输出。"""

    def __init__(self, sse: bool):
        self.sse, self.buf, self.model, self.usage = sse, b"", "", {}

    def feed(self, chunk: bytes) -> None:
        self.buf += chunk
        if not self.sse:
            return
        while b"\n\n" in self.buf:
            event, self.buf = self.buf.split(b"\n\n", 1)
            for line in event.split(b"\n"):
                if line.startswith(b"data:"):
                    self._take(line[5:].strip())

    def _take(self, raw: bytes) -> None:
        try:
            d = json.loads(raw)
        except ValueError:
            return
        if d.get("type") == "message_start":
            m = d.get("message", {})
            self.model = m.get("model", self.model)
            self.usage.update({k: v for k, v in (m.get("usage") or {}).items() if isinstance(v, int)})
        elif d.get("type") == "message_delta":
            self.usage.update({k: v for k, v in (d.get("usage") or {}).items() if isinstance(v, int)})

    def result(self) -> tuple[str, dict[str, Any]]:
        if not self.sse:
            try:
                d = json.loads(self.buf)
                return d.get("model", ""), {k: v for k, v in (d.get("usage") or {}).items() if isinstance(v, int)}
            except ValueError:
                return "", {}
        return self.model, self.usage
