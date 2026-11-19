"""端点代理（§3.4.2、§3.5.2）：容器外的唯一模型出口。三件事：

1. 换密钥：会话只持有任务令牌（x-api-key 或 Authorization: Bearer），代理换成真实密钥再转发上游。
   真实密钥只在本进程里，从不进入模型容器与执行容器（I6、3.5.5 的 3）。
2. 逐请求计量：从响应的 usage 记下 input/cache_read/cache_write/output，按带版本的价目表折成毫美元，
   以 cost 事件（source=proxy）交给图服务。流式响应边转发边解析 SSE。
3. 超额拒绝：任务花费达到预留额、题花费达到题上限、或全局上限（M0 暂定 500 美元）用尽，新请求直接 429。
   任务令牌在租约释放后作废，带它的请求 401。
   全局与按题的累计花费在启动时从图服务的账本投影（/budget）恢复：进程重启后不归零，硬顶继续有效。

只用标准库：ThreadingHTTPServer 收，http.client 转发。不调用模型 SDK：代理是透明转发，客户端是 CLI。

计量要兼容 Anthropic 兼容端点的方言（真实测试报告 P0-C：DeepSeek 上全程记 $0.000）：
- 向上游只要未压缩的响应（accept-encoding: identity）；上游仍压缩的（gzip、deflate）边转发边解压来计量，
  转给客户端的字节不变。
- SSE 的事件分隔认 \n\n、\r\n\r\n 与 \r\r；usage 在 message_start、message_delta 任一处或两处都行，
  值为 null 的字段不算。
- 字段名认 Anthropic 的 input/output/cache_read_input/cache_creation_input_tokens，也认 OpenAI 式的
  prompt/completion_tokens 与 DeepSeek 的 prompt_cache_hit/miss_tokens（见 normalize_usage）。
- 成功的 /v1/messages 响应里一个用量字段都取不到时，按字节数估 token（宁多勿少）再乘价目表，
  cost 事件的 price_table 带 “+estimated” 后缀，并记一条警告。
- 每个请求记一行日志（logger “adapter”）：任务、模型、上游给的原始 usage、折算的毫美元。
"""

from __future__ import annotations

import http.client
import json
import logging
import math
import os
import secrets
import ssl
import threading
import time
import urllib.parse
import zlib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from paoding_graph.contract import GraphPort, GraphReader

from .keyring import KeyRing

LOG = logging.getLogger("adapter")
# 系统没配好 CA 时（macOS 上 python.org 与 uv 装的 Python 常见）依次试的证书包
CA_CANDIDATES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt")


def tls_context() -> tuple[ssl.SSLContext, str]:
    """连上游用的 TLS 上下文与它的 CA 来源（记进日志）。

    真实测试报告：CLI 经代理调 DeepSeek 无响应。代理连上游的 TLS 握手要是因为本机 Python 找不到 CA 而失败，
    代理回 502，CLI 默默重试几分钟再退出，看上去就是“没有响应”。所以：SSL_CERT_FILE / SSL_CERT_DIR 有就用
    （OpenSSL 自己认）；系统缺省路径里有证书就用；都没有再试 certifi（装了的话）与几个常见的证书包位置。"""
    ctx = ssl.create_default_context()
    paths = ssl.get_default_verify_paths()
    if os.environ.get(paths.openssl_cafile_env) or os.environ.get(paths.openssl_capath_env):
        return ctx, "SSL_CERT_FILE/SSL_CERT_DIR"
    if (paths.cafile and os.path.isfile(paths.cafile)) or (
        paths.capath and os.path.isdir(paths.capath) and any(os.scandir(paths.capath))
    ):
        return ctx, "system"
    if ctx.cert_store_stats().get("x509_ca"):  # macOS 等从系统钥匙串之类的地方装进来的
        return ctx, "system"
    candidates: list[str] = []
    try:
        import certifi  # type: ignore[import-not-found]

        candidates.append(certifi.where())
    except ImportError:
        pass
    for ca in (*candidates, *CA_CANDIDATES):
        if os.path.isfile(ca):
            ctx.load_verify_locations(cafile=ca)
            return ctx, ca
    return ctx, "none"  # 连 https 上游必然失败；请求日志里会看到 502 与 SSL 报错


