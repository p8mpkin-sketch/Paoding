"""replay 判官落在真的执行层上：每次重放一个新建的洁净容器，不挂 Worker 的工作区，跑完即拆（需要本机 Docker）。

验收：3.3.5 的 3（伪造的工作区文件过不了重放）、3.2.5 的洁净重放、3.6.4 的 3（判官容器看不到任务容器的东西）。
"""

import subprocess

import pytest
from judge_rig import IMAGE, JRig, docker_ok

from paoding_executor.contract import DockerExecutor, EnvManager, compile_spec

# 纯计算的题：授权范围里只有工作区，任务与判官容器都没有任何出站通路，重放也不要求碰过资源
QUIET = [{"resource": "workspace", "pattern": "*", "actions": ["read", "write"], "risk": "r0"}]
pytestmark = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")


@pytest.fixture
def dj(tmp_path):
    r = JRig(tmp_path, executor="pending")
    r.box = r.runner.executor = DockerExecutor(r.svc, r.blobs, "tok-exec")
    yield r
    r.box.close()


def containers(r):
    out = (
        subprocess.run(
            ["docker", "ps", "-a", "--filter", f"label=paoding.owner={r.box.owner}", "--format", "{{.Names}}"],
            capture_output=True,
        )
        .stdout.decode()
        .split()
    )
    return sorted(out)


def fact(r, script, expect):
    lid, tok = r.session()
    return r.fact(tok, {"judge_id": "replay", "spec_ref": r.spec(script), "expect": expect})


def test_replay_passes_on_a_reproducible_spec(dj):
    dj.open(scope=QUIET)
    fid, rid = fact(dj, "echo value-$((6*7))", {"stdout_contains": "value-42", "exit_code": 0})
    [done] = dj.runner.tick()
    assert done["result"] == "pass", done
    assert dj.level("p1", fid) == "E3" and containers(dj) == []
    ev = dj.state["artifacts"][done["evidence"]]
    assert ev["class"] == "judge" and b"value-42" in dj.blobs.get(ev["hash"])
    assert ev["exec"]["tool"] == "replay" and ev["exec"]["base"] == IMAGE


def test_forged_workspace_file_does_not_survive_replay(dj, tmp_path):
    """Worker 在自己的工作区里放一份"证明"，任务容器里看得到；判官的洁净容器里没有它，重放失败。"""
    dj.open(scope=QUIET)
    ws = tmp_path / "ws"
    ws.mkdir()
    ws.chmod(0o777)
    (ws / "proof.txt").write_text("port 8080 open\n")
    env = {"base": IMAGE, "baseline_ref": "basic@1"}
    sid = dj.box.launch(compile_spec("task", dj.state["problems"]["p1"]["scope"], env, "r0", False, str(ws)), "l-task")
    seen = dj.box.exec(sid, "cat /workspace/proof.txt", "p1", "task-cat")
    assert seen.exit_code == 0 and "open" in seen.output  # 任务容器里确实看得到
    fid, rid = fact(dj, "cat /workspace/proof.txt", {"stdout_contains": "open", "exit_code": 0})
    before = dj.level("p1", fid)
    [done] = dj.runner.tick()
    assert done["result"] == "fail", done
    assert before == "E0" and dj.level("p1", fid) == "X"  # 判定性 fail：论断被证伪
    assert containers(dj) == [sid]  # 判官容器拆了，任务容器不受影响


def test_replay_timeout_kills_the_container(tmp_path):
    from judge_rig import REG, with_flake

    r = JRig(tmp_path, registry=with_flake(REG, "replay", timeout_s=1), executor="pending")
    r.box = r.runner.executor = DockerExecutor(r.svc, r.blobs, "tok-exec")
    try:
        r.open(scope=QUIET)
        fid, rid = fact(r, "sleep 30", {})
        [done] = r.runner.tick()
        assert (done["result"], done["reason"]) == ("inconclusive", "timeout"), done
        assert containers(r) == [] and r.state["requests"][rid]["inconclusive"] == "timeout"
    finally:
        r.box.close()


