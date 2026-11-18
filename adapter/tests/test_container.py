"""审计 P0-2：模型容器接进运行路径。假 CLI 跑在 Docker 容器里（通用 Python 镜像 + 只读挂进去的 fakecli.py），
不调真模型、不用真密钥；端点代理、工具端点、图服务、执行层都是真的。

验收：
- 会话的 CLI 在模型容器里跑完整条链（MCP 工具、端点代理计量、exec 落到执行容器）；
- 模型容器内能访问工具端点（MCP）与端点代理，不能访问外网、题目容器与宿主（规格 §3.4.2、3.6.4 的 4）；
- 容器里只有任务令牌，没有真实密钥；只挂工作区、会话目录（只读）与 HOME；
- 软线（SIGINT）与终止送得进容器；会话结束后容器、中继、网络都不留。
"""

import http.client
import json
import socket
import subprocess
import threading
import time

import pytest
from adapter_rig import FETCH, IMAGE, DockerRig, docker_ok, graph, lease_bootstrap, open_net_problem, upstream  # noqa: F401  fixture

from paoding_adapter import backend as be
from paoding_adapter.container import MCP_PORT, PROXY_PORT, RELAY_ALIAS, ContainerLauncher, ContainerProc, UnixBridge

EXEC, SUBMIT, SHOW = "mcp__paoding__exec", "mcp__paoding__submit", "mcp__paoding__show"
REAL_KEY = "sk-fake-upstream"  # 测试台交给端点代理的“真实密钥”（假的）：不得出现在容器里

needs_docker = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, timeout=60)


def leftovers():
    names = docker("ps", "-a", "--filter", "name=pd-model-", "--format", "{{.Names}}").stdout.decode().split()
    nets = docker("network", "ls", "--filter", "name=pd-model-", "--format", "{{.Name}}").stdout.decode().split()
    return sorted(names + nets)


class ContainerRig(DockerRig):
    """DockerRig 的接线，CLI 换到模型容器里跑。"""

    def __init__(self, tmp_path, graph, upstream):
        super().__init__(tmp_path, graph, upstream)
        self.script_dir = tmp_path / "scripts"
        self.script_dir.mkdir()
        self.launcher = ContainerLauncher(
            IMAGE,
            self.proxy.server.server_address[1],
            self.endpoint.server.server_address[1],
            mounts=((str(be.FAKE_CLI), be.FAKE_CLI_IN_CONTAINER), (str(self.script_dir), "/scripts")),
        )
        self.runner.launcher = self.launcher
        self.cfg.binding = be.CliBinding(program=be.fake_program(in_container=True))

    def script_for(self, role, steps, resume_steps=()):
        p = self.script_dir / f"{role}.json"
        p.write_text(json.dumps({"steps": list(steps), "resume_steps": list(resume_steps)}))
        self.scripts[role] = p
        return p

    def start(self, lease_id, pid="p1"):
        """在线程里跑会话，返回 (线程, 结果盒)。"""
        box = {}
        t = threading.Thread(target=lambda: box.update(rec=self.run(lease_id, pid)), daemon=True)
        t.start()
        return t, box

    def wait_model(self, lease_id, timeout=30):
        """等模型容器起来并且 CLI 已经走到脚本里（事件流里见到 init）。"""
        name = ContainerLauncher.names(lease_id)["model"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            p = docker("inspect", "--format", "{{.State.Running}}", name)
            if p.returncode == 0 and p.stdout.decode().strip() == "true":
                return name
            time.sleep(0.05)
        raise AssertionError(f"模型容器 {name} 没起来")

    def close(self):
        self.launcher.close()
        super().close()


@pytest.fixture
def crig(tmp_path, graph, upstream):  # noqa: F811
    r = ContainerRig(tmp_path, graph, upstream)
    yield r
    r.close()


def inside(name, code):
    """在模型容器里跑一小段 Python（测试用的探针；模型自己没有任何命令执行工具）。"""
    p = docker("exec", name, "python", "-I", "-c", code)
    return p.returncode, (p.stdout + p.stderr).decode()


CONNECT = "import socket,sys;s=socket.socket();s.settimeout(3);sys.exit(0 if s.connect_ex(('{h}',{p}))==0 else 7)"
# 按名字或地址连：解析不了名字也算连不上
REACH = "import socket,sys\ntry: socket.create_connection(('{h}',{p}),3)\nexcept OSError: sys.exit(7)"


# ---------- 不需要 Docker：命令构造与套接字桥 ----------


def test_container_command_shape(tmp_path):
    sdir = tmp_path / "l_7"
    d = be.container_argv(
        "cli:2.1",
        "pd-model-l-7",
        "pd-model-l-7-net",
        sdir / "workspace",
        sdir,
        ["claude", "-p", "x"],
        {"ANTHROPIC_API_KEY": "pdt-abc"},
        home=sdir / "home",
        user="1000:1000",
        labels={"paoding.role": "model"},
        mounts=(("/a/fakecli.py", "/opt/paoding/fakecli.py"),),
        memory="2g",
        pids=512,
    )
    assert d[:4] == ["docker", "run", "--rm", "--init"] and d[-4:] == ["cli:2.1", "claude", "-p", "x"]
    assert "--read-only" in d and "--privileged" not in d and d[d.index("--cap-drop") + 1] == "ALL"
    assert d[d.index("--network") + 1] == "pd-model-l-7-net" and "-p" not in d[: d.index("cli:2.1")]  # 不发布端口
    mounts = [d[i + 1] for i, a in enumerate(d) if a == "--mount"]
    assert mounts == [
        f"type=bind,src={sdir / 'workspace'},dst=/workspace,bind-propagation=rprivate",
        f"type=bind,src={sdir},dst=/session,readonly",
        f"type=bind,src={sdir / 'home'},dst=/home/pd",
        "type=bind,src=/a/fakecli.py,dst=/opt/paoding/fakecli.py,readonly",
    ]
    assert d[d.index("--user") + 1] == "1000:1000" and "paoding.role=model" in d


def test_unix_bridge_forwards_to_loopback(tmp_path, upstream):  # noqa: F811
    port = upstream.server.server_address[1]
    b = UnixBridge(tmp_path / "u.sock", port)
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(tmp_path / "u.sock"))
        body = json.dumps({"stream": False}).encode()
        s.sendall(
            b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Connection: close\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
        )
        data = b""
        while chunk := s.recv(65536):
            data += chunk
        assert data.startswith(b"HTTP/1.0 200") or data.startswith(b"HTTP/1.1 200")
        assert b'"usage"' in data and len(upstream.seen) == 1
    finally:
        b.close()
    assert not (tmp_path / "u.sock").exists()


