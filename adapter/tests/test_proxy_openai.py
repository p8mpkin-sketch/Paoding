"""OpenAI 兼容上游（前端 v5 裁决“OpenAI 兼容=做”）：代理把 Messages 改写成 Chat Completions 再改回来，计量照旧。

全部走本机假上游。验收：命令行收到的是 Messages 形状（流式与非流式、文字与工具调用）；上游收到的是 Chat Completions、
Bearer 密钥、没有 Anthropic 的头；用量按 OpenAI 的口径入账；count_tokens 本地估不出站；其他路径拒绝。
"""

import http.client
import json

import pytest
from adapter_rig import PRICES, graph, lease_bootstrap, open_problem  # noqa: F401  fixture

from paoding_adapter.fakeupstream import FakeUpstream
from paoding_adapter.openai_compat import StreamTranslator, from_openai_response, to_openai_request
from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig, ledger_diff

MODEL = "model-a"
OPENAI_USAGE = {"prompt_tokens": 1200, "completion_tokens": 300, "prompt_tokens_details": {"cached_tokens": 200}}


def _call(graph, body, dialect=None, path="/v1/messages", method="POST", up_path="/v1"):
    open_problem(graph)
    up = FakeUpstream(OPENAI_USAGE, model=MODEL, dialect=dialect)
    p = EndpointProxy(ProxyConfig("http://unused.invalid", "sk-fake", "tok-adapter"), PriceTable.load(PRICES), graph)
    host, port = p.serve()
    try:
        lid = lease_bootstrap(graph)
        p.register_task("t", lid, "p1", 100_000, upstream=up.url + up_path, fmt="openai")
        c = http.client.HTTPConnection(host, port, timeout=10)
        c.request(
            method,
            path,
            headers={"x-api-key": "t", "content-type": "application/json", "anthropic-version": "2023-06-01"},
            body=json.dumps(body) if body is not None else None,
        )
        r = c.getresponse()
        data = r.read()
        c.close()
        return p, up, r, data
    finally:
        p.close()
        up.close()


def _sse_events(data: bytes):
    out = []
    for ev in data.decode().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in ev.split("\n") if ": " in line)
        if "data" in lines:
            out.append((lines.get("event"), json.loads(lines["data"])))
    return out


BODY = {
    "model": MODEL,
    "max_tokens": 64,
    "system": [{"type": "text", "text": "你是助手"}],
    "messages": [{"role": "user", "content": "你好"}],
    "tools": [
        {
            "name": "Bash",
            "description": "跑命令",
            "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}},
        }
    ],
}


@pytest.mark.parametrize("stream", [False, True])
def test_upstream_sees_chat_completions_with_bearer(graph, stream):
    p, up, r, _ = _call(graph, {**BODY, "stream": stream})
    assert r.status == 200
    [seen] = up.seen
    assert seen["path"] == "/v1/chat/completions"
    h = {k.lower(): v for k, v in seen["headers"].items()}
    assert h["authorization"] == "Bearer sk-fake" and "x-api-key" not in h and "anthropic-version" not in h
    b = seen["body"]
    assert b["messages"][0] == {"role": "system", "content": "你是助手"}
    assert b["tools"][0]["function"]["name"] == "Bash" and b["max_tokens"] == 64
    if stream:
        assert b["stream_options"] == {"include_usage": True}


@pytest.mark.parametrize("stream", [False, True])
def test_metered_in_openai_terms(graph, stream):
    p, up, r, _ = _call(graph, {**BODY, "stream": stream})
    [c] = [c for c in graph.state["costs"] if c["source"] == "proxy"]
    norm = {"input_tokens": 1000, "output_tokens": 300, "cache_read_input_tokens": 200}
    assert (c["tokens_in"], c["tokens_out"], c["tokens_cached"]) == (1000, 300, 200)
    assert c["usd_milli"] == PriceTable.load(PRICES).usd_milli(MODEL, norm) > 0
    assert ledger_diff(p, graph.state) == []


def test_non_stream_reply_is_a_message_with_tool_use(graph):
    _, _, r, data = _call(graph, BODY, dialect={"openai_tool": True})
    m = json.loads(data)
    assert r.getheader("content-type") == "application/json"
    assert m["type"] == "message" and m["role"] == "assistant" and m["stop_reason"] == "tool_use"
    assert m["content"][0] == {"type": "text", "text": "hi"}
    assert m["content"][1] == {"type": "tool_use", "id": "call_1", "name": "Bash", "input": {"command": "ls"}}
    assert m["usage"] == {"input_tokens": 1000, "output_tokens": 300, "cache_read_input_tokens": 200}


