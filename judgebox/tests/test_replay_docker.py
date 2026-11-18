"""replay 判官落在真的执行层上：每次重放一个新建的洁净容器，不挂 Worker 的工作区，跑完即拆（需要本机 Docker）。

验收：3.3.5 的 3（伪造的工作区文件过不了重放）、3.2.5 的洁净重放、3.6.4 的 3（判官容器看不到任务容器的东西）。
"""

import subprocess

import pytest
from judge_rig import IMAGE, JRig, docker_ok

from paoding_executor.contract import DockerExecutor, compile_spec

# 一条 r1 规则：r0 的任务与判官容器都不编入它，所以这些容器没有任何出站通路
QUIET = [{"resource": "net", "pattern": "nowhere:1", "actions": ["connect"], "risk": "r1"}]
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
