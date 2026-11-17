"""adapter 测试台：真图服务（SQLite 临时文件）+ 本机假上游。不碰真密钥、真模型。"""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from paoding_graph.contract import Config, GraphService, TokenRegistry

ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "config" / "prices.yaml"

CFG = Config(judges={
    "replay": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.01},
    "exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0},
}, external_resources=frozenset())


def open_problem(svc, pid="p1", usd_milli=5000):
    st = b"statement " + pid.encode()
    return svc.submit("tok-human", pid, f"open-{pid}", [
        {"op": "register_artifact", "body": {"hash": hashlib.sha256(st).hexdigest(), "size": len(st),
                                              "media_type": "text/plain", "class": "input"}},
        {"op": "open_problem", "body": {
            "title": "t", "origin": {"statement_ref": "$0", "materials": []},
            "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
            "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
            "budget": {"usd_milli": usd_milli, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
            "env": {"base": "basic", "baseline_ref": "base@1"}, "judges": ["exact_match", "replay"]}}])


@pytest.fixture
def graph(tmp_path):
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": "cz"}, "tok-human")
    reg.issue({"kind": "sinan", "id": "sn1"}, "tok-sinan")
    reg.issue({"kind": "adapter", "id": "ad1"}, "tok-adapter")
    reg.issue({"kind": "executor", "id": "ex1"}, "tok-exec")
    t = [1000]

    def tick():
        t[0] += 1
        return t[0]
    svc = GraphService(tmp_path / "g.sqlite", CFG, reg, tick)
    return svc


def lease_bootstrap(svc, pid="p1", reserve=1000):
    out = svc.submit("tok-sinan", pid, f"lease-{pid}", [{"op": "lease", "body": {
        "kind": "bootstrap", "holder": "sn1", "reserve": {"usd_milli": reserve, "wall_s": 600}, "ttl_s": 600}}])
    assert out["ok"], out
    return out["results"][0]["id"]


class FakeUpstream:
    """假模型端点：记录收到的请求头，按请求体 stream 字段回 JSON 或 SSE，usage 由测试指定。"""

    def __init__(self):
        self.seen: list[dict] = []
        self.usage = {"input_tokens": 1000, "output_tokens": 200,
                      "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 100}
        self.model = "claude-sonnet-5-5"
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

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def upstream():
    u = FakeUpstream()
    yield u
    u.close()


# ---------- 会话测试台：图服务 + Blob + 端点代理 + 工具端点 + 假执行层 + 假 CLI ----------

import hashlib as _hl  # noqa: E402

from paoding_graph.contract import BlobStore  # noqa: E402


class FakeExec:
    """ExecPort 的进程内替身：不起容器，按执行层同一形状登记 exec 类 Artifact（执行层令牌）。"""

    def __init__(self, graph, blobs):
        self.graph, self.blobs, self.calls = graph, blobs, []

    def exec(self, sid, cmd, pid, idem_key, timeout_s=60, cwd="/workspace", register_as="exec"):
        from paoding_executor.contract import ExecResult
        self.calls.append(cmd)
        data = f"$ {cmd}\nok\n".encode()
        h = self.blobs.put(data)
        prov = {"sandbox_id": sid, "base": "basic", "baseline_ref": "base@1", "tool": "shell", "command": cmd,
                "cwd": cwd, "exit_code": 0, "touched": [], "started_at": 1, "ended_at": 2, "truncated": False}
        out = self.graph.submit("tok-exec", pid, idem_key, [{"op": "register_artifact", "body": {
            "hash": h, "size": len(data), "media_type": "text/plain; charset=utf-8", "class": "exec", "exec": prov}}])
        assert out["ok"], out
        return ExecResult(out["results"][0]["id"], h, 0, data.decode(), False, prov)


class Rig:
    def __init__(self, tmp_path, graph, upstream):
        from paoding_adapter import backend as be
        from paoding_adapter.mcp import ToolEndpoint
        from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig
        from paoding_adapter.session import AdapterConfig, SessionRunner
        self.tmp, self.graph, self.upstream = tmp_path, graph, upstream
        self.blobs = BlobStore(tmp_path / "blobs")
        self.proxy = EndpointProxy(ProxyConfig(upstream.url, "sk-fake-upstream", "tok-adapter"),
                                   PriceTable.load(PRICES), graph)
        self.proxy.serve()
        self.endpoint = ToolEndpoint()
        self.endpoint.serve()
        self.executor = FakeExec(graph, self.blobs)
        self.cfg = AdapterConfig(root=tmp_path / "sessions", renew_s=60, stall_s=30, judges_cfg=CFG.judges,
                                 binding=be.CliBinding(program=be.fake_program()))
        self.runner = SessionRunner(self.cfg, graph, graph, self.blobs, graph.tokens, self.proxy,
                                    self.endpoint, self.executor)
        self.statement = "statement p1"

    def put_input(self, content: bytes, pid="p1"):
        h = self.blobs.put(content)
        out = self.graph.submit("tok-human", pid, "in-" + _hl.sha256(content).hexdigest()[:8], [
            {"op": "register_artifact", "body": {"hash": h, "size": len(content), "media_type": "text/plain",
                                                 "class": "input"}}])
        return out["results"][0]["id"]

    def script(self, steps, resume_steps=()):
        p = self.tmp / f"script-{len(list(self.tmp.glob('script-*')))}.json"
        p.write_text(json.dumps({"steps": list(steps), "resume_steps": list(resume_steps)}))
        self.cfg.extra_env = {"PD_FAKE_SCRIPT": str(p)}
        return p

    def run(self, lease_id, pid="p1", **kw):
        return self.runner.run(pid, lease_id, statement=self.statement, sandbox_id="sb-test", **kw)

    def close(self):
        self.proxy.close()
        self.endpoint.close()


@pytest.fixture
def rig(tmp_path, graph, upstream):
    r = Rig(tmp_path, graph, upstream)
    open_problem(graph)
    yield r
    r.close()
