"""执行层运行时：需要本机 Docker；没有时跳过。不用题目容器：目标是临时的通用 HTTP 容器。

验收：3.6.4 的 1（越界不通）、2（r0 容器没有 r1 通路）、3（判官洁净容器看不到 Worker 的文件）、
4（执行容器一侧：没有模型密钥、连不到外网与模型端点）；exec 的采集、登记与 8 KB 截断回显。
"""

import hashlib
import os
import shutil
import socket
import subprocess
import uuid

import pytest

from paoding_executor.compile import Limits, compile_spec
from paoding_executor.runtime import ECHO_LIMIT, DockerExecutor

IMAGE = "python:3.12-slim"


def _docker_ok():
    if not shutil.which("docker"):
        return False
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")


class FakeGraph:
    def __init__(self):
        self.calls = []

    def submit(self, token, pid, idem_key, ops):
        self.calls.append((token, pid, idem_key, ops))
        return {"ok": True, "results": [{"ok": True, "id": f"a_{len(self.calls)}"}]}


class MemBlobs:
    def __init__(self):
        self.d = {}

    def put(self, data):
        data = data if isinstance(data, bytes) else data.read()  # 执行层给的是只读流
        h = hashlib.sha256(data).hexdigest()
        self.d[h] = data
        return h

    def get(self, h, start=0, end=None):
        return self.d[h][start:end]


@pytest.fixture(scope="module")
def targets():
    names = [f"pdt-{uuid.uuid4().hex[:6]}-{i}" for i in range(2)]
    for n in names:
        subprocess.run(
            ["docker", "run", "-d", "--name", n, IMAGE, "python", "-m", "http.server", "80"],
            check=True,
            capture_output=True,
        )
    yield names
    for n in names:
        subprocess.run(["docker", "rm", "-f", n], capture_output=True)


@pytest.fixture
def ex(tmp_path):
    os.chmod(tmp_path, 0o777)
    e = DockerExecutor(FakeGraph(), MemBlobs(), "tok-exec")
    yield e
    for sid in list(e._live):
        e.destroy(sid)


ENV = {"base": IMAGE, "baseline_ref": f"{IMAGE}@test"}
PROBE = (
    'python -c "import socket,sys;s=socket.socket();s.settimeout(3);'
    "sys.exit(0 if s.connect_ex(('{h}',{p}))==0 else 7)\""
)


def _scope(targets):
    return [
        {"resource": "net", "pattern": f"{targets[0]}:80", "actions": ["*"], "risk": "r0"},
        {"resource": "net", "pattern": f"{targets[1]}:80", "actions": ["*"], "risk": "r1"},
    ]


def test_exec_capture_and_register(ex, tmp_path, targets):
    spec = compile_spec("t1", _scope(targets), ENV, "r0", False, str(tmp_path))
    sid = ex.launch(spec, "l_1")
    r = ex.exec(sid, "echo hello; echo oops >&2; exit 3", "p1", "k1")
    assert r.exit_code == 3 and r.artifact == "a_1"
    assert ex.blobs.get(r.blob) == b"hello\noops\n"
    token, pid, _, ops = ex.graph.calls[0]
    body = ops[0]["body"]
    assert token == "tok-exec" and body["class"] == "exec" and body["exec"]["command"].startswith("echo hello")
    big = ex.exec(sid, f"python -c \"print('x'*{3 * ECHO_LIMIT})\"", "p1", "k2")
    assert big.truncated and len(big.output.encode()) < ECHO_LIMIT + 200
    assert len(ex.blobs.get(big.blob)) == 3 * ECHO_LIMIT + 1


def test_timeout(ex, tmp_path, targets):
    sid = ex.launch(compile_spec("t2", _scope(targets), ENV, "r0", False, str(tmp_path)), "l_1")
    r = ex.exec(sid, "echo start; sleep 30", "p1", "k1", timeout_s=2)
    assert r.exit_code is None and "start" in r.output and r.ended_by == "timeout"
    assert ex.exec(sid, "exit 137", "p1", "k2").ended_by == "killed"  # 没到点的 137 不算超时


def test_oom_is_told_apart_from_timeout(ex, tmp_path):
    """P1-2：触到内存上限被杀与超时是两种结束方式；依据是守护进程的 oom 事件。"""
    spec = compile_spec("t2m", [], ENV, "r0", False, str(tmp_path), limits=Limits(mem_mb=64))
    sid = ex.launch(spec, "l_1")
    r = ex.exec(sid, "echo start; exec python -c 'x = bytearray(400 * 1024 * 1024); print(len(x))'", "p1", "k1")
    assert (r.exit_code, r.ended_by) == (137, "oom") and "start" in r.output
    assert "内存上限 64 MB" in r.output
    ok = ex.exec(sid, "echo still-here", "p1", "k2")  # 容器还在，后续命令照常
    assert (ok.exit_code, ok.ended_by) == (0, "exit")


def test_capture_keeps_head_and_tail_while_streaming(tmp_path):
    """P1-2：上限在读的过程中生效：超过上限只留头尾，Blob 不超过上限。"""
    os.chmod(tmp_path, 0o777)
    with DockerExecutor(FakeGraph(), MemBlobs(), "tok-exec", max_capture=1 << 20) as e:
        sid = e.launch(compile_spec("t2c", [], ENV, "r0", False, str(tmp_path)), "l_1")
        r = e.exec(sid, "python -c \"import sys; sys.stdout.write('H'*1000 + 'x'*3000000 + 'T'*1000)\"", "p1", "k1")
        data = e.blobs.get(r.blob)
        assert len(data) == 1 << 20 and data.startswith(b"H" * 1000 + b"x") and data.endswith(b"x" + b"T" * 1000)
        assert r.truncated and r.provenance["truncated"] and r.exit_code == 0
        assert e.graph.calls[0][3][0]["body"]["size"] == 1 << 20


