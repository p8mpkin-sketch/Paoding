"""授权编译：能力按风险注入（3.6.4 的 2 的编译部分）。纯函数，不需要 Docker。"""

import pytest

from paoding_executor.compile import ScopeError, compile_spec

ENV = {"base": "img", "baseline_ref": "img@1"}
SCOPE = [
    {"resource": "net", "pattern": "t0:80", "actions": ["*"], "risk": "r0"},
    {"resource": "net", "pattern": "t1:22", "actions": ["*"], "risk": "r1"},
    {"resource": "net", "pattern": "t2:9000", "actions": ["*"], "risk": "r2"},
]


def test_ceiling_filters():
    assert compile_spec("s", SCOPE, ENV, "r0", False, "/w").egress_allow == ("t0:80",)
    assert compile_spec("s", SCOPE, ENV, "r1", False, "/w").egress_allow == ("t0:80", "t1:22")


def test_r2_needs_approval():
    """未经批准的 r2 Intent：即使被错误地调度，容器里也没有对应通路。"""
    assert "t2:9000" not in compile_spec("s", SCOPE, ENV, "r2", False, "/w").egress_allow
    assert "t2:9000" in compile_spec("s", SCOPE, ENV, "r2", True, "/w").egress_allow


def test_deterministic():
    a = compile_spec("s", SCOPE, ENV, "r1", False, "/w")
    b = compile_spec("s", list(reversed(SCOPE)), ENV, "r1", False, "/w")
    assert a == b


def test_actions_decide_what_opens():
    """P0-4：只有 actions 含 connect（或 *）的规则进 egress_allow；规则连同动作原样交给闸门。"""
    scope = [
        {"resource": "net", "pattern": "t0:80", "actions": ["connect"], "risk": "r0"},
        {"resource": "net", "pattern": "t0:81", "actions": ["read"], "risk": "r0"},
        {"resource": "net", "pattern": "t0:82", "actions": [], "risk": "r0"},
        {"resource": "net", "pattern": "t0:83", "actions": ["read"], "risk": "r0"},
        {"resource": "net", "pattern": "t0:83", "actions": ["connect"], "risk": "r1"},
    ]
    r0 = compile_spec("s", scope, ENV, "r0", False, "/w")
    assert r0.egress_allow == ("t0:80",)
    assert r0.egress_rules == (("t0:80", ("connect",)), ("t0:81", ("read",)), ("t0:82", ()), ("t0:83", ("read",)))
    r1 = compile_spec("s", scope, ENV, "r1", False, "/w")
    assert r1.egress_allow == ("t0:80", "t0:83") and dict(r1.egress_rules)["t0:83"] == ("connect", "read")


@pytest.mark.parametrize("pattern", ["t0", "t0:", ":80", "t0:http", "t0:0", "t0:70000", ""])
def test_net_pattern_needs_a_port(pattern):
    """出站放行到端口为止：没写端口的 net 规则不默认成"整台主机"，直接拒绝（异议报告 006 第 1 项）。"""
    with pytest.raises(ScopeError):
        compile_spec(
            "s", [{"resource": "net", "pattern": pattern, "actions": ["connect"], "risk": "r0"}], ENV, "r0", False, "/w"
        )


def test_unknown_resource_kind():
    with pytest.raises(ScopeError):
        compile_spec(
            "s", [{"resource": "mystery", "pattern": "x", "actions": [], "risk": "r0"}], ENV, "r0", False, "/w"
        )


def test_workspace_no_egress():
    spec = compile_spec(
        "s", [{"resource": "workspace", "pattern": "*", "actions": [], "risk": "r0"}], ENV, "r0", False, "/w"
    )
    assert spec.egress_allow == ()


def test_resource_kinds_single_source():
    """评审方 #14 必修 1：执行层的资源种类与 graph 登记表同一张；external 不各持一份。"""
    from paoding_executor.compile import RESOURCE_KINDS
    from paoding_graph.contract import RESOURCE_EXTERNAL

    assert set(RESOURCE_KINDS) == set(RESOURCE_EXTERNAL)
    assert all(k.external == RESOURCE_EXTERNAL[name] for name, k in RESOURCE_KINDS.items())
    assert RESOURCE_EXTERNAL["net"] is True and RESOURCE_EXTERNAL["workspace"] is False