def test_stream_reply_is_message_events(graph):
    _, _, r, data = _call(graph, {**BODY, "stream": True}, dialect={"openai_tool": True})
    assert r.getheader("content-type") == "text/event-stream"
    evs = _sse_events(data)
    kinds = [e for e, _ in evs]
    assert kinds[0] == "message_start" and kinds[-1] == "message_stop" and kinds[-2] == "message_delta"
    text = "".join(
        d["delta"]["text"] for e, d in evs if e == "content_block_delta" and d["delta"]["type"] == "text_delta"
    )
    assert text == "hi"
    [tool_start] = [d for e, d in evs if e == "content_block_start" and d["content_block"]["type"] == "tool_use"]
    assert tool_start["index"] == 1 and tool_start["content_block"]["name"] == "Bash"
    args = "".join(
        d["delta"]["partial_json"]
        for e, d in evs
        if e == "content_block_delta" and d["delta"]["type"] == "input_json_delta"
    )
    assert json.loads(args) == {"command": "ls"}
    assert kinds.count("content_block_start") == kinds.count("content_block_stop") == 2
    delta = evs[-2][1]
    assert delta["delta"]["stop_reason"] == "tool_use" and delta["usage"]["output_tokens"] == 300


def test_upstream_error_becomes_message_error(graph):
    _, _, r, data = _call(graph, BODY, dialect={"error": 404})
    assert r.status == 404
    assert json.loads(data) == {"type": "error", "error": {"type": "not_found_error", "message": "bad model"}}
    assert [c for c in graph.state["costs"] if c["source"] == "proxy"] == []


def test_count_tokens_is_local_and_other_paths_refused(graph):
    p, up, r, data = _call(graph, BODY, path="/v1/messages/count_tokens")
    assert r.status == 200 and json.loads(data)["input_tokens"] > 0 and up.seen == []
    _, up2, r2, _ = _call(graph, None, path="/v1/models", method="GET")
    assert r2.status == 404 and up2.seen == []


def test_register_rejects_unknown_format(graph):
    p = EndpointProxy(ProxyConfig("http://x.invalid", "", "tok"), PriceTable.load(PRICES), graph)
    with pytest.raises(ValueError):
        p.register_task("t", "l1", "p1", 10, fmt="gemini")


# ---------- 纯转换 ----------


def test_request_translation_covers_tool_results_and_images():
    body = {
        "model": "x",
        "max_tokens": 5,
        "stop_sequences": ["END"],
        "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        "tools": [
            {"name": "t", "input_schema": {"type": "object"}},
            {"type": "web_search_20250305", "name": "web_search"},
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "…"},
                    {"type": "tool_use", "id": "u1", "name": "t", "input": {"a": 1}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "u1",
                        "content": [{"type": "text", "text": "ok"}],
                        "is_error": True,
                    },
                    {"type": "text", "text": "继续"},
                ],
            },
        ],
    }
    o = to_openai_request(body, model="m2")
    assert (
        o["model"] == "m2"
        and o["stop"] == ["END"]
        and o["tool_choice"] == "required"
        and o["parallel_tool_calls"] is False
    )
    assert [t["function"]["name"] for t in o["tools"]] == ["t"]  # 服务端工具转不过去
    u0, a1, t2, u3 = o["messages"]
    assert u0["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}
    assert a1 == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "u1", "type": "function", "function": {"name": "t", "arguments": '{"a": 1}'}}],
    }
    assert t2 == {"role": "tool", "tool_call_id": "u1", "content": "[error] ok"}
    assert u3 == {"role": "user", "content": "继续"}


def test_response_translation_edge_cases():
    m = from_openai_response({"choices": [{"message": {"content": None}, "finish_reason": "length"}]}, model="m")
    assert m["content"] == [{"type": "text", "text": ""}] and m["stop_reason"] == "max_tokens" and m["model"] == "m"
    bad = from_openai_response(
        {"choices": [{"message": {"tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "not json"}}]}}]}
    )
    assert bad["content"][0]["input"] == {"_raw": "not json"}


def test_stream_without_done_still_closes():
    tr = StreamTranslator("m")
    out = tr.feed(b'data: {"choices":[{"delta":{"content":"a"}}]}\r\n\r\ndata: {"choices":[{"delta":{"content":"b"}}]}')
    out += tr.finish()
    evs = _sse_events(out)
    assert [e for e, _ in evs] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert tr.finish() == b""  # 收过尾不再吐
