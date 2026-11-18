"""端点代理的转发（真实测试报告：CLI 经代理调 DeepSeek 无响应，直连正常）。

复现到的机制：代理连不上上游（例如本机 Python 找不到 CA，TLS 握手失败）时回 502，CLI 静默重试几分钟，
stderr 又被丢掉，看上去就是“没有响应”。这里全用本机假上游（https 的用临时自签证书），不碰真模型：
- 上游是 https 且证书可信：照常转发、计量
- 证书不可信：立刻 502，正文与日志都写明 SSL 错误
- 系统没配 CA 时 tls_context 退到常见的证书包
- 分块传输的请求体照样转发；计量出错不吞掉响应的收尾
- CLI 的 stderr 落到会话目录
- 装了真 CLI 时：真 CLI → 代理 → 仿 DeepSeek 的假上游，走通一轮（没装则跳过）
"""

import http.client
import json
import logging
import os
import shutil
import ssl
import subprocess
import sys
import time

import pytest
from adapter_rig import PRICES, graph, lease_bootstrap, open_problem, rig, upstream  # noqa: F401  fixture

from paoding_adapter import proxy as proxy_mod
from paoding_adapter.fakeupstream import FakeUpstream
from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig
from paoding_adapter.session import CLI_STDERR, local_launcher


@pytest.fixture(scope="module")
def cert(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("没有 openssl，生成不了自签证书")
    d = tmp_path_factory.mktemp("tls")
    key, crt = d / "key.pem", d / "cert.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "1",
         "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
        check=True, capture_output=True,
    )  # fmt: skip
    return str(crt), str(key)


def _proxy(graph, upstream_url):
    open_problem(graph)
    p = EndpointProxy(
        ProxyConfig(upstream_url + "/anthropic", "sk-fake", "tok-adapter"), PriceTable.load(PRICES), graph
    )
    p.serve()
    lid = lease_bootstrap(graph)
    p.register_task("t", lid, "p1", 100_000)
    return p


def _post(p, body: bytes, extra=None, chunked=False):
    host, port = p.server.server_address[:2]
    c = http.client.HTTPConnection(host, port, timeout=10)
    hdr = {"x-api-key": "t", "content-type": "application/json", **(extra or {})}
    c.request("POST", "/v1/messages?beta=true", body=iter([body]) if chunked else body, headers=hdr,
              encode_chunked=chunked)  # fmt: skip
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


BODY = json.dumps({"model": "deepseek-chat", "max_tokens": 5, "stream": True, "messages": []}).encode()


def costs(graph):
    return [c for c in graph.state["costs"] if c["source"] == "proxy"]


def test_https_upstream_trusted_forwards(graph, cert, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="adapter")
    monkeypatch.setenv("SSL_CERT_FILE", cert[0])
    up = FakeUpstream(model="deepseek-chat", dialect={"crlf": True, "usage_at": "delta"}, tls=cert)
    p = _proxy(graph, up.url)
    try:
        assert p.tls_source == "SSL_CERT_FILE/SSL_CERT_DIR"
        st, data = _post(p, BODY)
        assert st == 200 and b"message_stop" in data
        assert up.seen[0]["path"] == "/anthropic/v1/messages?beta=true"
        assert costs(graph)[0]["usd_milli"] > 0
        assert any("→ 上游 https://localhost" in r.getMessage() and " 200（" in r.getMessage() for r in caplog.records)
    finally:
        p.close()
        up.close()


def test_https_upstream_untrusted_502_fast_and_logged(graph, cert, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="adapter")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    up = FakeUpstream(tls=cert)
    p = _proxy(graph, up.url)
    try:
        t0 = time.monotonic()
        st, data = _post(p, BODY)
        assert st == 502 and time.monotonic() - t0 < 5
        msg = json.loads(data)["error"]["message"]
        assert "SSLCertVerificationError" in msg or "CERTIFICATE_VERIFY_FAILED" in msg, msg
        [err] = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert "连不上" in err.getMessage() and "TLS 证书来源" in err.getMessage()
        assert costs(graph) == []
    finally:
        p.close()
        up.close()


