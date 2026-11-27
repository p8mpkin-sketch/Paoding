"""盲判自己的模型调用：两种线格式的请求与应答，密钥只从环境变量取。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from lj_rig import CANARY

from liangju.common import Refused
from liangju.model import TOOLS, HttpClient, JudgeModel, ModelError, Toolbox, ToolCall, with_tools

ANTHROPIC = [
    {
        "model": "j-1",
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 4, "output_tokens": 3},
        "content": [
            {"type": "text", "text": "查一下"},
            {"type": "tool_use", "id": "t1", "name": "search", "input": {"pattern": "MAX_BATCH ="}},
        ],
    },
    {
        "model": "j-1",
        "usage": {"input_tokens": 20, "output_tokens": 5},
        "content": [{"type": "text", "text": '{"verdict": "holds"}'}],
    },
]
OPENAI = [
    {
        "model": "j-2",
        "usage": {"prompt_tokens": 14, "completion_tokens": 3, "prompt_tokens_details": {"cached_tokens": 4}},
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "t1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"pattern": "MAX_BATCH ="}'},
                        }
                    ],
                }
            }
        ],
    },
    {
        "model": "j-2",
        "usage": {"prompt_tokens": 20, "completion_tokens": 5},
        "choices": [{"message": {"content": '{"verdict": "holds"}'}}],
    },
]


@pytest.fixture
def server():
    state = {"replies": [], "seen": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            state["seen"].append((self.path, dict(self.headers), body))
            reply = state["replies"].pop(0)
            data = (reply if isinstance(reply, str) else json.dumps(reply)).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}"
    yield state
    srv.shutdown()


def cfg(server, wire):
    return JudgeModel.load(
        {"name": "j", "version": "1", "wire": wire, "url": server["url"], "key_env": "LIANGJU_TEST_KEY"}
    )


@pytest.mark.parametrize(
    ("wire", "replies", "path"), [("anthropic", ANTHROPIC, "/v1/messages"), ("openai", OPENAI, "/chat/completions")]
)
def test_tool_round_trip_on_both_wires(server, monkeypatch, wire, replies, path):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "sk-test")
    server["replies"] = list(replies)
    text, turns = with_tools(HttpClient(cfg(server, wire)), "系统提示", "核对这条", Toolbox(CANARY / "snapshot"), 4)
    assert text == '{"verdict": "holds"}' and len(turns) == 2
    assert turns[0].calls == [ToolCall("t1", "search", {"pattern": "MAX_BATCH ="})]
    assert turns[0].usage == {"input": 10, "cached_input": 4, "output": 3} and turns[0].model.startswith("j-")
    (p1, h1, first), (p2, _, second) = server["seen"]
    assert p1 == p2 == path and len(first["tools"]) == len(TOOLS) and first["temperature"] == 0.0
    sent = json.dumps(second, ensure_ascii=False)
    assert "relay/config.py:3:MAX_BATCH = 16" in sent and "核对这条" in sent  # 工具的结果回给了模型
    low = {k.lower(): v for k, v in h1.items()}
    key = low.get("x-api-key") or low.get("authorization", "")
    assert "sk-test" in key and "sk-test" not in json.dumps(first)
    if wire == "anthropic":
        assert first["system"] == "系统提示" and second["messages"][-1]["content"][0]["type"] == "tool_result"
    else:
        assert first["messages"][0] == {"role": "system", "content": "系统提示"}
        assert second["messages"][-1]["role"] == "tool" and second["messages"][-2]["tool_calls"][0]["id"] == "t1"


def test_bad_endpoint_answers_are_model_errors(server, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "sk-test")
    for wire, reply in (("openai", {"choices": []}), ("openai", "不是 JSON"), ("anthropic", "[1]")):
        server["replies"] = [reply]
        with pytest.raises(ModelError):
            HttpClient(cfg(server, wire)).chat("s", [{"role": "user", "text": "u"}])
    dead = JudgeModel.load(
        {"name": "j", "version": "1", "wire": "openai", "url": "http://127.0.0.1:1", "key_env": "LIANGJU_TEST_KEY"}
    )
    with pytest.raises(ModelError):
        HttpClient(dead, timeout=2).chat("s", [{"role": "user", "text": "u"}])


def test_registration_and_key(server, monkeypatch):
    monkeypatch.delenv("LIANGJU_TEST_KEY", raising=False)
    with pytest.raises(Refused):
        HttpClient(cfg(server, "openai"))  # 没有密钥：不启动
    with pytest.raises(Refused):
        JudgeModel.load({"name": "j", "version": "1", "wire": "别的", "url": "u", "key_env": "K"})
    with pytest.raises(Refused):
        JudgeModel.load({"name": "j", "wire": "openai", "url": "u", "key_env": "K"})
