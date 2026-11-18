"""干跑两种模式（规格 §8）。

baseline（单 CLI 直连）：假 CLI + 假上游，进程内，不需要 Docker。证明直连模式能起会话、经端点代理计量、
本地判定、写记录。
full（全栈流程）：起 scripts/run.py 的整套系统跑内建 6×7 题到 solved（与 test-e2e.sh 同一条已验证路径），需要 Docker。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from paoding_eval.__main__ import main as cli_main
from paoding_eval.record import Record, run_dirname, stamp
from paoding_eval.runner import run_baseline, run_full
from paoding_eval.spec import DRYRUN, load, sha256_hex

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "scripts" / "e2e"
FIELDS = {"mode", "problem", "run", "model", "duration_s", "terminal", "cost_usd", "events", "log_dir"}


def docker_ok() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


# ---------- 记录与规格 ----------


def test_record_schema_and_rounding(tmp_path):
    rec = Record("baseline", "q1", 1, "deepseek-chat", 1.23456, "solved", 0.0114999, 7, "runs/x/")
    d = rec.as_dict()
    assert set(d) == FIELDS
    assert d["duration_s"] == 1.23 and d["cost_usd"] == 0.0115
    assert json.loads(rec.write(tmp_path).read_text(encoding="utf-8")) == d


def test_record_rejects_bad_enums():
    with pytest.raises(ValueError):
        Record("b1", "q1", 1, "m", 1.0, "solved", 0.0, 1, "d")
    with pytest.raises(ValueError):
        Record("full", "q1", 1, "m", 1.0, "won", 0.0, 1, "d")


def test_run_dirname_and_stamp():
    assert re.fullmatch(r"\d{8}T\d{6}Z", stamp())
    assert run_dirname("full", "q1", 2, "20261118T100000Z") == "20261118T100000Z-full-q1-2"


def test_spec_open_ops_and_expect():
    ops = DRYRUN.open_ops()
    assert [o["op"] for o in ops] == ["register_artifact", "open_problem"]
    assert ops[1]["body"]["goal"]["check"] == {"judge_id": "exact_match", "expect": {"sha256": sha256_hex("42")}}
    assert ops[1]["body"]["origin"]["statement_ref"] == "$0"


def test_spec_load_roundtrip(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text("id: qx\ntitle: T\nstatement: S\nanswer: A\njudges: [exact_match]\n", encoding="utf-8")
    spec = load(p)
    assert spec.id == "qx" and spec.answer == "A" and spec.judges == ["exact_match"]


def test_spec_load_rejects_unknown_field(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text("id: q\ntitle: T\nstatement: S\nanswer: A\nbogus: 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load(p)


def test_template_manifest_loads():
    spec = load(ROOT / "eval" / "problems.d" / "TEMPLATE.yaml")
    assert spec.scope[0]["resource"] == "net" and spec.judges == ["exact_match", "replay"]


# ---------- baseline（无 Docker） ----------


def test_baseline_dryrun_solves_and_meters(tmp_path):
    out = tmp_path / "runs"
    rec = run_baseline(DRYRUN, 1, out_root=out)
    assert rec.mode == "baseline" and rec.terminal == "solved"
    assert rec.cost_usd > 0, "红线 5：直连模式也经端点代理计量，花费应为正"
    assert rec.events >= 1
    assert re.fullmatch(r"runs/\d{8}T\d{6}Z-baseline-dry-compute-1/", rec.log_dir)
    run_dir = tmp_path / rec.log_dir
    on_disk = json.loads((run_dir / "record.json").read_text(encoding="utf-8"))
    assert set(on_disk) == FIELDS and on_disk["terminal"] == "solved"
    assert (run_dir / "cli.stream-json").exists()


def test_baseline_dryrun_unsolved_when_answer_mismatches(tmp_path):
    # 假 CLI 写进一个与判据不符的值 → exact_match 不符 → unsolved（仍计量、仍正常跑完）
    rec = run_baseline(
        DRYRUN,
        1,
        out_root=tmp_path / "runs",
        fake_steps=[{"tool": "Write", "input": {"file_path": "answer.txt", "content": "41"}}],
    )
    assert rec.terminal == "unsolved"
    assert rec.cost_usd > 0


def test_baseline_dryrun_failed_when_cli_errors(tmp_path):
    rec = run_baseline(DRYRUN, 1, out_root=tmp_path / "runs", fake_steps=[{"exit": 1}])
    assert rec.terminal == "failed"


def test_cli_baseline_dryrun_prints_record(tmp_path, capsys):
    assert cli_main(["baseline", "--dryrun", "--out", str(tmp_path / "runs")]) == 0
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert set(printed) == FIELDS and printed["mode"] == "baseline" and printed["terminal"] == "solved"


def test_cli_full_needs_config(tmp_path):
    assert cli_main(["full", "--dryrun", "--out", str(tmp_path / "runs")]) == 2


# ---------- full（需 Docker） ----------


@pytest.mark.skipif(not docker_ok(), reason="需要 Docker（全栈 + 重放容器）")
def test_full_dryrun_solves_fullstack(tmp_path):
    config = {
        "backend": {
            "kind": "fake",
            "scripts": {
                "bootstrap": str(E2E / "bootstrap.json"),
                "reason": str(E2E / "reason.json"),
                "explore": str(E2E / "explore.json"),
            },
        },
        "executor": {"kind": "docker", "bases": {"basic": "python:3.12-slim"}},
        "poll_s": 0.2,
        "dog_interval_s": 0.5,
    }
    rec = run_full(DRYRUN, 1, out_root=tmp_path / "runs", config=config, timeout_s=180)
    assert rec.mode == "full" and rec.terminal == "solved", rec.as_dict()
    assert rec.events > 0 and rec.cost_usd > 0
    assert re.fullmatch(r"runs/\d{8}T\d{6}Z-full-dry-compute-1/", rec.log_dir)
    assert (tmp_path / rec.log_dir / "events.json").exists()