def test_missing_image_is_an_environment_error(dj):
    dj.cfg.bases = {"basic": "paoding-no-such-image:0"}
    dj.open(scope=QUIET)
    fid, rid = fact(dj, "true", {})
    [done] = dj.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "env_error") and containers(dj) == []


# ---------- 恒真谓词（P0-3）：真闸门、真访问摘要 ----------


@pytest.fixture
def target():
    import uuid

    with EnvManager() as envs:
        boot = "mkdir -p /srv && cd /srv && echo ready > status && exec python -m http.server 8080"
        yield envs.start(f"pdt-{uuid.uuid4().hex[:8]}", IMAGE, command=["sh", "-c", boot], ready_port=8080)


def test_echo_ok_does_not_reach_e3_on_a_real_sandbox(dj, target):
    """验收：题目的观察对象是外部资源；一条 `echo ok`、期望含 ok 的观察类论断，重放没碰任何资源，到不了 E3。"""
    dj.open(scope=[{"resource": "net", "pattern": f"{target}:8080", "actions": ["connect"], "risk": "r0"}])
    lid, tok = dj.session()
    fid, rid = dj.fact(
        tok, {"judge_id": "replay", "spec_ref": dj.spec("echo ok"), "expect": {"stdout_contains": "ok", "exit_code": 0}}
    )
    [done] = dj.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "untouched"), done
    assert dj.level("p1", fid) == "E0" and containers(dj) == [target]  # 判官容器与闸门都拆了
    ev = dj.state["artifacts"][done["evidence"]]
    assert ev["exec"]["touched"] == [] and b"ok" in dj.blobs.get(ev["hash"])
    # 嘴上说连过也不算：访问摘要来自闸门，不来自输出
    fid2, _ = dj.fact(
        tok,
        {
            "judge_id": "replay",
            "spec_ref": dj.spec(f"echo connected to {target}:8080; echo ok"),
            "expect": {"stdout_contains": "ok"},
        },
        title="目标在线",
    )
    [again] = dj.runner.tick()
    assert again["reason"] == "untouched" and dj.level("p1", fid2) == "E0"


def test_a_spec_that_really_reads_the_target_reaches_e3(dj, target):
    """对照：规格真的去读了授权目标，访问摘要里有这条连接，论断升到 E3。"""
    dj.open(scope=[{"resource": "net", "pattern": f"{target}:8080", "actions": ["connect"], "risk": "r0"}])
    read = f"python -c \"import urllib.request as u;print(u.urlopen('http://{target}:8080/status',timeout=5).read().decode())\""
    fid, rid = fact(dj, read, {"stdout_contains": "ready", "exit_code": 0})
    [done] = dj.runner.tick()
    assert done["result"] == "pass", done
    assert dj.level("p1", fid) == "E3" and containers(dj) == [target]
    assert dj.state["artifacts"][done["evidence"]]["exec"]["touched"] == [f"net:{target}:8080"]


def test_control_separates_a_spec_that_reads_its_input_from_a_constant(dj):
    """对照判据（§3.3.3）落在真容器上：读输入的规格主运行通过、对照不通过；打印常量的规格对照也通过。"""
    dj.open(scope=QUIET)
    lid, tok = dj.session()
    bogus = dj.art(b"7\n", cls="authored", who=tok)
    reads = "n=$(cat /workspace/inputs/1 2>/dev/null || echo 6); echo value-$((n*7))"
    check = {"judge_id": "replay", "spec_ref": dj.spec(reads), "expect": {"stdout_contains": "value-42"}}
    good, _ = dj.fact(tok, {**check, "control": {"inputs": [bogus]}}, title="读输入")
    const = {"judge_id": "replay", "spec_ref": dj.spec("echo value-42"), "expect": {"stdout_contains": "value-42"}}
    flat, _ = dj.fact(tok, {**const, "control": {"inputs": [bogus]}}, title="常量")
    done = {d["request"]: d for d in dj.runner.tick()}
    by_target = {dj.state["requests"][rid]["target"]: d for rid, d in done.items()}
    assert by_target[good]["result"] == "pass" and dj.level("p1", good) == "E3"
    assert (by_target[flat]["result"], by_target[flat]["reason"]) == ("inconclusive", "no_contrast")
    assert dj.level("p1", flat) != "E3" and containers(dj) == []
