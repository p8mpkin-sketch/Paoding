"""方案分析的驱动程序在模型容器里跑（docs/design/fenjue/13-kernel.md §3.3）：通用 Python 镜像，程序与两个纯标准库的包
只读挂进去；容器里只有任务令牌，出站只到端点中继。需要本机 Docker 与镜像 python:3.12-slim（CI 里一定有）。"""

from __future__ import annotations

import json
import subprocess

import pytest
from adapter_rig import IMAGE, docker_ok
from tunshi_rig import cases, engine_gongfa, fixture_tar, trig  # noqa: F401

from paoding_adapter import backend as be
from paoding_adapter.container import ContainerLauncher

needs_docker = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")


def leftovers():
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=pd-model-", "--format", "{{.Names}}"], capture_output=True
    )
    return out.stdout.decode().split()


@needs_docker
def test_the_driver_runs_inside_the_model_container_to_the_first_confirmation(trig):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    launcher = ContainerLauncher(
        IMAGE,
        rig.proxy.server.server_address[1],
        rig.endpoint.server.server_address[1],
        mounts=be.driver_mounts("tunshi"),
    )
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