def test_owner_alive():
    import os
    import socket

    from paoding_executor.runtime import owner_alive, owner_id

    assert owner_alive(owner_id()) is True
    assert owner_alive(f"{socket.gethostname()}:{os.getpid()}:0") is False  # pid 复用
    assert owner_alive(f"{socket.gethostname()}:999999:1") is False
    assert owner_alive("other-host:1:1") is None and owner_alive("") is None


# ---------- macOS 兼容（已在真实环境验证的三项补丁之二） ----------


def test_owner_alive_without_proc_never_says_dead(monkeypatch):
    """macOS 没有 /proc：取不到启动时刻时不能把活着的属主判成已死，否则孤儿清扫误杀在用的沙箱。"""
    import os
    import socket

    from paoding_executor import runtime

    monkeypatch.setattr(runtime, "_has_proc", lambda: False)
    host = socket.gethostname()
    for owner in (runtime.owner_id(), f"{host}:{os.getpid()}:None", f"{host}:{os.getpid()}:?", f"{host}:999999:1"):
        assert runtime.owner_alive(owner) is None, owner


def test_sweep_spares_everything_without_proc(monkeypatch):
    """同上，落到清扫：没有 /proc 时属主一律“不由本机判断”，一个都不清。"""
    from paoding_executor import runtime

    monkeypatch.setattr(runtime, "_has_proc", lambda: False)
    calls = []

    class P:
        stdout = b"pd-x-1 myhost:1:None\npd-y-2 myhost:2:?\n"

    monkeypatch.setattr(runtime.socket, "gethostname", lambda: "myhost")
    monkeypatch.setattr(runtime, "_docker", lambda *a, **k: calls.append(a) or P())
    assert runtime.sweep_orphans() == []
    assert not [c for c in calls if c[0] in ("rm", "network") and c[1] in ("-f", "rm", "disconnect")]


def test_bind_args_use_v_and_strip_private_on_macos(monkeypatch, tmp_path):
    """macOS 补丁之一：绑定挂载用 -v；Docker Desktop 不认解析出来的 /private/var、/private/tmp 前缀，去掉。"""
    import pytest

    from paoding_executor import runtime

    assert runtime.bind_args(tmp_path, "/workspace") == ["-v", f"{tmp_path}:/workspace"]
    assert runtime.bind_args(tmp_path, "/s", readonly=True) == ["-v", f"{tmp_path}:/s:ro"]
    assert runtime.host_path("/private/var/folders/ab/x") == "/private/var/folders/ab/x"  # 非 macOS 原样
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    assert runtime.host_path("/private/var/folders/ab/x") == "/var/folders/ab/x"
    assert runtime.host_path("/private/tmp/w") == "/tmp/w"
    assert runtime.host_path("/Users/cz/w") == "/Users/cz/w"
    with pytest.raises(FileNotFoundError):  # -v 会悄悄建空目录：先查存在
        runtime.bind_args(tmp_path / "missing", "/workspace")
    with pytest.raises(ValueError):
        runtime.bind_args("/a:b", "/workspace")


def test_only_compiles_the_validated_touches():
    """v1.5 增量 11：给了 touches 的下标就只编译这些规则；集合已在 add_intent 校验过，这里不另查。"""
    assert compile_spec("s", SCOPE, ENV, "r1", False, "/w", only=frozenset({0})).egress_allow == ("t0:80",)
    assert compile_spec("s", SCOPE, ENV, "r1", False, "/w", only=frozenset({1})).egress_allow == ("t1:22",)
    assert compile_spec("s", SCOPE, ENV, "r1", False, "/w", only=frozenset()).egress_allow == ()
    # 风险上限与 r2 批准仍照旧生效：only 只会收窄，不会放宽
    assert compile_spec("s", SCOPE, ENV, "r1", False, "/w", only=frozenset({2})).egress_allow == ()
    assert compile_spec("s", SCOPE, ENV, "r2", False, "/w", only=frozenset({2})).egress_allow == ()
    assert compile_spec("s", SCOPE, ENV, "r1", False, "/w", only=None) == compile_spec(
        "s", SCOPE, ENV, "r1", False, "/w"
    )
