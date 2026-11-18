"""审计 P0-2（组装根一侧）：会话后端在模型容器里起 CLI。

- 假 CLI + `"launcher": "container"`：整套系统走完一道题，三个会话的 CLI 都跑在模型容器里（同一条容器路径，
  不调真模型、不用真密钥）；
- `backend.kind == "real"`：缺省就是模型容器启动器；真实密钥从环境变量读、只交给端点代理。这里只验接线，
  不起任何会话。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "scripts" / "e2e"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(E2E))

from drive import open_problem, wait_terminal  # noqa: E402
from stack import Stack, StackConfig, StackError, docker_available  # noqa: E402

from paoding_adapter.contract import ContainerLauncher, local_launcher  # noqa: E402

IMAGE = "python:3.12-slim"
PID = "e2e"


def docker_ok() -> bool:
    return docker_available() and subprocess.run(["docker", "image", "inspect", IMAGE],
                                                 capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")


def write_config(tmp_path: Path, backend: dict, **top) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"backend": backend, "executor": {"kind": "docker", "bases": {"basic": IMAGE}},
                             "poll_s": 0.2, "dog_interval_s": 0.5, **top}))
    return p


def model_leftovers() -> list[str]:
    names = subprocess.run(["docker", "ps", "-a", "--filter", "name=pd-model-", "--format", "{{.Names}}"],
                           capture_output=True).stdout.decode().split()
    nets = subprocess.run(["docker", "network", "ls", "--filter", "name=pd-model-", "--format", "{{.Name}}"],
                          capture_output=True).stdout.decode().split()
    return sorted(names + nets)


def test_full_stack_with_sessions_in_model_containers(tmp_path):
    home = tmp_path / "home"
    cfg = write_config(tmp_path, {"kind": "fake", "launcher": "container", "scripts": {
        k: str(E2E / f"{k}.json") for k in ("bootstrap", "reason", "explore")}})
    stack = Stack(StackConfig.load(home, cfg, port=0, static_dir=None))
    assert isinstance(stack.runner.launcher, ContainerLauncher)
    url = stack.start()
    try:
        token = (home / "human.token").read_text().strip()
        assert open_problem(url, token, PID)["ok"]
        st = wait_terminal(url, PID, 90)
        assert st["problem"].get("closed") and st["problem"]["terminal"] == "solved", st["problem"]
        g = stack.graph
        sessions = [l for l in g.state["leases"].values() if l["kind"] != "judge"]
        assert [l["kind"] for l in sessions] == ["bootstrap", "reason", "explore"]
        seen = []
        for l in sessions:
            # 会话记录里 CLI 自报的工作目录是容器里的 /workspace，不是宿主上的会话目录。
            # 最后一个会话（explore）的记录可能赶不上登记：判官先把题关了，关题后内核不收登记。
            tr = next((a for a in g.state["artifacts"].values()
                       if a.get("media_type") == "application/vnd.paoding.session-record+json"
                       and a["producer"].get("session") == l["id"]), None)
            if tr is None:
                assert l["kind"] == "explore", l
                continue
            rec = json.loads(stack.blobs.get(tr["hash"]))
            init = next(e for e in rec["events"] if e.get("subtype") == "init")
            assert init["cwd"] == "/workspace" and rec["exit_codes"] == [0], (l["id"], init, rec["exit_codes"])
            assert rec["proxy"]["requests"] > 0 and rec["proxy"]["usd_milli"] > 0
            seen.append(l["kind"])
        assert seen[:2] == ["bootstrap", "reason"]
        # explore 也在容器里跑过：它的花费记在账上，候选是它写进共享工作区的文件
        explore = sessions[2]
        assert sum(c["usd_milli"] for c in g.state["costs"] if c["task_id"] == explore["id"]) > 0
    finally:
        stack.stop()
    assert model_leftovers() == []


def test_real_backend_defaults_to_the_container_launcher(tmp_path, monkeypatch):
    """只验接线：不起会话、不连任何模型端点。密钥是一串假字符，只该出现在端点代理的配置里。"""
    key = "sk-test-not-a-real-key"
    monkeypatch.setenv("PD_TEST_MODEL_KEY", key)
    cfg = write_config(tmp_path, {"kind": "real", "image": "example/cli:0", "upstream": "https://model.invalid",
                                  "api_key_env": "PD_TEST_MODEL_KEY"})
    stack = Stack(StackConfig.load(tmp_path / "home", cfg, port=0, static_dir=None))
    try:
        launcher = stack.runner.launcher
        assert isinstance(launcher, ContainerLauncher) and launcher.image == "example/cli:0"
        assert launcher.mounts == ()                                   # 真 CLI 的镜像自带 CLI，不挂假 CLI
        assert stack.adapter_cfg.binding.program == ["claude"]
        assert stack.proxy.cfg.upstream == "https://model.invalid" and stack.proxy.cfg.api_key == key
        assert stack.upstream is None                                  # 不起假上游
        # 容器里看到的端点是中继，环境变量里是任务令牌：命令行里没有真实密钥
        from paoding_adapter import backend as be
        plan = be.LaunchPlan("l_1", tmp_path / "s" / "workspace", tmp_path / "s" / "system.md", "u",
                             tmp_path / "s" / "mcp.json", proxy_url=launcher.proxy_url, task_token="pdt-x")
        argv, env = stack.adapter_cfg.binding.command(plan)
        assert env["ANTHROPIC_BASE_URL"] == "http://pd-endpoints:8081" and env["ANTHROPIC_API_KEY"] == "pdt-x"
        assert key not in json.dumps([argv, env]) and key not in (tmp_path / "config.yaml").read_text()
    finally:
        stack.stop()


def test_real_backend_refuses_to_start_without_key_or_image(tmp_path, monkeypatch):
    monkeypatch.delenv("PD_TEST_MODEL_KEY", raising=False)
    cfg = write_config(tmp_path, {"kind": "real", "image": "example/cli:0", "api_key_env": "PD_TEST_MODEL_KEY"})
    with pytest.raises(StackError, match="PD_TEST_MODEL_KEY"):
        Stack(StackConfig.load(tmp_path / "home", cfg, port=0, static_dir=None))
    monkeypatch.setenv("PD_TEST_MODEL_KEY", "sk-test-not-a-real-key")
    cfg = write_config(tmp_path, {"kind": "real", "api_key_env": "PD_TEST_MODEL_KEY"})
    with pytest.raises(StackError, match="backend.image"):
        Stack(StackConfig.load(tmp_path / "home", cfg, port=0, static_dir=None))


def test_fake_backend_still_defaults_to_host_subprocess(tmp_path):
    cfg = write_config(tmp_path, {"kind": "fake", "scripts": {}})
    stack = Stack(StackConfig.load(tmp_path / "home", cfg, port=0, static_dir=None))
    try:
        assert stack.runner.launcher is local_launcher
    finally:
        stack.stop()
