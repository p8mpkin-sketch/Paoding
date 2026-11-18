"""baseline 与 full 环境对等（box.py）：CLI 在执行层同款沙箱里跑，经闸门只连得到授权目标。

M1 第一批读数里 baseline 三次全败，原因是 CLI 在宿主上跑、解析不了题目容器的名字。这里用假 CLI 的 Bash
步骤在沙箱里真的去连一个题目容器：授权端口能连上并解出，授权外的端口与外网连不上，计量仍经端点代理。
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from paoding_eval.readings import collect_records, manifest_digest
from paoding_eval.runner import run_baseline
from paoding_eval.spec import DRYRUN, ProblemSpec

IMAGE = "python:3.12-slim"
ANSWER = "s3cret-41"
# 题目容器：8000 是授权端口，8001 同一台主机但不在 scope 里
SERVER = (
    "import http.server,threading\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    f"        b=b'{ANSWER}'; self.send_response(200); self.end_headers(); self.wfile.write(b)\n"
    "for p in (8000, 8001):\n"
    "    s=http.server.ThreadingHTTPServer(('0.0.0.0',p),H); threading.Thread(target=s.serve_forever).start()\n"
)


def docker_ok() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not docker_ok(), reason="需要 Docker（baseline 沙箱）")


def fetch(url: str) -> str:
    """沙箱里的一条 Bash：取 url 的内容；连不上就输出 blocked。"""
    py = (
        "import urllib.request\n"
        "try:\n"
        f"    print(urllib.request.urlopen('{url}', timeout=3).read().decode())\n"
        "except Exception:\n"
        "    print('blocked')\n"
    )
    return f"python -c {shlex.quote(py)}"


@pytest.fixture
def target() -> Iterator[str]:
    name = f"pd-evaltgt-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--name", name, IMAGE, "python", "-c", SERVER], check=True, capture_output=True
    )
    for _ in range(100):  # 等两个端口都开始监听
        probe = "import socket;[socket.create_connection(('127.0.0.1',p),1).close() for p in (8000,8001)]"
        if subprocess.run(["docker", "exec", name, "python", "-c", probe], capture_output=True).returncode == 0:
            break
    yield name
    subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)


def spec_for(target: str) -> ProblemSpec:
    return ProblemSpec(
        id="boxq",
        title="沙箱题",
        statement=f"答案在 http://{target}:8000/ 。",
        answer=ANSWER,
        scope=[{"resource": "net", "pattern": f"{target}:8000", "actions": ["connect"], "risk": "r0"}],
    )


def leftovers(log_dir: Path) -> list[str]:
    p = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True)
    return [n for n in p.stdout.split() if n.startswith("pd-eval-")]


def test_baseline_reaches_authorized_target_and_solves(tmp_path: Path, target: str) -> None:
    spec = spec_for(target)
    steps = [{"tool": "Bash", "input": {"command": fetch(f"http://{target}:8000/a") + " > answer.txt"}}]
    rec = run_baseline(spec, 1, out_root=tmp_path / "runs", fake_steps=steps, image=IMAGE, meta={"manifest": "m"})
    assert rec.terminal == "solved"
    assert rec.cost_usd > 0  # 沙箱里的 CLI 经中继到端点代理，计量照旧（红线 5）
    log_dir = tmp_path / rec.log_dir
    meta = json.loads((log_dir / "meta.json").read_text())
    assert meta["sandbox"] is True and meta["image"] == IMAGE and "Bash" in meta["tools"]
    assert meta["target_connects"] >= 1 and meta["manifest"] == "m"
    gate = [json.loads(line) for line in (log_dir / "gate.jsonl").read_text().splitlines()]
    assert any(r["event"] == "connect" and r["ok"] and r["dst"] == f"{target}:8000" for r in gate)
    assert not leftovers(log_dir)  # 沙箱、闸门、中继与网络都拆了；题目容器还在
    assert subprocess.run(["docker", "inspect", target], capture_output=True).returncode == 0


def test_baseline_cannot_reach_beyond_scope(tmp_path: Path, target: str) -> None:
    """同一台主机的授权外端口、外网、宿主上的端点代理以外的地址，都连不上。"""
    cmd = " && ".join(
        [
            fetch(f"http://{target}:8001/") + " > answer.txt",
            fetch("http://example.com/") + " >> answer.txt",
            fetch("http://1.1.1.1/") + " >> answer.txt",
        ]
    )
    rec = run_baseline(
        spec_for(target),
        1,
        out_root=tmp_path / "runs",
        fake_steps=[{"tool": "Bash", "input": {"command": cmd}}],
        image=IMAGE,
    )
    assert rec.terminal == "unsolved"
    got = (tmp_path / rec.log_dir / "workspace" / "answer.txt").read_text().split()
    assert got == ["blocked", "blocked", "blocked"]


def test_relative_out_root(tmp_path: Path, target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """--out 缺省是相对路径 runs/：工作区要先解析成绝对路径再挂进沙箱（cz 真机验收时撞上）。"""
    monkeypatch.chdir(tmp_path)
    steps = [{"tool": "Bash", "input": {"command": fetch(f"http://{target}:8000/") + " > answer.txt"}}]
    rec = run_baseline(spec_for(target), 1, out_root=Path("runs"), fake_steps=steps, image=IMAGE)
    assert rec.terminal == "solved" and rec.log_dir.startswith("runs/")


def test_real_baseline_requires_sandbox(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--image"):
        run_baseline(DRYRUN, 1, out_root=tmp_path, real_program=["claude"], upstream_url="http://x", api_key="k")


def test_collect_records_into_repo_layout(tmp_path: Path, target: str) -> None:
    spec = spec_for(target)
    steps = [{"tool": "Bash", "input": {"command": fetch(f"http://{target}:8000/") + " > answer.txt"}}]
    for n in (1, 2):
        run_baseline(
            spec,
            n,
            out_root=tmp_path / "runs",
            fake_steps=steps,
            image=IMAGE,
            meta={"runner_commit": "abc", "manifest": manifest_digest(spec)},
        )
    rows = collect_records(tmp_path / "runs", tmp_path / "records")
    assert len(rows) == 2
    files = sorted(p.name for p in (tmp_path / "records").iterdir())
    assert files[-1] == "summary.md" and len(files) == 3
    text = "".join(p.read_text() for p in (tmp_path / "records").iterdir())
    assert ANSWER not in text  # 记录与摘要里都没有答案
    assert "| boxq | baseline | 2/2 |" in (tmp_path / "records" / "summary.md").read_text()
