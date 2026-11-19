"""按任务选模型档案（宪章 03 §3.2、地图 Q14、AC6.1）：会话开起时按任务的 prefs.model 解析一次，
否则按设置层的角色路由；CLI 拿到档案的模型 id，端点代理按档案的上游与密钥槽转发。"""

from types import SimpleNamespace

from adapter_rig import PRICES, graph, lease_bootstrap, open_problem  # noqa: F401  fixture
from test_proxy import call

from paoding_adapter import backend as be
from paoding_adapter.fakeupstream import FakeUpstream
from paoding_adapter.keyring import KeyRing
from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig
from paoding_adapter.session import AdapterConfig, SessionRunner

PROFILES = {
    "default": {"name": "default", "model": "", "endpoint": "", "key_slot": "default"},
    "light": {"name": "light", "model": "light-1", "endpoint": "http://light.example", "key_slot": "light"},
}
ROUTES = {"bootstrap": "default", "reason": "default", "explore": "default"}


def resolve(role, want):
    if role not in ROUTES:
        raise KeyError(role)
    name = want or ROUTES[role]
    if name not in PROFILES:
        raise KeyError(name)
    return PROFILES[name]


def model_of(prefs, role="explore", resolver=resolve):
    p = {"prefs": prefs} if prefs is not None else {}
    fake = SimpleNamespace(
        cfg=AdapterConfig(root=None, resolve_model=resolver),  # type: ignore[arg-type]
        reader=SimpleNamespace(state={"problems": {"p1": p}}),
    )
    return SessionRunner._model(fake, "p1", role)  # type: ignore[arg-type]


def test_task_profile_wins_over_role_route():
    assert model_of({"model": "light"})["model"] == "light-1"
    assert model_of(None)["name"] == "default"
    assert model_of({})["name"] == "default"


def test_deleted_profile_falls_back_to_route_and_unknown_role_to_default():
    assert model_of({"model": "gone"})["name"] == "default"
    assert model_of(None, role="recall") == {}
    assert model_of({"model": "light"}, resolver=None) == {}


def test_cli_gets_the_task_model(tmp_path):
    plan = be.LaunchPlan("l_1", tmp_path, tmp_path / "s.md", "u", tmp_path / "m.json", model="light-1")
    argv, _ = be.CliBinding(program=["cli"], model="strong-1").command(plan)
    assert argv[argv.index("--model") + 1] == "light-1"
    argv, _ = be.CliBinding(program=["cli"], model="strong-1").command(
        be.LaunchPlan("l_1", tmp_path, tmp_path / "s.md", "u", tmp_path / "m.json")
    )
    assert argv[argv.index("--model") + 1] == "strong-1"


def test_proxy_forwards_to_the_task_upstream_with_its_key_slot(graph):
    open_problem(graph)
    main, light = FakeUpstream(), FakeUpstream()
    ring = KeyRing({"default": "", "light": ""})
    ring.set("default", "sk-main", source="config")
    ring.set("light", "sk-light", source="config")
    p = EndpointProxy(ProxyConfig(main.url, "", "tok-adapter", keyring=ring), PriceTable.load(PRICES), graph)
    p.addr = p.serve()
    try:
        lid = lease_bootstrap(graph)
        p.register_task("tok-light", lid, "p1", 1000, upstream=light.url, key_slot="light")
        assert call(p, "tok-light")[0] == 200
        assert not main.seen and len(light.seen) == 1
        h = {k.lower(): v for k, v in light.seen[0]["headers"].items()}
        assert h["x-api-key"] == "sk-light"
        p.register_task("tok-main", lid, "p1", 1000)
        assert call(p, "tok-main")[0] == 200
        assert len(main.seen) == 1
    finally:
        p.close()
        main.close()
        light.close()
