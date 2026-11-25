"""容器生命周期：创建、销毁、重置、清理（§3.6.2 的 launch/reset/destroy；kickoff §6 的题目环境容器）。

需要本机 Docker；没有时跳过。目标一律是临时的通用 HTTP 容器。
验收：3.6.4 的 1（越界不通）在重置与重建之后仍成立；3.6.4 的 4（环境容器的启动参数进不了执行容器）；
3.4.5 的 3 的执行层一半（租约结束后沙箱被回收）；孤儿清扫（哮天犬第 3 件事）。
"""

import os
import socket
import subprocess
import uuid

import pytest
from test_docker import ENV, IMAGE, PROBE, FakeGraph, MemBlobs, _docker_ok

from paoding_executor.compile import Limits, compile_spec
from paoding_executor.contract import DockerExecutor, EnvManager, SandboxGone, ScopeError, sweep_orphans
from paoding_executor.runtime import LABEL, OWNER

pytestmark = pytest.mark.skipif(not _docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")
SERVE = ["python", "-m", "http.server", "8080"]


def names(kind="ps"):
    args = (
        ["docker", "ps", "-a", "--format", "{{.Names}}"]
        if kind == "ps"
        else ["docker", "network", "ls", "--format", "{{.Name}}"]
    )
    return set(subprocess.run(args, capture_output=True).stdout.decode().split())


@pytest.fixture
def ex(tmp_path):
    os.chmod(tmp_path, 0o777)
    with DockerExecutor(FakeGraph(), MemBlobs(), "tok-exec") as e:
        yield e


@pytest.fixture
def envs():
    with EnvManager() as m:
        yield m


@pytest.fixture
def target(envs):
    return envs.start(f"pdt-{uuid.uuid4().hex[:8]}", IMAGE, command=SERVE, ready_port=8080)


def spec_for(tmp_path, target=None, sid="lc", **kw):
    scope = [{"resource": "net", "pattern": f"{target}:8080", "actions": ["connect"], "risk": "r0"}] if target else []
    return compile_spec(sid, scope, ENV, "r0", False, str(tmp_path), **kw)


# ---------- 创建与销毁 ----------


def test_launch_creates_container_and_network_destroy_removes_both(ex, tmp_path, target):
    sid = ex.launch(spec_for(tmp_path, target), "l_1")
    assert sid in names() and f"{sid}-net" in names("net")
    [sb] = ex.sandboxes()
    assert sb == {"sid": sid, "lease": "l_1", "spec": "lc", "targets": [target], "mounted": True, "running": True}
    ex.destroy(sid)
    assert sid not in names() and f"{sid}-net" not in names("net") and ex.sandboxes() == []
    assert target in names()  # 目标容器不归沙箱所有，不随之销毁
    ex.destroy(sid)  # 幂等
    with pytest.raises(SandboxGone):
        ex.exec(sid, "true", "p1", "k")


def test_failed_launch_leaves_nothing_behind(ex, tmp_path):
    before = (names(), names("net"))
    spec = compile_spec(
        "bad",
        [{"resource": "net", "pattern": "no-such-container:80", "actions": ["*"], "risk": "r0"}],
        ENV,
        "r0",
        False,
        str(tmp_path),
    )
    with pytest.raises(ScopeError):
        ex.launch(spec, "l_1")
    bad_image = compile_spec(
        "bad2", [], {"base": "no-such-image:none", "baseline_ref": "x"}, "r0", False, str(tmp_path)
    )
    with pytest.raises(subprocess.CalledProcessError):
        ex.launch(bad_image, "l_1")
    assert (names(), names("net")) == before and ex.sandboxes() == []


def test_hardening_flags_and_no_inherited_env(ex, tmp_path, target, monkeypatch):
    """I2、3.6.4 的 4：能力全丢、不可提权、资源有上限；宿主进程的环境变量一个都不带进去。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-appear")
    sid = ex.launch(spec_for(tmp_path, target, limits=Limits(cpu=0.5, mem_mb=128, pids=64, wall_s=300)), "l_1")
    fmt = "{{.HostConfig.CapDrop}}|{{.HostConfig.SecurityOpt}}|{{.HostConfig.Memory}}|{{.HostConfig.PidsLimit}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.Privileged}}"  # noqa: E501
    got = subprocess.run(["docker", "inspect", "--format", fmt, sid], capture_output=True).stdout.decode().strip()
    assert got == f"[ALL]|[no-new-privileges]|{128 * 1024 * 1024}|64|500000000|false"
    env = ex.exec(sid, "env; id -u", "p1", "a").output
    assert "sk-should-never-appear" not in env and "ANTHROPIC" not in env
    mounts = (
        subprocess.run(
            ["docker", "inspect", "--format", "{{range .Mounts}}{{.Destination}} {{end}}", sid], capture_output=True
        )
        .stdout.decode()
        .split()
    )
    assert mounts == ["/workspace"]  # 工作区是唯一的挂载；没有 docker.sock


def test_wall_clock_limit_stops_container(ex, tmp_path):
    sid = ex.launch(spec_for(tmp_path, limits=Limits(wall_s=1)), "l_1")
    subprocess.run(["docker", "wait", sid], capture_output=True, timeout=30)
    assert ex.sandboxes()[0]["running"] is False
    with pytest.raises(SandboxGone):
        ex.exec(sid, "echo late", "p1", "k")
    assert ex.graph.calls == []  # 没有采集，也就没有登记


# ---------- 重置 ----------


def test_reset_keeps_id_and_scope_but_drops_state(ex, tmp_path, target):
    sid = ex.launch(spec_for(tmp_path, target), "l_1")
    ex.exec(sid, "echo x > /tmp/state; echo kept > /workspace/note.txt", "p1", "a")
    cid = subprocess.run(["docker", "inspect", "--format", "{{.Id}}", sid], capture_output=True).stdout
    assert ex.reset(sid) == sid  # 会话手里的沙箱 id 继续有效
    assert subprocess.run(["docker", "inspect", "--format", "{{.Id}}", sid], capture_output=True).stdout != cid
    assert ex.exec(sid, "test -e /tmp/state", "p1", "b").exit_code != 0  # 容器内状态回到 baseline
    assert ex.exec(sid, "cat /workspace/note.txt", "p1", "c").output == "kept\n"  # 工作区是共享挂载，不重置
    assert ex.exec(sid, PROBE.format(h=target, p=8080), "p1", "d").exit_code == 0  # 白名单照旧
    assert ex.exec(sid, PROBE.format(h="1.1.1.1", p=443), "p1", "e").exit_code != 0  # 3.6.4 的 1：越界照旧不通
    assert [s["sid"] for s in ex.sandboxes()] == [sid]
    with pytest.raises(SandboxGone):
        ex.reset("pd-nope")


# ---------- 按租约清理 ----------


def test_destroy_lease_and_reclaim(ex, tmp_path):
    a = ex.launch(spec_for(tmp_path, sid="a"), "l_1")
    aj = ex.launch(spec_for(tmp_path, sid="aj"), "l_1", mount_workspace=False)
    b = ex.launch(spec_for(tmp_path, sid="b"), "l_2")
    c = ex.launch(spec_for(tmp_path, sid="c"), "l_3")
    assert sorted(ex.destroy_lease("l_1")) == sorted([a, aj])
    assert {a, aj}.isdisjoint(names()) and {b, c} <= names()
    ended = {"l_2": 999.0}  # l_2 已结束很久：回收；l_3 在途：不动
    assert ex.reclaim(ended.get) == [b]
    assert b not in names() and c in names() and [s["sid"] for s in ex.sandboxes()] == [c]
    assert ex.destroy_lease("l_none") == []


def test_destroy_by_labels_after_restart(ex, tmp_path, target):
    """进程重启后新实例不认识旧沙箱：仍能按标签把容器、网络拆干净，且不碰不是本层建的容器。"""
    sid = ex.launch(spec_for(tmp_path, target), "l_9")
    fresh = DockerExecutor(FakeGraph(), MemBlobs(), "tok-exec")
    assert fresh.sandboxes() == []
    fresh.destroy(sid)
    assert sid not in names() and f"{sid}-net" not in names("net") and target in names()
    ex._live.clear()
    stranger = f"plain-{uuid.uuid4().hex[:6]}"
    subprocess.run(["docker", "run", "-d", "--name", stranger, IMAGE, "sleep", "60"], check=True, capture_output=True)
    try:
        fresh.destroy(stranger)
        assert stranger in names()
    finally:
        subprocess.run(["docker", "rm", "-f", stranger], capture_output=True)


def test_context_manager_cleans_up(tmp_path):
    os.chmod(tmp_path, 0o777)
    with DockerExecutor(FakeGraph(), MemBlobs(), "tok-exec") as e:
        sids = [e.launch(spec_for(tmp_path, sid=f"cm{i}"), f"l_{i}") for i in range(2)]
        assert set(sids) <= names()
    assert set(sids).isdisjoint(names()) and not {f"{s}-net" for s in sids} & names("net")


def test_sweep_removes_dead_owners_networks_and_envs(tmp_path, target):
    """哮天犬第 3 件事：属主已死的沙箱、它的网络、题目环境容器一并回收；目标容器接在网络上也删得掉。"""
    tag = uuid.uuid4().hex[:6]
    dead_owner = f"{socket.gethostname()}:999999:1"
    sid, net, env = f"pd-dead-{tag}", f"pd-dead-{tag}-net", f"pd-deadenv-{tag}"
    lab = ["--label", f"{LABEL}={sid}", "--label", f"{OWNER}={dead_owner}"]
    subprocess.run(["docker", "network", "create", "--internal", *lab, net], check=True, capture_output=True)
    subprocess.run(
        ["docker", "run", "-d", "--name", sid, *lab, "--network", net, IMAGE, "sleep", "300"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["docker", "network", "connect", net, target], check=True, capture_output=True)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            env,
            "--label",
            f"{LABEL}={env}",
            "--label",
            f"{OWNER}={dead_owner}",
            IMAGE,
            "sleep",
            "300",
        ],
        check=True,
        capture_output=True,
    )
    try:
        swept = sweep_orphans()
        assert {sid, env} <= set(swept) and target not in swept
        assert {sid, env}.isdisjoint(names()) and net not in names("net") and target in names()
        assert sweep_orphans() == [] or {sid, env}.isdisjoint(sweep_orphans())
    finally:
        subprocess.run(["docker", "rm", "-f", sid, env], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)


# ---------- 题目环境容器 ----------


def test_env_start_reset_stop(envs, ex, tmp_path):
    name = f"pde-{uuid.uuid4().hex[:8]}"
    cmd = ["sh", "-c", 'echo "$SEED" > /tmp/seed; echo 0 > /tmp/hits; exec python -m http.server 8080 -d /tmp']
    envs.start(name, IMAGE, env={"SEED": "s3cr3t-seed"}, command=cmd, ready_port=8080)
    assert envs.running(name) and envs.names() == [name]
    with pytest.raises(ValueError):
        envs.start(name, IMAGE, command=SERVE)
    sid = ex.launch(spec_for(tmp_path, name), "l_1")
    fetch = (
        "python -c \"import urllib.request as u;print(u.urlopen('http://%s:8080/%%s').read().decode().strip())\"" % name
    )
    assert ex.exec(sid, fetch % "seed", "p1", "a").output.strip() == "s3cr3t-seed"
    subprocess.run(["docker", "exec", name, "sh", "-c", "echo dirty > /tmp/hits"], check=True)
    assert ex.exec(sid, fetch % "hits", "p1", "b").output.strip() == "dirty"
    # 启动参数只在环境容器里：执行容器的环境、宿主上的工作区里都没有（3.6.4 的 4）
    assert "s3cr3t-seed" not in ex.exec(sid, "env; ls -la /workspace", "p1", "c").output
    ex.destroy(sid)
    cid = subprocess.run(["docker", "inspect", "--format", "{{.Id}}", name], capture_output=True).stdout
    assert envs.reset(name) == name  # 重置 = 删除后按同一参数重建
    assert subprocess.run(["docker", "inspect", "--format", "{{.Id}}", name], capture_output=True).stdout != cid
    sid = ex.launch(spec_for(tmp_path, name, sid="lc2"), "l_2")
    assert ex.exec(sid, fetch % "hits", "p1", "d").output.strip() == "0"  # 状态清零
    assert ex.exec(sid, fetch % "seed", "p1", "e").output.strip() == "s3cr3t-seed"  # 同一参数
    envs.stop(name)  # 沙箱网络还接着它，也删得掉
    assert name not in names() and envs.names() == []
    envs.stop(name)  # 幂等
    # 目标没了：闸门接不通上游，立刻重置连接，取不到任何内容。闸门仍在监听，所以只看 connect 的探测
    # 会以为端口开着（SPEC.md 已知缺口 5）
    gone = ex.exec(sid, fetch % "seed", "p1", "f")
    assert gone.exit_code != 0 and "s3cr3t-seed" not in gone.output


def test_env_not_ready_is_cleaned_up(envs):
    name = f"pde-{uuid.uuid4().hex[:8]}"
    with pytest.raises(RuntimeError, match="未就绪"):
        envs.start(name, IMAGE, command=["sh", "-c", "echo boom; exit 3"], ready_port=8080, ready_timeout_s=5)
    assert name not in names() and envs.names() == []


def test_env_manager_only_stops_its_own(envs):
    stranger = f"plain-{uuid.uuid4().hex[:6]}"
    subprocess.run(["docker", "run", "-d", "--name", stranger, IMAGE, "sleep", "60"], check=True, capture_output=True)
    try:
        envs.stop(stranger)
        assert stranger in names()
    finally:
        subprocess.run(["docker", "rm", "-f", stranger], capture_output=True)
