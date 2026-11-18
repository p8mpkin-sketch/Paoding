"""瘦基线的 Bk（等成本独立重试）与 Bn（共享笔记）两臂（arms.py，规格 A2）。

用假 CLI 与假上游干跑；两条走沙箱的用例证明两臂与 baseline 面对同一套执行层网络。假上游每次请求计 0.005 美元。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from paoding_eval.__main__ import main as cli_main
from paoding_eval.arms import NOTES, merge_notes, run_arm
from paoding_eval.record import Record
from paoding_eval.spec import DRYRUN

IMAGE = "python:3.12-slim"
WRONG = [{"tool": "Write", "input": {"file_path": "answer.txt", "content": "41"}}]
RIGHT = [{"tool": "Write", "input": {"file_path": "answer.txt", "content": DRYRUN.answer}}]


def docker_ok() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


needs_docker = pytest.mark.skipif(not docker_ok(), reason="需要 Docker（瘦基线沙箱）")


def meta(tmp: Path, rec: Record) -> dict:
    return json.loads((tmp / rec.log_dir / "meta.json").read_text())


def test_modes_in_record_schema() -> None:
    for m in ("bk", "bn"):
        Record(m, "p", 1, "x", 1.0, "solved", 0.0, 0, "runs/x/")


def test_bk_stops_at_equal_cost_budget(tmp_path: Path) -> None:
    """预算 0.012 美元、每次 0.005：第三次开跑时还剩 0.002，跑完即到额，不再开第四次。"""
    rec = run_arm("bk", DRYRUN, 1, out_root=tmp_path / "runs", rounds=20, budget_usd=0.012, fake_steps=WRONG)
    m = meta(tmp_path, rec)
    assert rec.terminal == "unsolved" and len(m["attempts"]) == 3
    assert m["arm"]["stopped_by"] == "budget" and rec.cost_usd == pytest.approx(0.015)
    assert rec.cost_usd <= 0.012 + 0.005  # 至多越过一次请求


def test_bk_needs_budget_or_rounds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--budget-usd"):
        run_arm("bk", DRYRUN, 1, out_root=tmp_path / "runs")
    assert cli_main(["bk", "--dryrun", "--out", str(tmp_path)]) == 2


def test_bk_attempts_are_independent(tmp_path: Path) -> None:
    """每次尝试一个新工作区：前一次留下的文件，后一次看不到。"""
    steps = {
        1: [{"tool": "Write", "input": {"file_path": "left.txt", "content": "x"}}, *WRONG],
        2: [{"tool": "Read", "input": {"file_path": "left.txt"}}, *RIGHT],
    }
    rec = run_arm("bk", DRYRUN, 1, out_root=tmp_path / "runs", rounds=5, fake_steps=lambda r, w: steps[r])
    m = meta(tmp_path, rec)
    assert rec.terminal == "solved" and [a["terminal"] for a in m["attempts"]] == ["unsolved", "solved"]
    assert m["arm"]["stopped_by"] == "solved" and rec.events == 4  # 两次尝试各 2 个回合
    second = (tmp_path / rec.log_dir / "r2-w1" / "cli.stream-json").read_text()
    assert "File does not exist" in second


def test_merge_notes_append_only() -> None:
    shared = "## w1 · 第 1 轮\n\nA\n"
    out, rewrote = merge_notes(shared, [(1, shared + "B\n"), (2, "改写\n"), (3, None), (4, shared)], 2)
    assert out.startswith(shared) and "## w1 · 第 2 轮\n\nB" in out
    assert rewrote == [2] and "改写" not in out and "w4" not in out


def test_bn_cli_dryrun(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["bn", "--dryrun", "--rounds", "2", "--workers", "2", "--out", str(tmp_path)]) == 0
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rec["mode"] == "bn" and rec["terminal"] == "solved" and rec["events"] == 2


@needs_docker
def test_bn_shares_notes_across_workers_and_rounds_in_sandbox(tmp_path: Path) -> None:
    """第 1 轮两个 Worker 各追加一条发现；第 2 轮 w1 读到 w2 的发现才写对答案，w2 改写笔记被整份丢弃。"""

    def steps(r: int, w: int) -> list[dict]:
        if r == 1:
            return [{"tool": "Bash", "input": {"command": f"echo 'w{w} 发现 k{w}' >> {NOTES}"}}, *WRONG]
        if w == 1:
            cmd = f"grep -q 'w2 发现 k2' {NOTES} && printf {DRYRUN.answer} > answer.txt"
            return [{"tool": "Bash", "input": {"command": cmd}}]
        return [{"tool": "Bash", "input": {"command": f"echo 改写 > {NOTES}"}}, *WRONG]

    rec = run_arm("bn", DRYRUN, 1, out_root=tmp_path / "runs", workers=2, rounds=3, fake_steps=steps, image=IMAGE)
    m = meta(tmp_path, rec)
    assert rec.terminal == "solved" and m["arm"]["stopped_by"] == "solved" and len(m["attempts"]) == 4
    assert m["sandbox"] is True and m["notes"]["rewrites_dropped"] == [[2, 2]]
    notes = (tmp_path / rec.log_dir / NOTES).read_text()
    assert "## w1 · 第 1 轮" in notes and "w2 发现 k2" in notes and "改写" not in notes
    seeded = (tmp_path / rec.log_dir / "r2-w1" / "workspace" / NOTES).read_text()
    assert "w1 发现 k1" in seeded and "w2 发现 k2" in seeded  # 第 2 轮开始时拷进去的是合并后的笔记


@needs_docker
def test_bk_runs_each_attempt_in_its_own_sandbox(tmp_path: Path) -> None:
    rec = run_arm(
        "bk",
        DRYRUN,
        1,
        out_root=tmp_path / "runs",
        rounds=3,
        fake_steps=lambda r, w: RIGHT if r == 2 else WRONG,
        image=IMAGE,
    )
    m = meta(tmp_path, rec)
    assert rec.terminal == "solved" and len(m["attempts"]) == 2 and m["sandbox"] is True
    assert rec.cost_usd == pytest.approx(0.01)  # 两次尝试都经沙箱里的中继计量
    left = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    assert "pd-eval-" not in left