# ---------- 需要 Docker ----------


@needs_docker
def test_session_runs_in_model_container(crig, graph):  # noqa: F811
    """主路径：CLI 在模型容器里，经中继调 MCP 工具与端点代理；exec 落在执行容器里，读到题目容器。"""
    host = crig.target({"value": "v-7741"})
    open_net_problem(graph, "p1", [(host, "r0")])
    lid = lease_bootstrap(graph)
    crig.script_for(
        "bootstrap",
        [
            {"tool": EXEC, "input": {"cmd": FETCH.format(host=host, path="value")}},
            {"tool": "Write", "input": {"file_path": "answer.txt", "content": "$r0.output"}},
            {"tool": "Read", "input": {"file_path": "answer.txt"}},
            {
                "tool": SUBMIT,
                "input": {
                    "ops": [{"op": "claim_done", "target": "goal", "candidate_path": "answer.txt"}],
                    "final": {"outcome": "found"},
                },
            },
        ],
    )
    rec = crig.run(lid)
    assert rec.status == "released" and rec.release["outcome"] == "done" and rec.exit_codes == [0]
    init = next(e for e in rec.events if e.get("subtype") == "init")
    assert init["cwd"] == "/workspace"  # CLI 看到的是容器里的路径，不是宿主的
    assert set(init["tools"]) >= {"Read", "Write", EXEC, SUBMIT, SHOW} and "Bash" not in init["tools"]
    results = [e for e in rec.events if e["type"] == "user"]
    assert "v-7741" in results[0]["message"]["content"][0]["content"]  # exec 的回显经 MCP 回到容器里
    assert "v-7741" in results[2]["message"]["content"][0]["content"]  # 文件工具读的是共享的工作区
    assert (crig.tmp / "sessions" / lid / "workspace" / "answer.txt").read_text().strip() == "v-7741"
    # 端点代理计了量：每个回合一个请求，全记在这个租约上
    costs = [c for c in graph.state["costs"] if c["task_id"] == lid and c["source"] == "proxy"]
    assert len(costs) == 4 and all(c["usd_milli"] > 0 for c in costs)
    assert all(s["headers"].get("x-api-key") == REAL_KEY for s in crig.upstream.seen)  # 上游只见真实密钥
    [req] = graph.state["requests"].values()
    assert req["target"] == "goal"
    assert leftovers() == [] and crig.sandboxes() == []  # 模型容器、中继、网络、执行容器都不留


