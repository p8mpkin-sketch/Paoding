"""端点代理计量的方言兼容（真实测试报告 P0-C：macOS + DeepSeek 上全程记 $0.000）。

全部走本机假上游，用 dialect 模拟别家 Anthropic 兼容端点的差异：CRLF 分行的 SSE、不理 accept-encoding 的 gzip、
usage 全在 message_delta、OpenAI/DeepSeek 式字段名、值为 null 的缓存字段、完全不给 usage。
验收：每种情形的预算读数都非零；取不到 usage 时按字节估算并在 cost 事件上标明。
"""

import http.client
import json
import logging

import pytest
from adapter_rig import PRICES, graph, lease_bootstrap, open_problem  # noqa: F401  fixture

from paoding_adapter.fakeupstream import FakeUpstream
from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig, ledger_diff, normalize_usage

DEEPSEEK = "deepseek-chat"
ANTHROPIC_STYLE = {
    "input_tokens": 1000,
    "output_tokens": 200,
    "cache_read_input_tokens": None,
    "cache_creation_input_tokens": None,
}  # 不报缓存的字段给 null
DEEPSEEK_STYLE = {
    "prompt_tokens": 6000,
    "completion_tokens": 200,
    "prompt_cache_hit_tokens": 5000,
    "prompt_cache_miss_tokens": 1000,
}


def _run(graph, usage, dialect, stream, model=DEEPSEEK):
    open_problem(graph)
    up = FakeUpstream(usage, model=model, dialect=dialect)
    p = EndpointProxy(ProxyConfig(up.url, "sk-fake", "tok-adapter"), PriceTable.load(PRICES), graph)
    host, port = p.serve()
    try:
        lid = lease_bootstrap(graph)
        p.register_task("t", lid, "p1", 100_000)
        c = http.client.HTTPConnection(host, port, timeout=10)
        c.request(
            "POST",
            "/v1/messages",
            headers={"x-api-key": "t", "content-type": "application/json", "accept-encoding": "gzip, deflate, br"},
            body=json.dumps(
                {
                    "model": model,
                    "max_tokens": 10,
                    "stream": stream,
                    "messages": [{"role": "user", "content": "你好" * 50}],
                }
            ),
        )
        r = c.getresponse()
        data = r.read()
        c.close()
        assert r.status == 200
        return p, up, lid, data, r
    finally:
        p.close()
        up.close()


def proxy_costs(graph):
    return [c for c in graph.state["costs"] if c["source"] == "proxy"]


CASES = {
    "deepseek_crlf_delta": (ANTHROPIC_STYLE, {"crlf": True, "usage_at": "delta"}, (1000, 200, 0)),
    "gzip_ignoring_accept_encoding": (ANTHROPIC_STYLE, {"gzip": True}, (1000, 200, 0)),
    "deepseek_field_names": (DEEPSEEK_STYLE, {}, (1000, 200, 5000)),
    "deepseek_names_crlf_gzip": (DEEPSEEK_STYLE, {"crlf": True, "gzip": True, "usage_at": "delta"}, (1000, 200, 5000)),
}


@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("case", sorted(CASES))
def test_nonzero_reading_across_dialects(graph, case, stream):
    usage, dialect, (t_in, t_out, t_cached) = CASES[case]
    p, up, lid, data, _ = _run(graph, usage, dialect, stream)
    [c] = proxy_costs(graph)
    norm = {"input_tokens": t_in, "output_tokens": t_out, **({"cache_read_input_tokens": t_cached} if t_cached else {})}
    assert c["usd_milli"] > 0 and c["usd_milli"] == PriceTable.load(PRICES).usd_milli(DEEPSEEK, norm)
    assert (c["tokens_in"], c["tokens_out"], c["tokens_cached"]) == (t_in, t_out, t_cached)
    assert c["model"] == DEEPSEEK and c["price_table"] == PriceTable.load(PRICES).version
    assert p.task("t").spent_usd_milli == c["usd_milli"] and ledger_diff(p, graph.state) == []
    assert up.seen[0]["headers"].get("accept-encoding") == "identity"  # 向上游只要未压缩的
    if dialect.get("gzip"):  # 转发的字节不动：客户端照样拿到 gzip
        import gzip

        assert gzip.decompress(data)


@pytest.mark.parametrize("stream", [True, False])
def test_no_usage_falls_back_to_estimate(graph, stream, caplog):
    caplog.set_level(logging.INFO, logger="adapter")
    p, up, lid, data, _ = _run(graph, ANTHROPIC_STYLE, {"no_usage": True}, stream)
    [c] = proxy_costs(graph)
    assert c["usd_milli"] > 0 and c["tokens_in"] > 0 and c["tokens_out"] > 0
    assert c["price_table"] == PriceTable.load(PRICES).version + "+estimated"
    assert any("没有可用的 usage" in r.getMessage() for r in caplog.records)


def test_raw_usage_is_logged(graph, caplog):
    caplog.set_level(logging.INFO, logger="adapter")
    _run(graph, DEEPSEEK_STYLE, {"crlf": True}, True)
    [line] = [r.getMessage() for r in caplog.records if "上游 usage=" in r.getMessage()]
    assert "prompt_cache_hit_tokens" in line and DEEPSEEK in line


def test_normalize_usage_shapes():
    assert normalize_usage(
        {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 6}
    ) == {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 6}
    assert normalize_usage(
        {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 7}}
    ) == {"input_tokens": 3, "output_tokens": 2, "cache_read_input_tokens": 7}
    assert normalize_usage({"prompt_tokens": 10, "completion_tokens": 2}) == {"input_tokens": 10, "output_tokens": 2}
    assert normalize_usage({"input_tokens": None, "output_tokens": True, "x": "y"}) == {}
    assert normalize_usage({}) == {}


def test_deepseek_prices():
    """cz 2026-11-18 给的 DeepSeek 官方标价：deepseek-chat 不再按最贵档计。"""
    pt = PriceTable.load(PRICES)
    assert "deepseek@2026-11" in pt.version
    u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert pt.usd_milli("deepseek-chat", u) == 270 + 1100 + 70
    assert pt.usd_milli("deepseek-reasoner", u) == 550 + 2190 + 140
