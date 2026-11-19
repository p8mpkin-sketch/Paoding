"""钥匙环（宪章 03 §4）：只在内存、不回显、不进日志；代理没有密钥时回 503 key_not_set，不转发。"""

import json
import logging

import pytest
from adapter_rig import PRICES, graph, lease_bootstrap, open_problem, upstream  # noqa: F401  fixture
from test_proxy import call

from paoding_adapter.contract import EndpointProxy, KeyRing, PriceTable, ProxyConfig

CANARY = "sk-canary-0f9e8d7c6b5a49382716"


def test_status_never_returns_key():
    ring = KeyRing({"default": "ANTHROPIC_API_KEY"})
    st = ring.set("default", CANARY)
    assert st["set"] and st["source"] == "page" and st["env"] == "ANTHROPIC_API_KEY"
    assert st["fingerprint"].endswith("…" + CANARY[-4:]) and CANARY not in json.dumps(ring.status())
    assert ring.get("default") == CANARY
    ring.clear("default")
    assert not ring.ready("default") and ring.status() == [ring.slot_status("default")]


def test_fingerprint_salted_per_ring():
    a, b = KeyRing(), KeyRing()
    assert a.fingerprint(CANARY) == a.fingerprint(CANARY) != b.fingerprint(CANARY)


@pytest.mark.parametrize("bad", ["", "   ", "has space", "x" * 4097])
def test_bad_keys_rejected_without_echo(bad):
    with pytest.raises(ValueError) as e:
        KeyRing().set("default", bad)
    assert bad.strip() == "" or bad not in str(e.value)


def test_unknown_source_rejected():
    with pytest.raises(ValueError):
        KeyRing().set("default", CANARY, source="disk")


def test_logs_redacted_message_args_and_traceback(caplog):
    ring = KeyRing()
    ring.set("default", CANARY)
    ring.install_redaction()
    ring.install_redaction()  # 可重复调用
    caplog.set_level(logging.INFO)
    L = logging.getLogger("t.keyring")
    L.info("直接写进消息 " + CANARY)
    L.info("走参数 %s", CANARY)
    try:
        raise RuntimeError(f"上游说 {CANARY} 不对")
    except RuntimeError:
        L.exception("异常栈")
    h = logging.getLogger().handlers
    text = caplog.text + "".join(r.getMessage() for r in caplog.records)
    assert CANARY not in text, h
    assert "<密钥 " in text


def test_proxy_without_key_returns_503(graph, upstream):  # noqa: F811
    open_problem(graph)
    ring = KeyRing({"default": "ANTHROPIC_API_KEY"})
    cfg = ProxyConfig(upstream.url, "", "tok-adapter", keyring=ring)
    p = EndpointProxy(cfg, PriceTable.load(PRICES), graph)
    p.addr = p.serve()
    try:
        lid = lease_bootstrap(graph)
        p.register_task("t", lid, "p1", 1000)
        st, body = call(p, "t")
        assert st == 503 and b"key_not_set" in body and upstream.seen == []
        ring.set("default", CANARY)  # 设置页注入后立即生效
        st, _ = call(p, "t")
        assert st == 200 and {k.lower(): v for k, v in upstream.seen[-1]["headers"].items()}["x-api-key"] == CANARY
        ring.clear("default")  # 清除也立即生效
        assert call(p, "t")[0] == 503
    finally:
        p.close()


def test_legacy_api_key_moves_into_ring(graph, upstream):  # noqa: F811
    cfg = ProxyConfig(upstream.url, CANARY, "tok-adapter")
    p = EndpointProxy(cfg, PriceTable.load(PRICES), graph)
    assert cfg.api_key == "" and p.keyring.get("default") == CANARY
    assert p.keyring.slot_status("default")["source"] == "config"
    assert CANARY not in repr(cfg)
