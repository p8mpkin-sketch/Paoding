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
from paoding_eval.arms import NOTES, bn_width, merge_notes, round_width, run_arm
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
    """预算 0.012 美元、每次 0.005：两次后剩 0.002，不够再开一次（按至今单次请求的最高花费估），不越过预算。"""
    rec = run_arm("bk", DRYRUN, 1, out_root=tmp_path / "runs", rounds=20, budget_usd=0.012, fake_steps=WRONG)
    m = meta(tmp_path, rec)
    assert rec.terminal == "unsolved" and len(m["attempts"]) == 2
    assert m["arm"]["stopped_by"] == "budget" and rec.cost_usd == pytest.approx(0.010)
    assert m["arm"]["over_budget_milli"] == 0


def test_round_width_never_over_allocates() -> None:
    """各尝试的预留之和不超过剩余；不够分就收窄，一个都不够就停。没有向上兜底。"""
    assert round_width(3, None, 0, 0, 999) == (3, 999)  # 没有预算：照开
    assert round_width(3, 16, 0, 0, 999) == (3, 5)  # 还没有请求：按 1 毫美元估
    assert round_width(3, 16, 6, 4, 999) == (2, 5)  # 剩 10、单次 4：只够开 2 个
    assert round_width(3, 16, 13, 4, 999) == (0, 0)  # 剩 3 < 单次 4：停
    assert round_width(3, 16, 16, 0, 999) == (0, 0)
    for workers, budget, spent, unit in [(3, 16, 0, 0), (3, 16, 5, 6), (4, 100, 37, 9), (2, 7, 6, 1)]:
        w, r = round_width(workers, budget, spent, unit, 0)
        assert w * r <= budget - spent


def test_bn_cap_is_shared_across_workers(tmp_path: Path) -> None:
    """预算 0.016、三个 Worker、每次 0.005：第一轮还不知道单次多贵，三个都开；第二轮剩 0.001，停。
    全臂共用代理的题目硬顶，越过预算的只有第一轮同时在途的请求，并记进 meta。"""
    rec = run_arm("bn", DRYRUN, 1, out_root=tmp_path / "runs", workers=3, rounds=5, budget_usd=0.016, fake_steps=WRONG)
    m = meta(tmp_path, rec)
    assert m["arm"]["widths"] == [3] and m["arm"]["stopped_by"] == "budget"
    assert rec.cost_usd == pytest.approx(0.015) and m["arm"]["over_budget_milli"] == 0


def test_bn_narrows_round_when_budget_cannot_cover_workers(tmp_path: Path) -> None:
    rec = run_arm("bn", DRYRUN, 1, out_root=tmp_path / "runs", workers=3, rounds=5, budget_usd=0.026, fake_steps=WRONG)
    m = meta(tmp_path, rec)
    assert m["arm"]["widths"] == [3, 2] and rec.cost_usd == pytest.approx(0.025)
    assert m["arm"]["over_budget_milli"] == 0


def test_bn_width_rule_c() -> None:
    """等成本口径 C：W = max(1, ⌊C_full ÷ 单次尝试成本⌋)，不超过 --workers。"""
    assert bn_width(0.016, 0.011, 3) == 1  # q1 的量级：付不起两次完整尝试，退化成单线程
    assert bn_width(0.3, 0.1, 5) == 3  # 浮点下 0.3 / 0.1 = 2.9999…，按毫美元整数算才对
    assert bn_width(0.5, 0.011, 3) == 3  # 不超过上限
    assert bn_width(0.005, 0.011, 3) == 1  # 一次都付不起也开 1 个，由代理的硬顶兜住
    with pytest.raises(ValueError):
        bn_width(0.016, 0, 3)


def test_bn_width_from_baseline_unit_cost(tmp_path: Path) -> None:
    """预算 0.016、单次 0.011：宽度 1，逐轮单线程跑到预算；与不给单次成本时第一轮拆成 3 份对照。"""
    rec = run_arm(
        "bn",
        DRYRUN,
        1,
        out_root=tmp_path / "runs",
        workers=3,
        rounds=5,
        budget_usd=0.016,
        unit_usd=0.011,
        fake_steps=WRONG,
    )
    m = meta(tmp_path, rec)
    assert m["arm"]["workers"] == 1 and m["arm"]["unit_usd"] == 0.011
    assert m["arm"]["widths"] == [1, 1, 1] and rec.cost_usd == pytest.approx(0.015)


def test_real_bn_needs_baseline_unit_cost(tmp_path: Path) -> None:
    """真题 bn 有预算就要单次成本：同一题必须先跑 baseline。"""
    with pytest.raises(ValueError, match="--unit-usd"):
        run_arm("bn", DRYRUN, 1, out_root=tmp_path, budget_usd=0.016, real_program=["claude"], image="img")


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


def test_overshoot_bound_is_requests_in_flight(tmp_path: Path) -> None:
    """已知的界：代理在请求前放行、响应后计费，所以越过预算的只能是预算被越过那一刻同时在途的请求。
    第一轮还不知道单次多贵：预算 0.012、三个 Worker 各预留 0.004，三个请求同时放行，各花 0.005，越过 0.003。
    界 = 在途请求数 × 单次最高花费；Bk 每轮只有一个尝试，界就是一次请求。"""
    rec = run_arm("bn", DRYRUN, 1, out_root=tmp_path / "runs", workers=3, rounds=5, budget_usd=0.012, fake_steps=WRONG)
    m = meta(tmp_path, rec)
    assert m["arm"]["widths"] == [3] and m["arm"]["over_budget_milli"] == 3
    assert m["arm"]["over_budget_milli"] <= m["arm"]["widths"][0] * 5
