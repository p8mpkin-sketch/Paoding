"""失败的沙箱启动不再留下容器与网络：善后逐条接超时、待确认表延后复查（settle）、按租约标签兜底回收（reclaim）。

cz 2026-11-26 真系统：一次启动失败留下一个“已创建、从未启动”的容器，带租约标签和本实例的属主标签，在册表里
没有，实例活着，所以按在册表的回收与按属主死活的孤儿清扫都看不到它，两小时后人工删掉。两条路都会留下它：
  甲：建容器的请求客户端超时了，清理跑完之后容器服务才把容器建出来（cz 那一次：没有同时留下网络）；
  乙：容器服务整个无响应，清理的第一条查询也超时，整个清理被打断（真 Docker 上复现出的那一条）。

不需要 Docker：容器命令行换成 fake_docker.py，执行层调子进程的超时按比例缩短，别的原样。
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from paoding_executor import runtime
from paoding_executor.compile import ExecSpec, Limits
from paoding_executor.runtime import DOOM_KEEP_S, LABEL, LEASE, OWNER, ROLE, DockerExecutor, sweep_orphans

FAKE = Path(__file__).with_name("fake_docker.py")
SHORT = {120: 2.0, 30.0: 1.0, 10.0: 0.8, 5.0: 0.6}  # 执行层的各档超时 → 测试里等的秒数
T = SHORT[120]


class Daemon:
    """假容器服务的状态目录：定计划、直接放进容器与网络、看还剩什么。"""

    def __init__(self, root: Path):
        self.root = root
        (root / "containers").mkdir(parents=True)
        (root / "networks").mkdir()

    def plan(self, **kw) -> None:
        (self.root / "plan.json").write_text(json.dumps(kw))

    def put(self, name: str, sid: str, owner: str, lease: str | None = "7", role: str = "sandbox") -> None:
        labels = {LABEL: sid, OWNER: owner, ROLE: role, **({LEASE: lease} if lease is not None else {})}
        (self.root / "containers" / f"{name}.json").write_text(json.dumps({"labels": labels, "state": "created"}))

    def put_net(self, name: str, sid: str, owner: str) -> None:
        (self.root / "networks" / f"{name}.json").write_text(json.dumps({"labels": {LABEL: sid, OWNER: owner}}))

    def sandbox(self, sid: str, owner: str, lease: str = "7") -> None:
        """清理被打断时留下的全套：执行容器、一个闸门、两张网络。"""
        self.put(sid, sid, owner, lease)
        self.put(f"{sid}-gate-0", sid, owner, lease, role="gate")
        self.put_net(f"{sid}-net", sid, owner)
        self.put_net(f"{sid}-up-net", sid, owner)

    def containers(self) -> dict[str, str]:
        return {p.stem: json.loads(p.read_text())["state"] for p in sorted((self.root / "containers").glob("*.json"))}

    def networks(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "networks").glob("*.json"))

    def left(self) -> list[str]:
        return sorted([*self.containers(), *self.networks()])

    def calls(self) -> list[str]:
        f = self.root / "calls.log"
        if not f.exists():
            return []
        lines = [line.split(" ", 1)[1] for line in f.read_text().splitlines()]
        return [c for c in lines if not c.startswith(("__create_later", "daemon:"))]  # 假容器服务自己的那一半不算


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    d = Daemon(tmp_path / "daemon")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "docker"
    exe.write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE} "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(d.root))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    real = subprocess.run

    def scaled(*a, **kw):  # 只缩短超时，别的原样
        if kw.get("timeout"):
            kw["timeout"] = SHORT.get(kw["timeout"], kw["timeout"])
        return real(*a, **kw)

    monkeypatch.setattr(runtime.subprocess, "run", scaled)
    yield d
    time.sleep(0.1)


@pytest.fixture
def ex(daemon):
    e = DockerExecutor(graph=None, blobs=None, token="t")  # type: ignore[arg-type]
    e.now = 1000.0  # type: ignore[attr-defined]
    e._clock = lambda: e.now  # type: ignore[attr-defined]
    return e


def spec(tmp_path) -> ExecSpec:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return ExecSpec(id="x1", image="img", baseline_ref="b", workspace=str(ws), limits=Limits())


def launch_fails(ex, tmp_path, lease="7") -> str:
    with pytest.raises(subprocess.TimeoutExpired) as err:
        ex.launch(spec(tmp_path), lease)
    assert err.value.cmd[1] == "run" and err.value.__context__ is None  # 抛出的是原来那个超时，不是善后里的
    (row,) = ex.doomed()
    assert row["lease"] == lease and ex.sandboxes() == []
    return row["sid"]


def ended(*leases: str, age: float = 3600.0):
    return lambda lease: age if lease in leases else None


# ---------- 方案三：善后做牢 + 待确认表 ----------


def test_a_container_that_appears_after_cleanup_is_caught_by_the_recheck(daemon, ex, tmp_path):
    """甲（cz 那一次）：只有建容器这一条慢，清理跑完了、网络删了，之后容器才出现。"""
    daemon.plan(create_after_s=T * 1.6)
    sid = launch_fails(ex, tmp_path)
    assert daemon.left() == []  # 清理跑完了：这一刻什么都没有
    assert ex.settle() == [] and [r["sid"] for r in ex.doomed()] == [sid]  # 第一次复查什么都没有：不能就此划掉
    ex.now += DOOM_KEEP_S / 2
    assert ex.settle() == [] and ex.doomed()  # 没到 10 分钟：还在表里
    time.sleep(T * 0.8)
    assert daemon.containers() == {sid: "created"}  # 容器服务这才把它建出来：已创建、从未启动
    assert ex.settle() == [sid] and daemon.left() == []  # 复查把它收掉
    ex.now += DOOM_KEEP_S  # 过了 10 分钟，但刚才那一轮还删到过东西：要再确认一次“确实没有”
    assert [r["sid"] for r in ex.doomed()] == [sid]
    assert ex.settle() == [] and ex.doomed() == []  # 查询成功、确认不存在、已过 10 分钟：划掉
    assert daemon.left() == []


STALL = 10.0  # 乙里容器服务无响应的时长：要盖过起沙箱的超时、整轮清理和一次复查


def test_a_cleanup_cut_short_by_an_unresponsive_daemon_is_finished_later(daemon, ex, tmp_path):
    """乙：从收到建容器的请求起容器服务整个无响应。以前清理的第一条查询一超时就抛，一条删除都没发。"""
    daemon.plan(create_after_s=0, stall_from_run=True, stall_s=STALL)
    t0 = time.monotonic()
    sid = launch_fails(ex, tmp_path)
    assert time.monotonic() - t0 < T + SHORT[30.0] + 7 * SHORT[5.0] + 1  # 第一条没答之后，剩下七条只发不久等
    after_run = daemon.calls()[daemon.calls().index("run -d --name") + 1 :]
    assert after_run[0] == f"rm -f -v {sid}"  # 删除先按名字发，不等查询
    assert {"ps -a --format", "network inspect --format", f"network rm {sid}-net"} <= {c for c in after_run}
    assert ex.settle() == []  # 还没恢复：列取用短超时，立刻回来，表不动
    assert [r["sid"] for r in ex.doomed()] == [sid]
    time.sleep(max(0.0, t0 + STALL + 0.5 - time.monotonic()))
    # 恢复之后：超时的那几条删除没有生效（假服务不补做），容器与网络都还在——复查收掉
    assert daemon.containers() == {sid: "created"} and daemon.networks() == [f"{sid}-net"]
    assert sorted(ex.settle()) == [sid, f"{sid}-net"] and daemon.left() == []
    ex.now += DOOM_KEEP_S
    assert ex.settle() == [] and ex.doomed() == [] and daemon.left() == []


def test_a_slow_but_successful_launch_is_not_doomed(daemon, ex, tmp_path):
    daemon.plan(create_after_s=T * 0.3)
    sid = ex.launch(spec(tmp_path), "7")
    assert ex.doomed() == [] and daemon.containers() == {sid: "running"} and ex.settle() == []
    ex.destroy(sid)
    assert daemon.left() == [] and ex.doomed() == []


def test_the_recheck_only_takes_what_carries_both_labels(daemon, ex, tmp_path):
    """复查按“沙箱标签 = 这个名字、属主标签 = 本实例”两个标签找：同名字标签但属主不同的不碰。"""
    daemon.plan(create_after_s=T * 1.6)
    sid = launch_fails(ex, tmp_path)
    time.sleep(T * 0.8)
    daemon.put("someone-elses", sid, "other-host:1:1")
    daemon.put_net("someone-elses-net", sid, "other-host:1:1")
    assert ex.settle() == [sid]
    assert daemon.left() == ["someone-elses", "someone-elses-net"]


def test_a_sandbox_being_rebuilt_is_left_alone_and_leaves_the_table_once_it_is_up(daemon, ex, tmp_path):
    """正在重建的沙箱（reset：同名再起）：复查这一轮跳过；重建成功从表里划掉，之后的复查不碰它。"""
    daemon.plan(create_after_s=T * 1.6)
    sid = launch_fails(ex, tmp_path)
    time.sleep(T * 0.8)
    assert daemon.containers() == {sid: "created"}
    with ex._rebuild:  # 重建进行中
        assert ex.settle() == [] and daemon.containers() == {sid: "created"}
        assert ex.reclaim(ended("7")) == [] and daemon.containers() == {sid: "created"}  # 租约已结束也一样不碰
    assert ex.settle() == [sid]
    daemon.plan()
    assert ex.launch(spec(tmp_path), "7", sid=sid) == sid  # 同名重建成功
    assert ex.doomed() == [] and [s["sid"] for s in ex.sandboxes()] == [sid]
    ex.now += DOOM_KEEP_S * 2
    assert ex.settle() == [] and daemon.containers() == {sid: "running"}
    assert ex.reclaim(ended()) == [] and daemon.containers() == {sid: "running"}  # 租约在途：兜底回收也不碰


# ---------- 方案四：按租约标签兜底回收 ----------


def test_reclaim_takes_a_finished_lease_with_its_gate_and_both_networks(daemon, ex):
    daemon.sandbox("pd-a-11111111", ex.owner, lease="7")
    assert ex.sandboxes() == []  # 在册表里没有它
    assert ex.reclaim(ended("7")) == ["pd-a-11111111"]
    assert daemon.left() == [] and ex.doomed() == []


@pytest.mark.parametrize("why", ["owner", "unknown_lease", "in_flight", "grace", "no_lease_label", "env_role"])
def test_reclaim_needs_all_four_conditions(daemon, ex, why):
    """四条缺一条就不碰：属主逐字相同；带租约标签且角色是沙箱或闸门；租约账上查得到且已结束；已过宽限。"""
    owner = "other-host:99:1" if why == "owner" else ex.owner
    daemon.sandbox("pd-a-11111111", owner, lease="7")
    if why == "no_lease_label":
        daemon.put("pd-a-11111111", "pd-a-11111111", owner, lease=None)
    if why == "env_role":
        daemon.put("pd-a-11111111", "pd-a-11111111", owner, lease="7", role="env")
        daemon.put("pd-a-11111111-gate-0", "pd-a-11111111", owner, lease="7", role="env")
    before = daemon.left()
    asked: list[str] = []

    def lease_ended(lease: str) -> float | None:
        asked.append(lease)
        if why in ("unknown_lease", "in_flight"):  # 账上查不到 / 仍在途：组装层都答 None
            return None
        return 59.0 if why == "grace" else 3600.0

    assert ex.reclaim(lease_ended, grace_s=60.0) == [] and daemon.left() == before
    if why in ("owner", "env_role"):
        assert asked == []  # 属主或角色不对的，连租约都不去问
    if why == "grace":
        assert ex.reclaim(lambda lease: 60.0, grace_s=60.0) == ["pd-a-11111111"] and daemon.left() == []


def test_reclaim_spares_other_instances_with_the_same_lease_number_and_env_containers(daemon, ex):
    """租约编号在每个实例里从 1 顺序编：共用一个容器服务的两个实例一定有相同的编号，所以必须核对属主。"""
    daemon.sandbox("pd-mine-11111111", ex.owner, lease="1")
    daemon.sandbox("pd-theirs-22222222", "other-host:42:777", lease="1")
    daemon.put("pd-env-ctf", "pd-env-ctf", ex.owner, lease=None, role="env")  # 题目环境容器：没有租约标签
    assert ex.reclaim(ended("1")) == ["pd-mine-11111111"]
    assert daemon.left() == sorted(
        [
            "pd-env-ctf",
            "pd-theirs-22222222",
            "pd-theirs-22222222-gate-0",
            "pd-theirs-22222222-net",
            "pd-theirs-22222222-up-net",
        ]
    )
    # destroy_lease 同样核对属主
    assert ex.destroy_lease("1") == [] and "pd-theirs-22222222" in daemon.containers()


def test_reclaim_cannot_reach_what_the_same_instance_left_before_a_restart(daemon, ex):
    """局限：属主是同一个实例重启前的进程（主机名相同、pid 或启动时刻不同）时，属主标识逐字对不上，不动。
    这一种收不回来；有 /proc 的平台上由孤儿清扫按“属主进程已死”接手，没有 /proc 的平台上仍会留下。"""
    host = ex.owner.split(":")[0]
    old = f"{host}:999999999:1"
    daemon.sandbox("pd-old-33333333", old, lease="7")
    before = daemon.left()
    assert ex.reclaim(ended("7")) == [] and daemon.left() == before
    if runtime._has_proc():
        assert "pd-old-33333333" in sweep_orphans() and daemon.left() == []


def test_reclaim_takes_sandboxes_on_the_books_too_and_replaces_reap(daemon, ex, tmp_path):
    """在册的沙箱租约结束了一样收（原来的 reap 没有调用方，已由 reclaim 取代并删掉）。"""
    daemon.plan()
    a = ex.launch(spec(tmp_path), "2")
    b = ex.launch(spec(tmp_path), "3")
    assert ex.reclaim(ended("2")) == [a]
    assert [s["sid"] for s in ex.sandboxes()] == [b] and daemon.containers() == {b: "running"}
    assert not hasattr(ex, "reap")


def test_reclaim_does_not_raise_or_hang_when_the_daemon_is_unresponsive(daemon, ex):
    daemon.sandbox("pd-a-11111111", ex.owner, lease="7")
    daemon.plan(stall_until=time.time() + 30)
    t0 = time.monotonic()
    assert ex.reclaim(ended("7")) == []  # 列取用短超时：没答就算了，下一轮再来
    assert time.monotonic() - t0 < SHORT[10.0] + 1
    daemon.plan()
    assert ex.reclaim(ended("7")) == ["pd-a-11111111"] and daemon.left() == []


def test_a_failing_lease_lookup_counts_as_unknown(daemon, ex):
    daemon.sandbox("pd-a-11111111", ex.owner, lease="7")
    before = daemon.left()

    def boom(lease: str) -> float | None:
        raise RuntimeError("账读不出来")

    assert ex.reclaim(boom) == [] and daemon.left() == before


# ---------- 孤儿清扫的两条列取命令：短超时，不抛 ----------

DEAD = "this-host:999999999:1"


@pytest.fixture
def dead_owner(monkeypatch):
    """把 DEAD 这个属主判成“进程已死”（真实判断要 /proc，这里不依赖平台）。"""
    monkeypatch.setattr(runtime, "owner_alive", lambda owner: False if owner == DEAD else None)


def test_the_orphan_sweep_behaves_as_before_when_listings_answer(daemon, dead_owner, caplog):
    daemon.sandbox("pd-old-33333333", DEAD)
    daemon.sandbox("pd-live-44444444", "other-host:1:1")
    with caplog.at_level("WARNING"):
        assert sorted(sweep_orphans()) == ["pd-old-33333333", "pd-old-33333333-gate-0"]  # 返回的仍只是容器名
    assert daemon.left() == [
        "pd-live-44444444",
        "pd-live-44444444-gate-0",
        "pd-live-44444444-net",
        "pd-live-44444444-up-net",
    ]
    assert caplog.records == []
    calls = daemon.calls()  # 发出去的命令与改动前一样：列容器、删、列网络、逐张查成员再删
    assert calls[0] == "ps -a --filter" and calls.count("ps -a --filter") == 1
    assert sorted(calls[1:3]) == ["rm -f -v pd-old-33333333", "rm -f -v pd-old-33333333-gate-0"]
    assert calls[3] == "network ls --filter"
    assert sorted(calls[4:]) == sorted(
        ["network inspect --format"] * 2 + ["network rm pd-old-33333333-net", "network rm pd-old-33333333-up-net"]
    )


def test_the_orphan_sweep_gives_up_quietly_when_the_container_listing_does_not_answer(daemon, dead_owner, caplog, ex):
    """容器服务无响应：以前每一轮在这条列取上等满 120 秒再抛，巡查日志里一轮一条“tick 失败”。"""
    daemon.sandbox("pd-old-33333333", DEAD)
    before = daemon.left()
    daemon.plan(stall_until=time.time() + 4)
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="executor"):
        assert sweep_orphans() == []  # 不抛，按“没清到”返回
    assert time.monotonic() - t0 < SHORT[10.0] + 1  # 只等了一条列取的短超时
    assert [r.getMessage() for r in caplog.records] == ["孤儿清扫：ps 没答（等了 10 秒），这一轮跳过，下一轮再来"]
    assert daemon.calls() == ["ps -a --filter"]  # 第二条列取没有再去等
    assert ex.reclaim(ended("7")) == []  # 新增回收照常跑（它自己也是短超时、不抛）
    time.sleep(max(0.0, 4.2 - (time.monotonic() - t0)))
    assert daemon.left() == before
    assert len(sweep_orphans()) == 2 and daemon.left() == []  # 恢复之后的下一轮照常清掉


def test_the_orphan_sweep_reports_what_it_did_when_only_the_network_listing_does_not_answer(
    daemon, dead_owner, caplog, monkeypatch
):
    daemon.sandbox("pd-old-33333333", DEAD)
    real = runtime._docker

    def docker(*args, **kw):
        if args[:2] == ("network", "ls"):
            raise subprocess.TimeoutExpired(["docker", *args], kw["timeout"])
        return real(*args, **kw)

    monkeypatch.setattr(runtime, "_docker", docker)
    with caplog.at_level("WARNING", logger="executor"):
        assert len(sweep_orphans()) == 2  # 容器那一半已经删了：如实返回
    assert daemon.left() == ["pd-old-33333333-net", "pd-old-33333333-up-net"]  # 网络留给下一轮
    (line,) = [r.getMessage() for r in caplog.records]
    assert line == "孤儿清扫：network ls 没答（等了 10 秒），这一轮跳过，下一轮再来"
    monkeypatch.setattr(runtime, "_docker", real)
    assert sweep_orphans() == [] and daemon.left() == []


def test_the_orphan_sweep_does_not_raise_when_the_command_line_is_missing(daemon, caplog, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    with caplog.at_level("WARNING", logger="executor"):
        assert sweep_orphans() == []
    (line,) = [r.getMessage() for r in caplog.records]
    assert line == "孤儿清扫：ps 的命令行起不来，这一轮跳过，下一轮再来" and "/" not in line