@needs_docker
def test_model_container_reaches_endpoints_but_nothing_else(crig, graph):  # noqa: F811
    host = crig.target({"value": "v-1"})
    open_net_problem(graph, "p1", [(host, "r0")])
    lid = lease_bootstrap(graph)
    crig.script_for(
        "bootstrap",
        [
            {"tool": SHOW, "input": {"list": "all"}},
            {"tool": EXEC, "input": {"cmd": FETCH.format(host=host, path="value")}},
            {"hang": 120},
        ],
    )
    t, box = crig.start(lid)
    try:
        name = crig.wait_model(lid)
        deadline = time.monotonic() + 30
        while len([c for c in graph.state["costs"] if c["task_id"] == lid]) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)  # 等脚本走到 hang：两个回合都经代理计了量
        n = ContainerLauncher.names(lid)

        # —— 环境变量：端点代理地址 + 任务令牌；没有真实密钥 ——
        env = dict(
            kv.split("=", 1) for kv in json.loads(docker("inspect", "--format", "{{json .Config.Env}}", name).stdout)
        )
        assert env["ANTHROPIC_BASE_URL"] == f"http://{RELAY_ALIAS}:{PROXY_PORT}"
        assert env["ANTHROPIC_API_KEY"].startswith("pdt-") and env["ANTHROPIC_API_KEY"] != REAL_KEY
        assert env["HOME"] == "/home/pd"
        assert REAL_KEY not in docker("inspect", name).stdout.decode()
        assert REAL_KEY not in docker("inspect", n["relay"]).stdout.decode()

        # —— 能访问工具端点（MCP）：容器里读到的 --mcp-config 指向中继，initialize 与 tools/list 都通 ——
        code, out = inside(
            name,
            (
                "import json,urllib.request as u\n"
                "url=json.load(open('/session/mcp.json'))['mcpServers']['paoding']['url']\n"
                "def rpc(m,i):\n"
                "    r=u.Request(url,data=json.dumps({'jsonrpc':'2.0','id':i,'method':m,'params':{}}).encode(),"
                "headers={'content-type':'application/json'})\n"
                "    return json.load(u.urlopen(r,timeout=5))['result']\n"
                "print(url.rsplit('/',1)[0]); print(rpc('initialize',1)['serverInfo']['name'])\n"
                "print(sorted(t['name'] for t in rpc('tools/list',2)['tools']))\n"
            ),
        )
        assert code == 0, out
        assert out.splitlines() == [f"http://{RELAY_ALIAS}:{MCP_PORT}/mcp", "paoding", "['exec', 'show', 'submit']"]

        # —— 能访问端点代理：带错令牌得到代理自己的 401（到得了代理，过不了鉴权） ——
        code, out = inside(
            name,
            (
                "import urllib.request as u,urllib.error as e\n"
                f"r=u.Request('http://{RELAY_ALIAS}:{PROXY_PORT}/v1/messages',data=b'{{}}',headers={{'x-api-key':'nope'}})\n"
                "try: u.urlopen(r,timeout=5)\n"
                "except e.HTTPError as x: print(x.code, x.read().decode())\n"
            ),
        )
        assert code == 0 and out.startswith("401") and "unknown_or_revoked_token" in out, out

        # —— 不能访问外网：没有出站路由，也解析不了外部域名 ——
        for h, p in (("1.1.1.1", 443), ("8.8.8.8", 53), ("93.184.216.34", 80)):
            assert inside(name, CONNECT.format(h=h, p=p))[0] == 7, (h, p)
        code, out = inside(name, "import socket;print(socket.gethostbyname('example.com'))")
        assert code != 0, out
        net = json.loads(docker("network", "inspect", n["net"]).stdout)[0]
        assert net["Internal"] is True
        assert sorted(c["Name"] for c in net["Containers"].values()) == sorted([n["model"], n["relay"]])

        # —— 不能访问宿主：网桥上没有宿主地址（隔离网关），端点代理与工具端点只在本机回环上 ——
        gw = (
            docker("network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}")
            .stdout.decode()
            .strip()
        )
        own_gw = (net["IPAM"]["Config"][0].get("Gateway") or "").split("/")[0]
        for port in (crig.proxy.server.server_address[1], crig.endpoint.server.server_address[1]):
            for h in filter(None, (gw, own_gw, "host.docker.internal")):
                assert inside(name, REACH.format(h=h, p=port))[0] == 7, (h, port)

        # —— 不能访问授权范围内的目标（3.6.4 的 4）：题目容器不在这张网络上；执行容器刚才读到了它 ——
        target_ip = (
            docker("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", host)
            .stdout.decode()
            .split()
        )
        assert target_ip
        for h in (host, *target_ip):
            assert inside(name, REACH.format(h=h, p=8080))[0] == 7, h
        assert "rec" not in box  # 会话还在跑
        [sandbox] = crig.sandboxes()
        # —— 反过来：执行容器到不了中继（它不在模型网络上），也就到不了模型端点 ——
        relay_ip = (
            docker("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", n["relay"])
            .stdout.decode()
            .split()
        )
        for h in (RELAY_ALIAS, n["relay"], *relay_ip):
            assert docker("exec", sandbox, "python", "-I", "-c", REACH.format(h=h, p=PROXY_PORT)).returncode == 7, h

        # —— 挂载：会话目录只读，根文件系统只读，工作区可写；没有 docker 套接字 ——
        code, out = inside(
            name,
            (
                "import os\n"
                "def can(p):\n"
                "    try: open(p,'w').close(); return True\n"
                "    except OSError: return False\n"
                "print(can('/session/x'), can('/etc/x'), can('/workspace/x'), can('/home/pd/x'),"
                " os.path.exists('/var/run/docker.sock'), os.getuid()==%d)\n" % __import__("os").getuid()
            ),
        )
        assert out.split() == ["False", "False", "True", "True", "False", "True"], out
        mounts = json.loads(docker("inspect", "--format", "{{json .Mounts}}", name).stdout)
        assert sorted(m["Destination"] for m in mounts) == sorted(
            ["/workspace", "/session", "/home/pd", be.FAKE_CLI_IN_CONTAINER, "/scripts"]
        )
    finally:
        crig.runner.kill(lid, "shutdown")
        t.join(30)
    rec = box["rec"]
    assert rec.status == "killed(shutdown)" and rec.release["outcome"] == "failed"
    assert leftovers() == [] and crig.sandboxes() == []


