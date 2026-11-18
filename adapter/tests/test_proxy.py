"""端点代理（D4–D6 假 CLI 版）。验收：3.4.5 的 4（预算硬顶/令牌作废）、3.5.5 的 3、4（代理侧计量与对账）。

全部走本机假上游：不需要真密钥、真模型。
"""
import http.client
import json

import pytest
from adapter_rig import PRICES, graph, lease_bootstrap, open_problem, upstream  # noqa: F401（fixture）

from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig

REAL_KEY = "sk-fake-upstream-key-not-real"


@pytest.fixture
def proxy(graph, upstream):
    open_problem(graph)
    p = EndpointProxy(ProxyConfig(upstream.url, REAL_KEY, "tok-adapter"), PriceTable.load(PRICES), graph)
    host, port = p.serve()
    p.addr = (host, port)
    yield p
    p.close()


def call(p, token, stream=False, auth="x-api-key"):
    c = http.client.HTTPConnection(*p.addr, timeout=10)
    hdr = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    hdr.update({"x-api-key": token} if auth == "x-api-key" else {"authorization": f"Bearer {token}"})
    c.request("POST", "/v1/messages", body=json.dumps({"model": "claude-sonnet-5-5", "max_tokens": 10,
                                                       "stream": stream, "messages": []}), headers=hdr)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def costs(graph):
    return [c for c in graph.state["costs"] if c["source"] == "proxy"]


def test_key_swap_task_token_never_reaches_upstream(proxy, graph, upstream):
    lid = lease_bootstrap(graph)
    proxy.register_task("task-tok-1", lid, "p1", 1000)
    for auth in ("x-api-key", "bearer"):
        st, _ = call(proxy, "task-tok-1", auth=auth)
        assert st == 200
    for s in upstream.seen:
        h = {k.lower(): v for k, v in s["headers"].items()}
        assert h["x-api-key"] == REAL_KEY
        assert "authorization" not in h
        assert "task-tok-1" not in json.dumps(h)


@pytest.mark.parametrize("stream", [False, True])
def test_metering_writes_cost_event(proxy, graph, upstream, stream):
    lid = lease_bootstrap(graph)
    proxy.register_task("t", lid, "p1", 1000)
    st, body = call(proxy, "t", stream=stream)
    assert st == 200 and (b"message_stop" in body if stream else json.loads(body)["usage"])
    [c] = costs(graph)
    # sonnet：1000×2 + 200×10 + 5000×0.10 + 100×2.5 = 4750 微美元 → 4.75 毫美元 → 向上取整 5
    assert c["task_id"] == lid and c["model"] == "claude-sonnet-5-5"
    assert (c["tokens_in"], c["tokens_out"], c["tokens_cached"]) == (1000, 200, 5000)
    assert c["usd_milli"] == 5 and c["price_table"] == PriceTable.load(PRICES).version
    assert proxy.task("t").spent_usd_milli == 5


def test_unknown_model_billed_at_highest_tier():
    pt = PriceTable.load(PRICES)
    u = {"input_tokens": 1_000_000}
    assert pt.usd_milli("no-such-model", u) == max(pt.usd_milli(m, u) for m in pt.models)


def test_reserve_exhausted_429(proxy, graph, upstream):
    lid = lease_bootstrap(graph)
    proxy.register_task("t", lid, "p1", 8)
    assert call(proxy, "t")[0] == 200          # 5
    assert call(proxy, "t")[0] == 200          # 10，越过预留（单请求事后计量，至多超一个请求）
    st, body = call(proxy, "t")
    assert st == 429 and json.loads(body)["error"]["type"] == "task_reserve_exhausted"
    assert len(upstream.seen) == 2


def test_problem_and_global_caps(graph, upstream):
    open_problem(graph)
    lid = lease_bootstrap(graph)
    pt = PriceTable.load(PRICES)
    p = EndpointProxy(ProxyConfig(upstream.url, REAL_KEY, "tok-adapter", global_cap_usd_milli=10**9,
                                  problem_caps={"p1": 4}), pt, graph)
    p.addr = p.serve()
    try:
        p.register_task("t", lid, "p1", 1000)
        assert call(p, "t")[0] == 200
        st, body = call(p, "t")
        assert st == 429 and json.loads(body)["error"]["type"] == "problem_budget_exhausted"
        p.cfg.problem_caps.clear()
        p.cfg.global_cap_usd_milli = 5
        st, body = call(p, "t")
        assert st == 429 and json.loads(body)["error"]["type"] == "global_cap_exhausted"
    finally:
        p.close()


def test_default_global_cap_is_500_usd():
    assert ProxyConfig("u", "k", "t").global_cap_usd_milli == 500_000


def test_revoked_and_unknown_token_401(proxy, graph, upstream):
    lid = lease_bootstrap(graph)
    proxy.register_task("t", lid, "p1", 1000)
    assert call(proxy, "nope")[0] == 401
    proxy.revoke("t")
    st, body = call(proxy, "t")
    assert st == 401 and json.loads(body)["error"]["type"] == "unknown_or_revoked_token"
    assert upstream.seen == []


def test_proxy_ledger_reconciles_with_graph(proxy, graph, upstream):
    """3.5.5 的 4（代理侧）：代理自记的花费与图里 cost 事件之和逐任务相等。"""
    lid = lease_bootstrap(graph)
    proxy.register_task("t", lid, "p1", 1000)
    for i in range(5):
        upstream.usage = {**upstream.usage, "output_tokens": 100 * (i + 1)}
        assert call(proxy, "t", stream=bool(i % 2))[0] == 200
    assert sum(c["usd_milli"] for c in costs(graph)) == proxy.task("t").spent_usd_milli == proxy.global_spent
    assert len({c["seq"] for c in costs(graph)}) == 5
