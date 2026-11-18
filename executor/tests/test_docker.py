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
        data = data if isinstance(data, bytes) else data.read()      # 执行层给的是只读流
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
    assert r.exit_code is None and "start" in r.output and r.ended_by == "timeout"
    assert ex.exec(sid, "exit 137", "p1", "k2").ended_by == "killed"      # 没到点的 137 不算超时


def test_oom_is_told_apart_from_timeout(ex, tmp_path):
    """P1-2：触到内存上限被杀与超时是两种结束方式；依据是守护进程的 oom 事件。"""
    spec = compile_spec("t2m", [], ENV, "r0", False, str(tmp_path), limits=Limits(mem_mb=64))
    sid = ex.launch(spec, "l_1")
    r = ex.exec(sid, "echo start; exec python -c 'x = bytearray(400 * 1024 * 1024); print(len(x))'", "p1", "k1")
    assert (r.exit_code, r.ended_by) == (137, "oom") and "start" in r.output
    assert "内存上限 64 MB" in r.output
    ok = ex.exec(sid, "echo still-here", "p1", "k2")                      # 容器还在，后续命令照常
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


TWO_PORTS = ("import http.server,threading\n"
             "for p in (8080, 8081):\n"
             "    threading.Thread(target=http.server.ThreadingHTTPServer(('', p), "
             "http.server.SimpleHTTPRequestHandler).serve_forever).start()\n")
GET = "python -c \"import urllib.request as u;print(u.urlopen('http://{h}:{p}/',timeout=5).status)\""


@pytest.fixture(scope="module")
def duo():
    """一台目标、两个端口都在监听：8080 与 8081。"""
    name = f"pdt-{uuid.uuid4().hex[:6]}-duo"
    subprocess.run(["docker", "run", "-d", "--name", name, IMAGE, "python", "-c", TWO_PORTS], check=True,
                   capture_output=True)
    yield name
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _addresses(name):
    fmt = "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}"
    return subprocess.run(["docker", "inspect", "--format", fmt, name], capture_output=True).stdout.decode().split()


def test_egress_is_port_level(ex, tmp_path, duo):
    """P0-4 验收：r0 规则只放行 duo:8080；同一容器的 8081 被拒，绕过名字直连目标地址也不通。"""
    scope = [{"resource": "net", "pattern": f"{duo}:8080", "actions": ["connect"], "risk": "r0"},
             {"resource": "net", "pattern": f"{duo}:8081", "actions": ["connect"], "risk": "r1"}]
    sid = ex.launch(compile_spec("pl", scope, ENV, "r0", False, str(tmp_path)), "l_1")
    assert ex.exec(sid, GET.format(h=duo, p=8080), "p1", "a").output.strip() == "200"      # 内容真的转发到了
    assert ex.exec(sid, PROBE.format(h=duo, p=8081), "p1", "b").exit_code == 7
    assert "refused" in ex.exec(sid, GET.format(h=duo, p=8081), "p1", "c").output.lower()
    for ip in _addresses(duo):                                # 目标的真实地址（默认网桥、上游网络）
        for port in (8080, 8081):
            assert ex.exec(sid, PROBE.format(h=ip, p=port), "p1", f"d{ip}{port}").exit_code == 7
    hi = ex.launch(compile_spec("pl1", scope, ENV, "r1", False, str(tmp_path)), "l_2")     # 上限抬到 r1：两个端口都通
    assert ex.exec(hi, GET.format(h=duo, p=8081), "p1", "e").output.strip() == "200"


def test_gate_enforces_actions(ex, tmp_path, duo):
    """P0-4：actions 由闸门执行。含 connect（或 *）的端口才开；只写了别的动作的规则不开通路。"""
    from paoding_executor.runtime import gate_log
    scope = [{"resource": "net", "pattern": f"{duo}:8080", "actions": ["read"], "risk": "r0"},
             {"resource": "net", "pattern": f"{duo}:8081", "actions": ["*"], "risk": "r0"}]
    spec = compile_spec("ga", scope, ENV, "r0", False, str(tmp_path))
    assert spec.egress_allow == (f"{duo}:8081",)
    sid = ex.launch(spec, "l_1")
    assert ex.exec(sid, PROBE.format(h=duo, p=8080), "p1", "a").exit_code == 7
    assert ex.exec(sid, GET.format(h=duo, p=8081), "p1", "b").output.strip() == "200"
    [gate] = ex._live[sid]["gates"]
    log = gate_log(gate)
    rules = {e["dst"]: e["open"] for e in log if e["event"] == "rule"}
    assert rules == {f"{duo}:8080": False, f"{duo}:8081": True}
    assert [(e["dst"], e["ok"]) for e in log if e["event"] == "connect"] == [(f"{duo}:8081", True)]