def test_tls_context_falls_back_to_known_bundle(monkeypatch, cert):
    """macOS 上 python.org / uv 装的 Python 常常没有缺省 CA：退到常见证书包位置。"""
    for k in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ssl, "get_default_verify_paths",
                        lambda: ssl.DefaultVerifyPaths("/nope/cert.pem", "/nope/certs", "SSL_CERT_FILE", "/nope",
                                                       "SSL_CERT_DIR", "/nope"))  # fmt: skip
    real = ssl.create_default_context

    def bare():
        ctx = real()
        ctx.cert_store_stats = lambda: {"x509_ca": 0}  # type: ignore[method-assign]
        return ctx

    monkeypatch.setattr(ssl, "create_default_context", bare)
    monkeypatch.setitem(sys.modules, "certifi", None)  # 没装 certifi
    monkeypatch.setattr(proxy_mod, "CA_CANDIDATES", ("/nope/a.pem", cert[0]))
    ctx, src = proxy_mod.tls_context()
    assert src == cert[0]
    monkeypatch.setattr(proxy_mod, "CA_CANDIDATES", ("/nope/a.pem",))
    assert proxy_mod.tls_context()[1] == "none"


def test_chunked_request_body_forwarded(graph):
    up = FakeUpstream()
    p = _proxy(graph, up.url)
    try:
        st, _ = _post(p, BODY, chunked=True)
        assert st == 200 and up.seen[0]["body"]["model"] == "deepseek-chat"
        st, _ = _post(p, BODY)  # 同一个代理接着处理下一个请求，没有被残留字节卡住
        assert st == 200 and len(up.seen) == 2
    finally:
        p.close()
        up.close()


def test_metering_failure_still_finishes_response(graph, monkeypatch, caplog):
    up = FakeUpstream()
    p = _proxy(graph, up.url)

    def boom(*a, **k):
        raise RuntimeError("账本挂了")

    monkeypatch.setattr(p, "charge", boom)
    try:
        st, data = _post(p, BODY)  # 收尾那一块照写：客户端不会一直等
        assert st == 200 and b"message_stop" in data
        assert any("入账失败" in r.getMessage() for r in caplog.records)
    finally:
        p.close()
        up.close()


def test_cli_stderr_goes_to_session_dir(tmp_path):
    ws = tmp_path / "l_9" / "workspace"
    ws.mkdir(parents=True)
    proc = local_launcher(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom: 无法连接')"], dict(os.environ), ws
    )
    proc.wait()
    proc.stdout.close()
    assert (tmp_path / "l_9" / CLI_STDERR).read_text(encoding="utf-8") == "boom: 无法连接"


@pytest.mark.skipif(not shutil.which("claude"), reason="没装真 CLI")
def test_real_cli_through_proxy_to_deepseek_like_upstream(graph, tmp_path):
    """真 CLI（不连真模型）经代理到仿 DeepSeek 的假上游：CRLF、gzip、usage 全在 message_delta。"""
    up = FakeUpstream(model="deepseek-chat", dialect={"crlf": True, "gzip": True, "usage_at": "delta"})
    p = _proxy(graph, up.url)
    (tmp_path / "home").mkdir()
    env = {"ANTHROPIC_BASE_URL": p.url, "ANTHROPIC_API_KEY": "t", "HOME": str(tmp_path / "home"),
           "PATH": os.environ["PATH"], "LANG": "C.UTF-8"}  # fmt: skip
    try:
        r = subprocess.run(["claude", "-p", "hi", "--bare", "--output-format", "stream-json", "--verbose"], env=env,
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=60)  # fmt: skip
        out = [json.loads(line) for line in r.stdout.decode().splitlines() if line.startswith("{")]
        result = [e for e in out if e.get("type") == "result"]
        assert r.returncode == 0 and result and result[-1]["result"] == "hi", r.stderr.decode()[-500:]
        assert costs(graph) and all(c["usd_milli"] > 0 for c in costs(graph))
    finally:
        p.close()
        up.close()


def test_cli_that_cannot_start_fails_the_lease_visibly(rig, caplog):
    """CLI 命令不存在：会话按 failed(launch) 释放租约，原因写进 cli.stderr.log 与日志（不再悄悄挂着等过期）。"""
    from paoding_adapter import backend as be

    caplog.set_level(logging.ERROR, logger="adapter")
    rig.cfg.binding = be.CliBinding(program=["/nonexistent/claude"])
    lid = lease_bootstrap(rig.graph)
    rec = rig.run(lid)
    assert rec.status == "failed(launch)" and rec.release["ok"] and rec.release["outcome"] == "failed"
    assert "/nonexistent/claude" in (rig.cfg.root / lid / CLI_STDERR).read_text(encoding="utf-8")
    assert any("CLI 起不来" in r.getMessage() for r in caplog.records)
