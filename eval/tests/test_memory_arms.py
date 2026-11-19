"""能力一的开关矩阵（04-proof-plan）：memory=off / memory=recall / recall_noverify 各一条端到端。

复做题组的最小形态：A 题先跑并关题（Bootstrap 写一条带对照的观察，同一会话交答案，薄路径解出），
通鉴封存判例、投影出环境事实；B 题与 A 同环境键，在同一数据目录里按开关开题。全栈、真判官（Docker 重放）、假 CLI。
"""

import dataclasses
import json
from pathlib import Path

import pytest
from paoding_eval.runner import run_full
from paoding_eval.spec import DRYRUN
from test_dryrun import docker_ok

SCRIPT = Path(__file__).parent / "memory" / "bootstrap.json"
CONFIG = {
    "backend": {"kind": "fake", "scripts": {"bootstrap": str(SCRIPT)}},
    "executor": {"kind": "docker", "bases": {"basic": "python:3.12-slim"}},
    "poll_s": 0.2,
    "dog_interval_s": 0.5,
    "memory": {"case_seal": True, "model_epoch": "fake-1"},
}

pytestmark = pytest.mark.skipif(not docker_ok(), reason="需要 Docker（全栈 + 重放容器）")


def pair(tmp_path: Path, memory: str):
    home = tmp_path / "home"
    out = tmp_path / "runs"
    a = run_full(dataclasses.replace(DRYRUN, id="redo-a"), 1, out_root=out, config=CONFIG, home=home, timeout_s=180)
    assert a.terminal == "solved", a.as_dict()
    b = run_full(
        dataclasses.replace(DRYRUN, id="redo-b"),
        1,
        out_root=out,
        config=CONFIG,
        home=home,
        memory=memory,
        timeout_s=180,
    )
    assert b.terminal == "solved", b.as_dict()
    run = tmp_path / b.log_dir
    events = json.loads((run / "events.json").read_text(encoding="utf-8"))
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    return events, meta


def recalled(events):
    return [e for e in events if e["kind"] == "add_fact" and e["body"]["title"].startswith("[忆] ")]


def test_memory_off_opens_cold(tmp_path):
    events, meta = pair(tmp_path, "off")
    assert meta["switches"] == {"memory": "off", "recall_noverify": False, "case_seal": True}
    assert "recall" not in events[1]["body"] and recalled(events) == []
    assert not any(e["kind"] == "lease" and e["body"]["kind"] == "recall" for e in events)


def test_memory_recall_verifies_before_bootstrap(tmp_path):
    events, meta = pair(tmp_path, "recall")
    assert meta["switches"]["memory"] == "recall" and meta["recall"]["facts"] == 1
    opener = next(e for e in events if e["kind"] == "open_problem")
    assert [i["title"] for i in opener["body"]["recall"]["items"]] == ["执行环境可用"]
    [fact] = recalled(events)
    fid = f"f_{fact['seq']}"
    verdicts = [e for e in events if e["kind"] == "judge_verdict"]
    reqs = {f"j_{e['seq']}": e["body"]["target"] for e in events if e["kind"] == "request_judge"}
    mine = [v for v in verdicts if reqs[v["body"]["request"]] == fid]
    assert mine and mine[0]["body"]["result"] == "pass" and mine[0]["body"]["control_end"] == "fail"  # 本题判官重跑
    kinds = [e["body"]["kind"] for e in events if e["kind"] == "lease"]
    assert kinds.index("recall") < kinds.index("bootstrap")


def test_recall_noverify_only_narrates(tmp_path):
    events, meta = pair(tmp_path, "noverify")
    assert meta["switches"] == {"memory": "noverify", "recall_noverify": True, "case_seal": True}
    opener = next(e for e in events if e["kind"] == "open_problem")
    rec = opener["body"]["recall"]
    assert rec["mode"] == "noverify" and rec["items"] == []
    assert [n["title"] for n in rec["notes"] if n["kind"] == "env_fact"] == ["执行环境可用"]
    assert recalled(events) == []
