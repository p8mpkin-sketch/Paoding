"""方案分析的驱动程序在模型容器里跑（docs/design/fenjue/13-kernel.md §3.3）：通用 Python 镜像，程序与两个纯标准库的包
只读挂进去；容器里只有任务令牌，出站只到端点中继。需要本机 Docker 与镜像 python:3.12-slim（CI 里一定有）。

中继的两种通路都真跑一遍：`unix`（Linux 缺省）与 `tcp`（macOS 的 Docker Desktop 缺省，经 host.docker.internal）。
Linux 上 host.docker.internal 指向默认网桥的网关，宿主的本机回环它到不了，所以测试在网关地址上开两个转发口代替
Docker Desktop 的“转到宿主本机回环”，其余（中继另接默认网桥、模型容器只在内部网络上）与 macOS 上一样。"""

from __future__ import annotations

import json
import socket
import subprocess
import threading

import pytest
from adapter_rig import IMAGE, docker_ok
from tunshi_rig import cases, engine_gongfa, fixture_tar, trig  # noqa: F401

from paoding_adapter import backend as be
from paoding_adapter.container import HOST_ALIAS, ContainerLauncher
from paoding_adapter.relay import accept_loop, to_tcp

needs_docker = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")


def leftovers():
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=pd-model-", "--format", "{{.Names}}"], capture_output=True
    )
    return out.stdout.decode().split()


def bridge_gateway() -> str:
    out = subprocess.run(
        ["docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"],
        capture_output=True,
    )
    return out.stdout.decode().strip()


class GatewayForward:
    """在默认网桥的网关地址上开一个口，转到本机回环上的一个端口（代替 Docker Desktop 的 host.docker.internal）。"""

    def __init__(self, port: int):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind((bridge_gateway(), 0))
        self.srv.listen(64)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=accept_loop, args=(self.srv, to_tcp("127.0.0.1", port)), daemon=True).start()

    def close(self) -> None:
        try:
            self.srv.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.srv.close()


def launcher_for(rig, transport: str) -> tuple[ContainerLauncher, list[GatewayForward]]:
    proxy, mcp = rig.proxy.server.server_address[1], rig.endpoint.server.server_address[1]
    fwd = [GatewayForward(proxy), GatewayForward(mcp)] if transport == "tcp" else []
    launcher = ContainerLauncher(
        IMAGE,
        proxy,
        mcp,
        mounts=be.driver_mounts("tunshi"),
        transport=transport,
        host_ports=(fwd[0].port, fwd[1].port) if fwd else None,
    )
    return launcher, fwd


REACH = (
    "import socket,sys\ntry:\n    socket.create_connection(('{h}', {p}), 3).close()\nexcept OSError:\n    sys.exit(7)\n"
)


def inside(name: str, code: str) -> int:
    return subprocess.run(["docker", "exec", name, "python", "-I", "-c", code], capture_output=True).returncode


@needs_docker
@pytest.mark.parametrize("transport", ["unix", "tcp"])
def test_the_driver_runs_inside_the_model_container_to_the_first_confirmation(trig, transport):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    launcher, fwd = launcher_for(rig, transport)
    rig.runner.launcher = launcher
    rig.cfg.drivers = {"tunshi": be.driver_program("tunshi", in_container=True)}
    rig.cfg.extra_env = {**rig.cfg.extra_env, "PD_LIB": be.DRIVER_LIB_IN_CONTAINER}
    try:
        rig.open(
            intake={
                **cases.intake("alpha", "code"),
                "sources": [{"no": 1, "form": "code", "via": "upload", "artifact": "$material"}],
            },
            material=fixture_tar("alpha"),
        )
        lid, rec = rig.session()
        assert rec.release["outcome"] == "done" and rec.exit_codes == [0], rig.stderr(lid)
        d = rig.deliveries()[-1]
        assert d["outcome"] == "partial" and rig.replay.misses == [] and len(rig.replay.calls) == 12
        init = next(e for e in rec.events if e.get("subtype") == "init")
        assert init["cwd"] == "/workspace" and init["driver"] == "tunshi"
        # 容器里解包的材料落在宿主的工作区里，属主是宿主上的同一个用户
        snap = rig.ws(lid) / "materials" / "s1"
        assert (snap / "README.md").read_bytes() == (cases.HERE / "alpha" / "code" / "README.md").read_bytes()
        run = json.loads((rig.ws(lid) / "analysis" / "run.json").read_text(encoding="utf-8"))
        assert run["step"] == "G1"
        # 真实密钥不进容器：请求头里带的是任务令牌，代理换成真实密钥再发上游
        heads = [r["headers"] for r in rig.upstream.seen]
        assert heads and all(h.get("x-api-key") == "sk-fake-upstream" for h in heads)
        assert "sk-fake-upstream" not in rig.stderr(lid)
        assert not [n for n in leftovers() if lid.replace("_", "-") in n]
    finally:
        launcher.close()
        for f in fwd:
            f.close()


@needs_docker
def test_over_tcp_only_the_relay_can_reach_the_host(trig):  # noqa: F811
    """tcp 通路：中继另接默认网桥、认得 host.docker.internal；模型容器仍只在内部网络上，宿主与网关都到不了。"""
    rig = trig(cases.recording("alpha", "code"))
    launcher, fwd = launcher_for(rig, "tcp")
    try:
        n = launcher._ensure("l_77")
        subprocess.run(
            ["docker", "run", "-d", "--name", n["model"], "--network", n["net"], IMAGE, "sleep", "60"],
            check=True,
            capture_output=True,
        )
        relay_nets = json.loads(
            subprocess.run(
                ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", n["relay"]], capture_output=True
            ).stdout
        )
        assert sorted(relay_nets) == sorted(["bridge", n["net"]])
        gw = bridge_gateway()
        for port in (fwd[0].port, fwd[1].port):
            for h in (HOST_ALIAS, gw):
                assert inside(n["model"], REACH.format(h=h, p=port)) == 7, (h, port)
        # 中继的两个口照常转到端点：模型容器经别名连得到
        assert inside(n["model"], REACH.format(h="pd-endpoints", p=8082)) == 0
    finally:
        launcher.close()
        for f in fwd:
            f.close()
    assert not [x for x in leftovers() if "l-77" in x]


@needs_docker
@pytest.mark.parametrize("transport", ["unix", "tcp"])
def test_an_unreachable_host_side_fails_before_the_session_not_inside_it(tmp_path, transport):
    """上游连不通（macOS 上挂进去的 Unix 套接字就是这样）时，起中继就报错并说明怎么办，而不是会话里被重置。"""
    launcher = ContainerLauncher(IMAGE, 1, 1, transport=transport, host_ports=(1, 1))
    try:
        if transport == "unix":  # 中继连不上挂进来的套接字（Docker Desktop 上是连上就被重置）
            for b in launcher._bridges:
                b.close()
        ws = tmp_path / "l_78" / "workspace"
        ws.mkdir(parents=True)
        with pytest.raises(Exception, match="端点中继连不到宿主上的端点") as e:
            launcher(["true"], {}, ws)
        assert "backend.transport" in str(e.value)
        assert not [x for x in leftovers() if "l-78" in x]
    finally:
        launcher.close()