@needs_docker
def test_soft_line_reaches_the_cli_and_closing_round_resumes_in_a_new_container(crig, graph):  # noqa: F811
    open_net_problem(graph, "p1", [(crig.target({"value": "v"}), "r0")])
    lid = lease_bootstrap(graph)
    crig.script_for(
        "bootstrap",
        [{"tool": "Write", "input": {"file_path": "note.txt", "content": "第一轮"}}, {"hang": 120}],
        resume_steps=[
            {"tool": "Read", "input": {"file_path": "note.txt"}},
            {"tool": SUBMIT, "input": {"ops": [], "final": {"outcome": "unsolved"}}},
        ],
    )
    t, box = crig.start(lid)
    crig.wait_model(lid)
    deadline = time.monotonic() + 30
    while not (crig.tmp / "sessions" / lid / "workspace" / "note.txt").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    crig.runner.soft_line(lid)  # SIGINT 送进容器：假 CLI 以 130 结束当前回合
    t.join(60)
    rec = box["rec"]
    assert rec.rounds == 2 and rec.exit_codes == [130, 0], rec.exit_codes
    assert rec.status == "released" and rec.release["outcome"] == "nothing"
    resumed = [e for e in rec.events if e["round"] == 2 and e["type"] == "user"]
    assert "第一轮" in resumed[0]["message"]["content"][0]["content"]  # 第二个容器接着用同一个工作区
    assert leftovers() == []


@needs_docker
def test_kill_stops_the_container_not_just_the_client(crig, graph):  # noqa: F811
    open_net_problem(graph, "p1", [(crig.target({"value": "v"}), "r0")])
    lid = lease_bootstrap(graph)
    crig.script_for("bootstrap", [{"hang": 600}])
    t, box = crig.start(lid)
    name = crig.wait_model(lid)
    t0 = time.monotonic()
    crig.runner.kill(lid, "budget")
    t.join(30)
    assert not t.is_alive() and time.monotonic() - t0 < 20
    assert docker("inspect", name).returncode != 0  # 容器没了，不是只杀了宿主上的 docker 客户端
    assert box["rec"].status == "killed(budget)" and box["rec"].release["outcome"] == "budget_exhausted"
    assert leftovers() == []


@needs_docker
def test_launch_failure_leaves_nothing_behind(tmp_path, upstream):  # noqa: F811
    launcher = ContainerLauncher(IMAGE, 1, 1, relay_image="no-such-image-paoding:0")
    try:
        ws = tmp_path / "l_9" / "workspace"
        ws.mkdir(parents=True)
        with pytest.raises(Exception):  # noqa: B017  起不来就行，不约束异常种类
            launcher(["true"], {}, ws)
        assert leftovers() == []
    finally:
        launcher.close()


def test_container_proc_is_popen_shaped():
    p = ContainerProc("pd-none", subprocess.Popen(["true"], stdout=subprocess.PIPE))
    assert p.wait(5) == 0 and p.poll() == 0 and p.stdout.read() == b""


@needs_docker
def test_orphans_of_a_dead_adapter_are_swept(tmp_path):
    """Adapter 进程异常退出后留下的中继与网络：带着与执行层相同的属主标签，哮天犬的孤儿清扫收得走。"""
    from paoding_executor.contract import sweep_orphans

    launcher = ContainerLauncher(IMAGE, 1, 1)
    try:
        launcher.owner = f"{socket.gethostname()}:999999:1"  # 一个不存在的进程
        launcher._ensure("l_55")
        assert leftovers() == ["pd-model-l-55-ep", "pd-model-l-55-net"]
        assert "pd-model-l-55-ep" in sweep_orphans()
        assert leftovers() == []
    finally:
        launcher.close()