def test_gate_only_serves_the_sandbox(ex, tmp_path, duo):
    """闸门只认执行容器的源地址：别的容器即使接进沙箱网络，也拿不到目标的内容（3.6.4 的 4 的网络一侧）。"""
    from paoding_executor.runtime import gate_log
    scope = [{"resource": "net", "pattern": f"{duo}:8080", "actions": ["connect"], "risk": "r0"}]
    sid = ex.launch(compile_spec("gs", scope, ENV, "r0", False, str(tmp_path)), "l_1")
    other = f"pdt-{uuid.uuid4().hex[:6]}-other"
    try:
        p = subprocess.run(["docker", "run", "--rm", "--name", other, "--network", f"{sid}-net", IMAGE, "sh", "-c",
                            GET.format(h=duo, p=8080)], capture_output=True)
        assert p.returncode != 0 and b"200" not in p.stdout
    finally:
        subprocess.run(["docker", "rm", "-f", other], capture_output=True)
    [gate] = ex._live[sid]["gates"]
    assert [e["why"] for e in gate_log(gate) if e["event"] == "deny"] == ["source"]
    assert ex.exec(sid, GET.format(h=duo, p=8080), "p1", "a").output.strip() == "200"


def test_gate_is_hardened(ex, tmp_path, duo):
    scope = [{"resource": "net", "pattern": f"{duo}:8080", "actions": ["connect"], "risk": "r0"}]
    sid = ex.launch(compile_spec("gh", scope, ENV, "r0", False, str(tmp_path)), "l_1")
    [gate] = ex._live[sid]["gates"]
    fmt = "{{.HostConfig.CapDrop}}|{{.HostConfig.SecurityOpt}}|{{.HostConfig.ReadonlyRootfs}}|{{.Config.User}}|{{len .Mounts}}|{{.Config.Env}}"
    got = subprocess.run(["docker", "inspect", "--format", fmt, gate], capture_output=True).stdout.decode().strip()
    assert got.startswith("[ALL]|[no-new-privileges]|true|65534:65534|0|")
    assert not any(w in got.upper() for w in ("ANTHROPIC", "API_KEY", "TOKEN", "SECRET"))
    nets = subprocess.run(["docker", "inspect", "--format", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}",
                           gate], capture_output=True).stdout.decode().split()
    assert sorted(nets) == [f"{sid}-net", f"{sid}-up-net"]      # 两张都是内部网络：闸门自己也出不了外网
    ex.destroy(sid)
    left = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True).stdout.decode()
    assert gate not in left and duo in left


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


def test_sweep_only_dead_owners(ex, tmp_path, targets):
    """评审方 #14 必修 2：孤儿清扫只清属主已死的沙箱；活实例的、别的主机的一律不动。"""
    from paoding_executor.runtime import LABEL, OWNER, sweep_orphans
    spec = compile_spec("s1", [], ENV, "r0", False, str(tmp_path))
    live = ex.launch(spec, "l_1")
    tag = uuid.uuid4().hex[:6]
    dead, foreign = f"pd-dead-{tag}", f"pd-foreign-{tag}"
    for name, owner in [(dead, f"{socket.gethostname()}:999999:1"), (foreign, "other-host:1:1")]:
        subprocess.run(["docker", "run", "-d", "--name", name, "--label", f"{LABEL}={name}", "--label",
                        f"{OWNER}={owner}", IMAGE, "sleep", "infinity"], check=True, capture_output=True)
    try:
        swept = sweep_orphans()
        assert dead in swept and live not in swept and foreign not in swept
        alive = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True).stdout.decode()
        assert live in alive and foreign in alive and dead not in alive
    finally:
        subprocess.run(["docker", "rm", "-f", dead, foreign], capture_output=True)
        ex.destroy(live)
