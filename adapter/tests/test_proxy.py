"""端点代理（D4–D6 假 CLI 版）。验收：3.4.5 的 4（预算硬顶/令牌作废）、3.5.5 的 3、4（代理侧计量与对账）。

全部走本机假上游：不需要真密钥、真模型。
"""

import http.client
import json

import pytest
from adapter_rig import PRICES, graph, lease_bootstrap, open_problem, upstream  # noqa: F401  fixture

from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig, ledger_diff

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
    c.request(
        "POST",
        "/v1/messages",
        body=json.dumps({"model": "claude-sonnet-5-5", "max_tokens": 10, "stream": stream, "messages": []}),
        headers=hdr,
    )
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
    assert call(proxy, "t")[0] == 200  # 5
    assert call(proxy, "t")[0] == 200  # 10，越过预留（单请求事后计量，至多超一个请求）
    st, body = call(proxy, "t")
    assert st == 429 and json.loads(body)["error"]["type"] == "task_reserve_exhausted"
    assert len(upstream.seen) == 2


def test_problem_and_global_caps(graph, upstream):
    open_problem(graph)
    lid = lease_bootstrap(graph)
    pt = PriceTable.load(PRICES)
    p = EndpointProxy(
        ProxyConfig(upstream.url, REAL_KEY, "tok-adapter", global_cap_usd_milli=10**9, problem_caps={"p1": 4}),
        pt,
        graph,
    )
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


# ---------- P1-1：重启后累计花费从账本投影（/budget）恢复 ----------


def _restart(graph, upstream, **cfg):
    """旧代理进程没了：新起一个，只凭图服务的账本恢复。"""
    p = EndpointProxy(
        ProxyConfig(upstream.url, REAL_KEY, "tok-adapter", **cfg), PriceTable.load(PRICES), graph, reader=graph
    )
    p.addr = p.serve()
    return p


def test_restart_restores_spend_from_ledger(proxy, graph, upstream):
    open_problem(graph, "p2")
    lid1, lid2 = lease_bootstrap(graph), lease_bootstrap(graph, "p2")
    proxy.register_task("t1", lid1, "p1", 1000)
    proxy.register_task("t2", lid2, "p2", 1000)
    for tok in ("t1", "t1", "t2"):
        assert call(proxy, tok)[0] == 200  # 每个请求 5 毫美元
    assert (proxy.global_spent, proxy.problem_spent) == (15, {"p1": 10, "p2": 5})
    proxy.close()

    cold = EndpointProxy(ProxyConfig(upstream.url, REAL_KEY, "tok-adapter"), PriceTable.load(PRICES), graph)
    assert (cold.global_spent, cold.problem_spent) == (0, {})  # 修复前的行为：不给账本就从零起
    p2 = _restart(graph, upstream)
    try:
        assert (p2.global_spent, p2.problem_spent) == (15, {"p1": 10, "p2": 5})
        assert p2.global_spent == sum(graph.budget(pid)["spent"]["usd_milli"] for pid in ("p1", "p2"))
        assert ledger_diff(p2, graph.state) == []  # 恢复后的基线与账本对得上
        p2.register_task("t3", lid1, "p1", 1000)
        assert call(p2, "t3")[0] == 200  # 重启后的新花费接着累计
        assert (p2.global_spent, p2.problem_spent["p1"]) == (20, 15)
        assert ledger_diff(p2, graph.state) == []
    finally:
        p2.close()


def test_global_cap_still_holds_after_restart(proxy, graph, upstream):
    """审计 P1-1：全局硬顶不因进程重启失效。"""
    lid = lease_bootstrap(graph)
    proxy.register_task("t", lid, "p1", 1000)
    assert call(proxy, "t")[0] == 200 and call(proxy, "t")[0] == 200  # 账本里已有 10
    proxy.close()
    seen = len(upstream.seen)
    p2 = _restart(graph, upstream, global_cap_usd_milli=10)
    try:
        p2.register_task("t2", lid, "p1", 1000)
        st, body = call(p2, "t2")
        assert st == 429 and json.loads(body)["error"]["type"] == "global_cap_exhausted"
        assert len(upstream.seen) == seen  # 没有转发上游
    finally:
        p2.close()


def test_problem_cap_still_holds_after_restart(proxy, graph, upstream):
    lid = lease_bootstrap(graph)
    proxy.register_task("t", lid, "p1", 1000)
    assert call(proxy, "t")[0] == 200
    proxy.close()
    p2 = _restart(graph, upstream, problem_caps={"p1": 5})
    try:
        p2.register_task("t2", lid, "p1", 1000)
        st, body = call(p2, "t2")
        assert st == 429 and json.loads(body)["error"]["type"] == "problem_budget_exhausted"
    finally:
        p2.close()


def test_restore_counts_closed_problems_and_survives_log_replay(proxy, graph, upstream, tmp_path):
    """图服务也重启（状态由日志重放得到）、题已关：花掉的钱仍计入全局。"""
    from adapter_rig import CFG

    from paoding_graph.contract import GraphService

    lid = lease_bootstrap(graph)
    proxy.register_task("t", lid, "p1", 1000)
    assert call(proxy, "t")[0] == 200
    assert graph.submit("tok-human", "p1", "close", [{"op": "close_problem", "body": {}}])["ok"]
    g2 = GraphService(tmp_path / "g.sqlite", CFG, graph.tokens)
    assert g2.state["problems"]["p1"]["closed"]
    p2 = EndpointProxy(ProxyConfig(upstream.url, REAL_KEY, "tok-adapter"), PriceTable.load(PRICES), g2, reader=g2)
    assert p2.global_spent == 5 and p2.restored == {"seq": g2.head(), "global": 5, "problems": {"p1": 5}}
