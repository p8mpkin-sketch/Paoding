"""授权编译：能力按风险注入（3.6.4 的 2 的编译部分）。纯函数，不需要 Docker。"""
import pytest

from paoding_executor.compile import ScopeError, compile_spec

ENV = {"base": "img", "baseline_ref": "img@1"}
SCOPE = [{"resource": "net", "pattern": "t0:80", "actions": ["*"], "risk": "r0"},
         {"resource": "net", "pattern": "t1:22", "actions": ["*"], "risk": "r1"},
         {"resource": "net", "pattern": "t2:9000", "actions": ["*"], "risk": "r2"}]


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


def test_unknown_resource_kind():
    with pytest.raises(ScopeError):
        compile_spec("s", [{"resource": "mystery", "pattern": "x", "actions": [], "risk": "r0"}], ENV, "r0", False, "/w")


def test_workspace_no_egress():
    spec = compile_spec("s", [{"resource": "workspace", "pattern": "*", "actions": [], "risk": "r0"}], ENV, "r0", False, "/w")
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
    assert owner_alive(f"{socket.gethostname()}:{os.getpid()}:0") is False      # pid 复用
    assert owner_alive(f"{socket.gethostname()}:999999:1") is False
    assert owner_alive("other-host:1:1") is None and owner_alive("") is None