def test_huge_output_does_not_land_in_memory(tmp_path):
    """P1-2 验收：300 MB 的输出，本进程的内存峰值几乎不动；落盘的 Blob 正好是 256 MB 上限。"""
    import resource

    from paoding_executor.runtime import MAX_CAPTURE
    from paoding_graph.contract import BlobStore

    os.chmod(tmp_path, 0o777)
    blobs = BlobStore(tmp_path / "blobs")
    spool = tmp_path / "spool"
    spool.mkdir()
    with DockerExecutor(FakeGraph(), blobs, "tok-exec", spool_dir=str(spool)) as e:
        sid = e.launch(compile_spec("t2h", [], ENV, "r0", False, str(tmp_path)), "l_1")
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        r = e.exec(sid, "head -c 314572800 /dev/zero", "p1", "k1", timeout_s=120)
        grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
    assert r.exit_code == 0 and r.truncated and r.provenance["truncated"]
    assert blobs.size(r.blob) == MAX_CAPTURE and list(spool.iterdir()) == []
    assert grown_mb < 32, f"采集让进程内存涨了 {grown_mb:.0f} MB"


def test_scope_enforced_by_risk(ex, tmp_path, targets):
    """3.6.4 的 1、2：r0 容器连得到 r0 目标，连不到 r1 目标与外网。"""
    sid = ex.launch(compile_spec("t3", _scope(targets), ENV, "r0", False, str(tmp_path)), "l_1")
    assert ex.exec(sid, PROBE.format(h=targets[0], p=80), "p1", "a").exit_code == 0
    assert ex.exec(sid, PROBE.format(h=targets[1], p=80), "p1", "b").exit_code != 0
    assert ex.exec(sid, PROBE.format(h="1.1.1.1", p=443), "p1", "c").exit_code != 0
    sid1 = ex.launch(compile_spec("t3b", _scope(targets), ENV, "r1", False, str(tmp_path)), "l_2")
    assert ex.exec(sid1, PROBE.format(h=targets[1], p=80), "p1", "d").exit_code == 0


def test_no_keys_no_model_endpoint(ex, tmp_path, targets):
    """3.6.4 的 4（执行容器一侧）：没有任何密钥类环境变量；连不到模型端点。"""
    sid = ex.launch(compile_spec("t4", _scope(targets), ENV, "r0", False, str(tmp_path)), "l_1")
    env = ex.exec(sid, "env", "p1", "a").output
    names = [line.split("=", 1)[0].upper() for line in env.splitlines() if "=" in line]
    # 镜像自带的 GPG_KEY 是公开的签名指纹，不是凭据；凭据类变量一个都不许有
    assert not [n for n in names if any(w in n for w in ("ANTHROPIC", "API_KEY", "TOKEN", "SECRET", "PASSWORD"))]
    assert "sk-ant" not in env
    assert ex.exec(sid, PROBE.format(h="api.anthropic.com", p=443), "p1", "b").exit_code != 0


def test_judge_clean_container(ex, tmp_path, targets):
    """3.6.4 的 3：Worker 写入的文件在判官的洁净容器里不存在。"""
    spec = compile_spec("t5", _scope(targets), ENV, "r0", False, str(tmp_path))
    w = ex.launch(spec, "l_1")
    ex.exec(w, "echo forged > /workspace/proof.txt; echo forged > /tmp/proof.txt", "p1", "a")
    assert (tmp_path / "proof.txt").exists()
    j = ex.launch(spec, "l_j", mount_workspace=False)
    r = ex.exec(j, "cat /workspace/proof.txt /tmp/proof.txt", "p1", "b", register_as="judge")
    assert r.exit_code != 0 and r.artifact is None
    assert len(ex.graph.calls) == 1  # judge 模式不由执行层登记


def test_reset_returns_to_baseline(ex, tmp_path, targets):
    sid = ex.launch(compile_spec("t6", _scope(targets), ENV, "r0", False, str(tmp_path)), "l_1")
    ex.exec(sid, "echo x > /tmp/state", "p1", "a")
    sid2 = ex.reset(sid)
    assert ex.exec(sid2, "test -e /tmp/state", "p1", "b").exit_code != 0


def test_sweep_only_dead_owners(ex, tmp_path, targets):
    """评审方 #14 必修 2：孤儿清扫只清属主已死的沙箱；活实例的、别的主机的一律不动。"""
    from paoding_executor.runtime import LABEL, OWNER, sweep_orphans

    spec = compile_spec("s1", [], ENV, "r0", False, str(tmp_path))
    live = ex.launch(spec, "l_1")
    tag = uuid.uuid4().hex[:6]
    dead, foreign = f"pd-dead-{tag}", f"pd-foreign-{tag}"
    for name, owner in [(dead, f"{socket.gethostname()}:999999:1"), (foreign, "other-host:1:1")]:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--label",
                f"{LABEL}={name}",
                "--label",
                f"{OWNER}={owner}",
                IMAGE,
                "sleep",
                "infinity",
            ],
            check=True,
            capture_output=True,
        )
    try:
        swept = sweep_orphans()
        assert dead in swept and live not in swept and foreign not in swept
        alive = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True).stdout.decode()
        assert live in alive and foreign in alive and dead not in alive
    finally:
        subprocess.run(["docker", "rm", "-f", dead, foreign], capture_output=True)
        ex.destroy(live)
