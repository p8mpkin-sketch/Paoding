"""模型“测试连接”（前端重新设计 v5 第二期）：POST /v1/models/test 按档案实际调一次上游，测通才让存。

假上游是本进程里的 HTTP 服务：按密钥与模型 ID 回 200 / 401 / 404。密钥只从钥匙环取，回给页面的说明里不带密钥。
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

from settings_hub import probe  # noqa: E402
from test_settings_keys import make, req  # noqa: E402

from paoding_adapter.contract import KeyRing  # noqa: E402

GOOD = "sk-probe-good-0001"
SEEN: list[dict] = []


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a: object) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        SEEN.append(
            {
                "path": self.path,
                "key": self.headers.get("x-api-key"),
                "version": self.headers.get("anthropic-version"),
                "body": body,
            }
        )
        if self.headers.get("x-api-key") != GOOD:
            code, out = (
                401,
                {
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": "invalid x-api-key " + str(self.headers.get("x-api-key")),
                    },
                },
            )
        elif body["model"] != "m-1":
            code, out = 404, {"type": "error", "error": {"type": "not_found_error", "message": "model not found"}}
        else:
            code, out = (
                200,
                {
                    "type": "message",
                    "content": [{"type": "text", "text": "p"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )
        raw = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def upstream() -> Iterator[str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SEEN.clear()
    yield f"http://127.0.0.1:{srv.server_address[1]}/api"
    srv.shutdown()


def test_probe_outcomes(upstream):
    ring = KeyRing({"default": "", "bad": ""})
    ring.set("default", GOOD)
    ring.set("bad", "sk-probe-wrong-9999")
    ok = probe({"endpoint": upstream, "model": "m-1", "key_slot": "default"}, ring, "")
    assert ok["ok"] is True and ok["status"] == 200 and ok["latency_ms"] >= 0
    seen = SEEN[-1]
    assert seen["path"] == "/api/v1/messages" and seen["version"] == "2023-06-01" and seen["body"]["max_tokens"] == 1

    bad = probe({"endpoint": upstream, "model": "m-1", "key_slot": "bad"}, ring, "")
    assert bad["ok"] is False and bad["code"] == "bad_key" and bad["status"] == 401
    assert "sk-probe-wrong-9999" not in json.dumps(bad)  # 上游把密钥回显在错误里，也要去掉

    nf = probe({"endpoint": upstream, "model": "m-2", "key_slot": "default"}, ring, "")
    assert nf["code"] == "not_found" and "model not found" in nf["message"]

    # 档案没写地址时用代理的缺省上游
    assert probe({"endpoint": "", "model": "m-1", "key_slot": "default"}, ring, upstream)["ok"] is True


@pytest.mark.parametrize(
    ("profile", "code"),
    [
        ({"endpoint": "http://127.0.0.1:9", "model": "", "key_slot": "default"}, "no_model"),
        ({"endpoint": "http://127.0.0.1:9", "model": "m", "key_slot": "empty"}, "key_not_set"),
        ({"endpoint": "ftp://x", "model": "m", "key_slot": "default"}, "bad_endpoint"),
        ({"endpoint": "http://127.0.0.1:9", "model": "m", "key_slot": "BAD SLOT"}, "bad_slot"),
        ({"endpoint": "http://127.0.0.1:9", "model": "m", "key_slot": "default"}, "unreachable"),
    ],
)
def test_probe_refuses_before_or_fails_cleanly(profile, code):
    ring = KeyRing({"default": "", "empty": ""})
    ring.set("default", GOOD)
    out = probe(profile, ring, "")
    assert out["ok"] is False and out["code"] == code and GOOD not in json.dumps(out)


def test_endpoint_needs_human_and_profile(tmp_path, upstream):
    s = make(tmp_path)
    s.start()
    try:
        url, tok = s.url, s.human_token
        prof = {"endpoint": upstream, "model": "m-1", "key_slot": "probe"}
        assert req(url, "POST", "/v1/models/test", {"profile": prof})[0] == 401
        assert req(url, "POST", "/v1/models/test", {"x": 1}, tok)[0] == 400
        assert (
            req(url, "POST", "/v1/models/test", {"profile": {**prof, "api_key": "sk-x"}}, tok)[0] == 400
        )  # 密钥不走请求体
        assert req(url, "PUT", "/v1/keys/probe", {"key": GOOD}, tok)[0] == 200
        code, out = req(url, "POST", "/v1/models/test", {"profile": prof}, tok)
        assert code == 200 and out["ok"] is True
        assert req(url, "GET", "/v1/settings")[1]["version"] == 1  # 测试不改设置
    finally:
        s.stop()


def test_probe_openai_format():
    """format=openai：调 {endpoint}/chat/completions，Bearer 密钥，不带 Anthropic 的头；没写地址就拒绝。"""
    from paoding_adapter.fakeupstream import FakeUpstream

    up = FakeUpstream({"prompt_tokens": 1, "completion_tokens": 1}, model="m-1")
    try:
        ring = KeyRing({"default": ""})
        ring.set("default", GOOD)
        ok = probe({"endpoint": up.url + "/v1", "model": "m-1", "key_slot": "default", "format": "openai"}, ring, "")
        assert ok["ok"] is True
        seen = up.seen[-1]
        h = {k.lower(): v for k, v in seen["headers"].items()}
        assert seen["path"] == "/v1/chat/completions" and h["authorization"] == f"Bearer {GOOD}"
        assert "x-api-key" not in h and "anthropic-version" not in h and seen["body"]["max_tokens"] == 1
        no_ep = probe({"endpoint": "", "model": "m-1", "key_slot": "default", "format": "openai"}, ring, up.url)
        assert no_ep["code"] == "bad_endpoint"
        assert (
            probe({"endpoint": up.url, "model": "m-1", "key_slot": "default", "format": "x"}, ring, "")["code"]
            == "bad_format"
        )
    finally:
        up.close()