ESTIMATED = "+estimated"
BYTES_PER_TOKEN = 3  # 估算用：英文约 4 字节一个 token，中文约 3 字节；取小的，估多不估少

HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
    "host",
    "content-length",
    "x-api-key",
    "authorization",
    "accept-encoding",
}


@dataclass
class PriceTable:
    version: str
    models: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> PriceTable:
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(d["version"], d["models"])

    def usd_milli(self, model: str, u: dict[str, Any]) -> int:
        p = self.models.get(model)
        if p is None:  # 未知模型按最贵档计，宁多勿少
            p = max(self.models.values(), key=lambda x: x["output"])
        micro = (
            u.get("input_tokens", 0) * p["input"]
            + u.get("output_tokens", 0) * p["output"]
            + u.get("cache_read_input_tokens", 0) * p["cache_read"]
            + u.get("cache_creation_input_tokens", 0) * p["cache_write"]
        )  # 美元×1e6/1e6 token
        return -(-int(round(micro * 1000)) // 1_000_000)  # 毫美元，向上取整


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
    upstream: str  # 例如 https://api.anthropic.com
    api_key: str  # 过渡期：直接给的真实密钥；给了 keyring 时忽略。空串 = 未设
    adapter_token: str  # 向图服务提交 cost 事件用的组件令牌
    global_cap_usd_milli: int = 500_000  # M0 总额上限，暂定 500 美元
    problem_caps: dict[str, Any] = field(default_factory=dict)  # pid → usd_milli
    keyring: KeyRing | None = None  # 真实密钥只在这里（宪章 03 §4）；缺省由 api_key 建一个
    key_slot: str = "default"  # 转发时换上哪个槽的密钥


class EndpointProxy:
    def __init__(self, cfg: ProxyConfig, prices: PriceTable, graph: GraphPort, reader: GraphReader | None = None):
        self.cfg, self.prices, self.graph = cfg, prices, graph
        if cfg.keyring is None:
            cfg.keyring = KeyRing({cfg.key_slot: ""})
            if cfg.api_key:
                cfg.keyring.set(cfg.key_slot, cfg.api_key, source="config")
        cfg.api_key = ""  # 密钥只留在钥匙环里：配置对象可能被打印、比较、序列化
        self.keyring: KeyRing = cfg.keyring
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        # 实例号，进 cost 的幂等键：重启后同一租约的计数重新从 1 起，不能撞上旧键
        self.boot = secrets.token_hex(4)
        self.global_spent = 0
        self.problem_spent: dict[str, int] = {}
        # 启动时从账本恢复的基线：seq 是恢复时的链头，对账只比它之后的事件
        self.restored: dict[str, Any] = {"seq": 0, "global": 0, "problems": {}}
        self.server: ThreadingHTTPServer | None = None
        self.tls, self.tls_source = tls_context()
        self.url = ""
        if reader is not None:
            self.restore(reader)

    # ---------- 启动恢复 ----------

    def restore(self, reader: GraphReader) -> dict[str, Any]:
        """从图服务的账本投影（GET /budget 的进程内形态）恢复累计花费。在开始收请求之前调用。

        图是账本，代理只是计量点：进程重启后，按题花费取各题 /budget 的 spent.usd_milli，全局花费取各题之和
        （已关的题也算，钱已经花了）。取的是账本里这道题的全部花费，不只是本代理入账的那部分：
        硬顶宁紧勿松。任务级的花费不恢复：任务令牌只在进程内存里，旧进程的会话随进程结束，租约由哮天犬回收。"""
        st = reader.state
        problems = {pid: int(reader.budget(pid)["spent"]["usd_milli"]) for pid in sorted(st["problems"])}
        with self._lock:
            self.problem_spent = dict(problems)
            self.global_spent = sum(problems.values())
            self.restored = {"seq": int(st.get("seq", 0)), "global": self.global_spent, "problems": problems}
        return self.restored

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

    def charge(self, t: Task, n: int, model: str, usage: dict[str, Any], estimated: bool = False) -> int:
        """n 取自 admit，做幂等键：同一请求重复上报只记一次。usage 是 normalize_usage 之后的形状。"""
        usd = self.prices.usd_milli(model, usage)
        with self._lock:
            t.spent_usd_milli += usd
            self.global_spent += usd
            self.problem_spent[t.pid] = self.problem_spent.get(t.pid, 0) + usd
        self.graph.submit(
            self.cfg.adapter_token,
            t.pid,
            f"cost:{t.lease_id}:{self.boot}:{n}",
            [
                {
                    "op": "cost",
                    "body": {
                        "task_id": t.lease_id,
                        "source": "proxy",
                        "model": model,
                        "tokens_in": usage.get("input_tokens", 0),
                        "tokens_cached": usage.get("cache_read_input_tokens", 0),
                        "tokens_out": usage.get("output_tokens", 0),
                        "usd_milli": usd,
                        "wall_s": 0,
                        "price_table": self.prices.version + (ESTIMATED if estimated else ""),
                    },
                }
            ],
        )
        return usd

    # ---------- HTTP ----------

    def serve(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:  # 不把请求打到 stderr
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

            def do_GET(self) -> None:
                self._forward(None)

            def do_POST(self) -> None:
                if "chunked" in self.headers.get("transfer-encoding", "").lower():
                    body = _read_chunked(self.rfile)  # 不读完的话，剩下的字节会被当成下一个请求，连接就卡住
                else:
                    body = self.rfile.read(int(self.headers.get("content-length") or 0))
                self._forward(body)

            def _forward(self, body: bytes | None) -> None:
                t0 = time.monotonic()
                status, why, task, n = proxy.admit(self._token())
                if status != 200:
                    LOG.warning("代理：%s %s → %d %s", self.command, self.path, status, why)
                    return self._reject(status, why)
                assert task is not None  # admit 放行（200）时必给任务
                key = proxy.keyring.get(proxy.cfg.key_slot)
                if key is None:
                    LOG.warning("代理：%s %s → 503 key_not_set（槽 %s）", self.command, self.path, proxy.cfg.key_slot)
                    return self._reject(503, "key_not_set")
                up = urllib.parse.urlsplit(proxy.cfg.upstream)
                conn: http.client.HTTPConnection
                if up.scheme == "https":
                    conn = http.client.HTTPSConnection(up.netloc, timeout=600, context=proxy.tls)
                else:
                    conn = http.client.HTTPConnection(up.netloc, timeout=600)
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
                headers["x-api-key"] = key
                headers["accept-encoding"] = "identity"  # 压缩的响应没法边转边计量
                path = (up.path.rstrip("/") + self.path) if up.path else self.path
                try:
                    conn.request(self.command, path, body=body, headers=headers)
                    resp = conn.getresponse()
                except OSError as e:
                    conn.close()
                    LOG.error(
                        "代理：%s %s → 上游 %s://%s%s 连不上：%s: %s（TLS 证书来源 %s）",
                        self.command,
                        self.path,
                        up.scheme,
                        up.netloc,
                        path,
                        type(e).__name__,
                        e,
                        proxy.tls_source,
                    )
                    return self._reject(502, f"upstream_error:{type(e).__name__}: {e}")
                LOG.info(
                    "代理：%s %s → 上游 %s://%s%s %d（%s，首字节 %.1f 秒）%s",
                    self.command,
                    self.path,
                    up.scheme,
                    up.netloc,
                    path,
                    resp.status,
                    resp.getheader("content-type", "-"),
                    time.monotonic() - t0,
                    task.lease_id,
                )
                ctype = resp.getheader("content-type", "")
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in HOP:
                        self.send_header(k, v)
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()
                meter = _Meter(ctype.startswith("text/event-stream"), resp.getheader("content-encoding", ""))
                client_gone = False
                try:
                    while chunk := resp.read1(65536):
                        meter.feed(chunk)
                        if not client_gone:
                            try:
                                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                            except OSError:  # 客户端断开：继续读完上游，用量照记
                                client_gone = True
                except OSError:
                    pass
                finally:
                    conn.close()
                    try:
                        self._meter(task, n, body, resp, ctype, meter)
                    except Exception:  # noqa: BLE001  计量出错不能吞掉响应收尾，否则客户端一直等最后一块
                        LOG.exception("计量：%s 第 %d 个请求入账失败", task.lease_id, n)
                if not client_gone:
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                    except OSError:
                        pass
                if resp.status >= 400:
                    LOG.warning(
                        "代理：%s 上游回 %d，正文头：%s",
                        task.lease_id,
                        resp.status,
                        meter.buf[:300].decode("utf-8", "replace"),
                    )

            def _meter(self, task: Task, n: int, body: bytes | None, resp: Any, ctype: str, meter: _Meter) -> None:
                """取用量、入账、记日志。上游没给用量时按字节估算。"""
                model, raw = meter.result()
                model = model or _req_model(body)
                usage, estimated = normalize_usage(raw), False
                if (
                    not usage
                    and resp.status == 200
                    and self.command == "POST"
                    and urllib.parse.urlsplit(self.path).path.endswith("/v1/messages")
                ):
                    usage, estimated = estimate_usage(body, meter.size), True
                    LOG.warning(
                        "计量：%s 第 %d 个请求的响应里没有可用的 usage（content-type=%s，"
                        "content-encoding=%s），按字节数估算 %s",
                        task.lease_id,
                        n,
                        ctype,
                        resp.getheader("content-encoding", "") or "-",
                        usage,
                    )
                if usage:  # 先入账再收尾：客户端见到响应结束时 cost 事件已落盘
                    usd = proxy.charge(task, n, model, usage, estimated)
                    LOG.info(
                        "计量：%s 第 %d 个请求 model=%s 上游 usage=%s → %d 毫美元%s",
                        task.lease_id,
                        n,
                        model or "?",
                        json.dumps(raw, sort_keys=True),
                        usd,
                        "（估算）" if estimated else "",
                    )

        self.server = ThreadingHTTPServer((host, port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        h, p = str(self.server.server_address[0]), int(self.server.server_address[1])  # AF_INET：(主机, 端口)
        self.url = f"http://{h}:{p}"
        LOG.info(
            "端点代理在 %s，上游 %s（https 的 CA 来源：%s）",
            self.url,
            self.cfg.upstream,
            self.tls_source if self.cfg.upstream.startswith("https") else "不适用",
        )
        return h, p

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def ledger_diff(proxy: EndpointProxy, state: dict[str, Any]) -> list[dict[str, Any]]:
    """对账（3.5.5 的 4、5）：代理自记的逐任务花费与图里 source=proxy 的 cost 事件之和逐项比较。
    返回不一致的条目；空表示对上。图是账本，代理是计量点，两者独立累计。
    代理启动时从账本恢复过基线的，只对恢复之后（seq 大于恢复时链头）的事件逐任务比较，合计加上基线。"""
    base = proxy.restored
    graph_by_task: dict[str, int] = {}
    for c in state["costs"]:
        if c["source"] == "proxy" and c["seq"] > base["seq"]:
            graph_by_task[c["task_id"]] = graph_by_task.get(c["task_id"], 0) + c["usd_milli"]
    proxy_by_task: dict[str, int] = {}
    for t in proxy._tasks.values():
        proxy_by_task[t.lease_id] = proxy_by_task.get(t.lease_id, 0) + t.spent_usd_milli
    diffs = [
        {"task_id": k, "proxy": proxy_by_task.get(k, 0), "graph": graph_by_task.get(k, 0)}
        for k in sorted(set(graph_by_task) | set(proxy_by_task))
        if proxy_by_task.get(k, 0) != graph_by_task.get(k, 0)
    ]
    total = base["global"] + sum(graph_by_task.values())
    if proxy.global_spent != total:
        diffs.append({"task_id": "*", "proxy": proxy.global_spent, "graph": total})
    return diffs


def normalize_usage(raw: dict[str, Any]) -> dict[str, int]:
    """把各家 Anthropic 兼容端点的 usage 折成代理计价用的四个字段；取不到的字段不出现。

    - Anthropic：input_tokens（不含缓存命中）、output_tokens、cache_read_input_tokens、cache_creation_input_tokens
    - OpenAI 式：prompt_tokens（含缓存命中）、completion_tokens、prompt_tokens_details.cached_tokens
    - DeepSeek：prompt_cache_hit_tokens（命中）、prompt_cache_miss_tokens（未命中）
    """

    def num(k: str) -> int | None:
        v = raw.get(k)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None

    details = raw.get("prompt_tokens_details")
    cached_openai = details.get("cached_tokens") if isinstance(details, dict) else None
    hit = next(
        (
            v
            for v in (
                num("cache_read_input_tokens"),
                num("prompt_cache_hit_tokens"),
                cached_openai if isinstance(cached_openai, int) else None,
            )
            if v is not None
        ),
        None,
    )
    inp = num("input_tokens")
    if inp is None:
        inp = num("prompt_cache_miss_tokens")
    prompt = num("prompt_tokens")
    if inp is None and prompt is not None:
        inp = max(0, prompt - (hit or 0))  # prompt_tokens 含命中部分，命中另按缓存价计
    outs = [v for v in (num("output_tokens"), num("completion_tokens")) if v is not None]
    out = max(outs) if outs else None  # 两种名字都出现（各在一个事件里）时取大的，宁多勿少
    u = {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": hit,
        "cache_creation_input_tokens": num("cache_creation_input_tokens"),
    }
    return {k: v for k, v in u.items() if v is not None}


def estimate_usage(request: bytes | None, response_bytes: int) -> dict[str, int]:
    """上游没给 usage 时的兜底：请求体字节数估输入，解压后的响应字节数估输出，都向上取整。"""
    return {
        "input_tokens": math.ceil(len(request or b"") / BYTES_PER_TOKEN),
        "output_tokens": math.ceil(response_bytes / BYTES_PER_TOKEN),
    }


def _req_model(body: bytes | None) -> str:
    try:
        m = json.loads(body or b"{}").get("model", "")
    except (ValueError, AttributeError):
        return ""
    return m if isinstance(m, str) else ""


def _read_chunked(f) -> bytes:  # type: ignore[no-untyped-def]
    out = b""
    while True:
        size = int(f.readline().split(b";")[0].strip() or b"0", 16)
        if size == 0:
            while f.readline() not in (b"\r\n", b"\n", b""):  # 尾部头
                pass
            return out
        out += f.read(size)
        f.readline()


class _Meter:
    """从非流式 JSON 或 SSE 流里取出 model 与原始 usage（未归一）。message_start 给输入侧，message_delta 给累计输出；
    哪边给了什么字段都收，值为 null 的不覆盖已有的数。上游压缩了的先解压（只用于计量，转发的字节不动）。"""

    def __init__(self, sse: bool, encoding: str = ""):
        self.sse, self.buf, self.model = sse, b"", ""
        self.usage: dict[str, Any] = {}
        self.size = 0  # 解压后的响应字节数，估算用
        enc = encoding.strip().lower()
        self._z = (
            zlib.decompressobj(32 + zlib.MAX_WBITS)
            if enc in ("gzip", "x-gzip")
            else zlib.decompressobj()
            if enc == "deflate"
            else None
        )
        self._opaque = enc not in ("", "identity", "gzip", "x-gzip", "deflate")  # 例如 br：标准库解不了

    def feed(self, chunk: bytes) -> None:
        if self._opaque:
            return
        if self._z is not None:
            try:
                chunk = self._z.decompress(chunk)
            except zlib.error:
                self._opaque = True
                return
        self.size += len(chunk)
        self.buf += chunk
        if not self.sse:
            return
        self.buf = self.buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n") if b"\r" in self.buf else self.buf
        while b"\n\n" in self.buf:
            event, self.buf = self.buf.split(b"\n\n", 1)
            for line in event.split(b"\n"):
                if line.startswith(b"data:"):
                    self._take(line[5:].strip())

    def _merge(self, u: object) -> None:
        if isinstance(u, dict):
            self.usage.update({k: v for k, v in u.items() if v is not None})

    def _take(self, raw: bytes) -> None:
        try:
            d = json.loads(raw)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        msg = d.get("message")
        m: dict[str, Any] = msg if isinstance(msg, dict) else {}
        if isinstance(m.get("model"), str):
            self.model = m["model"]
        elif isinstance(d.get("model"), str):
            self.model = d["model"]
        self._merge(m.get("usage"))  # message_start
        self._merge(d.get("usage"))  # message_delta（及把 usage 放在顶层的方言）

    def result(self) -> tuple[str, dict[str, Any]]:
        if self._opaque:
            return "", {}
        if not self.sse:
            try:
                d = json.loads(self.buf)
            except ValueError:
                return "", {}
            if not isinstance(d, dict):
                return "", {}
            self._merge(d.get("usage"))
            return (d["model"] if isinstance(d.get("model"), str) else ""), self.usage
        if self.buf.strip():  # 末尾没有空行收口的最后一个事件
            for line in self.buf.split(b"\n"):
                if line.startswith(b"data:"):
                    self._take(line[5:].strip())
            self.buf = b""
        return self.model, self.usage
