"""执行层运行时：需要本机 Docker；没有时跳过。不用靶场：目标是临时的通用 HTTP 容器。

验收：3.6.4 的 1（越界不通）、2（r0 容器没有 r1 通路）、3（判官洁净容器看不到 Worker 的文件）、
4（执行容器一侧：没有模型密钥、连不到外网与模型端点）；exec 的采集、登记与 8 KB 截断回显。
"""
import hashlib
import os
import shutil
import subprocess
import uuid

import pytest

from paoding_executor.compile import compile_spec
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
        h = hashlib.sha256(data).hexdigest()
        self.d[h] = data
        return h

    def get(self, h, start=0, end=None):
        return self.d[h][start:end]


@pytest.fixture(scope="module")
def targets():
    names = [f"pdt-{uuid.uuid4().hex[:6]}-{i}" for i in range(2)]
    for n in names:
        subprocess.run(["docker", "run", "-d", "--name", n, IMAGE, "python", "-m", "http.server", "80"],
                       check=True, capture_output=True)
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
PROBE = ("python -c \"import socket,sys;s=socket.socket();s.settimeout(3);"
         "sys.exit(0 if s.connect_ex(('{h}',{p}))==0 else 7)\"")


def _scope(targets):
    return [{"resource": "net", "pattern": f"{targets[0]}:80", "actions": ["*"], "risk": "r0"},
            {"resource": "net", "pattern": f"{targets[1]}:80", "actions": ["*"], "risk": "r1"}]


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
    assert r.exit_code is None and "start" in r.output


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
    assert len(ex.graph.calls) == 1                      # judge 模式不由执行层登记


def test_reset_returns_to_baseline(ex, tmp_path, targets):
    sid = ex.launch(compile_spec("t6", _scope(targets), ENV, "r0", False, str(tmp_path)), "l_1")
    ex.exec(sid, "echo x > /tmp/state", "p1", "a")
    sid2 = ex.reset(sid)
    assert ex.exec(sid2, "test -e /tmp/state", "p1", "b").exit_code != 0
