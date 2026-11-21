"""进化读数的读端（GET /v1/evolution，paoding_fenjue.evolution）：品阶史、炼档结局统计、常设留出两臂。"""

from __future__ import annotations

import json
from pathlib import Path

from paoding_fenjue import shapes
from paoding_fenjue.readings import evolution

ROOT = Path(__file__).resolve().parents[2]
D001 = json.loads((ROOT / "docs/design/fenjue/dossiers/001-replayable-live.json").read_text(encoding="utf-8"))
OLD = "9770a71f87236df2e29e320e75b1c9a6c3bc2ef64d449fb54954dd25a390ace9"  # #125 之前：没有常设留出


def task(pid: str, stamp: str | None, terminal: str | None = "delivered", spent: int = 100, wall: int = 60):
    p = {"id": pid, **({"gongfa": {"jie": 2, "digest": stamp}} if stamp else {})}
    row = {"id": pid, "closed": terminal is not None, "terminal": terminal, "spent_usd_milli": spent,
           "wall": {"elapsed_s": wall}}  # fmt: skip
    return p, row


def run(tasks, dossiers=(D001,)):
    return evolution(list(dossiers), {p["id"]: p for p, _ in tasks}, [r for _, r in tasks])


def split(n: int) -> tuple[list[str], list[str]]:
    v = shapes.current()
    ids = [f"t{i}" for i in range(n)]
    return [i for i in ids if not v.in_holdout(i, "H6")], [i for i in ids if v.in_holdout(i, "H6")]


def test_history_and_outcome_tally():
    out = run([])
    assert out["current"]["jie"] == 2 and out["current"]["holdout_permille"] == 100
    assert [h["jie"] for h in out["history"]] == [0, 1, 2] and out["history"][2]["dossier"] == "001"
    assert out["outcomes"] == {
        "huolian": 1,
        "helian": 0,
        "binghuo": 0,
        "fanshi": 0,
        "decided": 1,
        "pending": 0,
        "reverted": 0,
    }
    [d] = out["dossiers"]
    assert d["fire"] == "h6.activity-ledger@1" and d["replaces"] == ["h6.activity"]
    assert d["verdict"]["outcome"] == "huolian" and d["verdict"]["jie"] == 2 and d["readings"]


def test_undecided_and_reverted_dossiers_are_counted_apart():
    draft = {**D001, "dossier": "002", "name": "x", "status": "readings_ready", "verdict": None}
    gone = {**D001, "dossier": "003", "name": "y", "status": "reverted", "reverts": [{"by": "cz", "why": "w"}]}
    t = run([], [D001, draft, gone])["outcomes"]
    assert (t["huolian"], t["decided"], t["pending"], t["reverted"]) == (2, 2, 1, 1)


def test_holdout_arms_follow_the_version_each_task_was_opened_under():
    main, held = split(80)
    assert main and held  # 10% 留出：八十道题里两边都有
    live = shapes.gongfa()["digest"]
    tasks = [task(i, live, "delivered") for i in main] + [task(i, live, "unsolved", spent=50) for i in held]
    tasks += [task("old1", OLD), task("pre1", None)]  # 没有留出的那一版、焚决之前：不进任何一臂
    [h] = run(tasks)["holdout"]
    assert (h["slot"], h["holdout"], h["active"], h["dossier"], h["live"]) == (
        "H6",
        "h6.activity@1",
        "h6.activity-ledger@1",
        "001",
        True,
    )
    assert h["main"]["tasks"] == len(main) and h["main"]["done_rate"] == 1.0
    assert h["held"]["tasks"] == len(held) and h["held"]["done_rate"] == 0.0 and h["held"]["avg_spent_usd_milli"] == 50
    assert h["retire_signal"]


def test_tasks_are_grouped_by_the_version_they_were_opened_under():
    live = shapes.gongfa()["digest"]
    out = run([task("a", live), task("b", live, None), task("c", OLD), task("d", None, "unsolved")])
    vs = {(v["jie"], v["digest"]): v for v in out["versions"]}
    assert vs[(2, live)]["tasks"] == 2 and vs[(2, live)]["open"] == 1 and vs[(2, live)]["current"]
    assert vs[(2, OLD)]["done"] == 1 and not vs[(2, OLD)]["current"]
    assert vs[(0, None)]["done_rate"] == 0.0


def test_a_live_holdout_is_listed_before_any_task_lands_in_it():
    [h] = run([])["holdout"]
    assert h["main"]["tasks"] == 0 and h["held"]["done_rate"] is None


def test_repinned_tasks_get_their_own_row_and_stay_out_of_both_arms():
    """体质修炼 003：改钉过的题前后用了两版，版本表里单列一行（按改钉到的那一版），不进常设留出的任何一臂。"""
    main, held = split(40)
    live = shapes.gongfa()["digest"]
    moved = [task(i, live) for i in main[:2]] + [task(i, live) for i in held[:1]]
    for p, _ in moved:
        p["repins"] = [{"seq": 5, "ts": 0, "to": {"jie": 2, "digest": OLD}, "reason": "r"}]
    out = run([task("a", live), *moved])
    rows = {(v["jie"], v["digest"], v["repinned"]): v for v in out["versions"]}
    assert rows[(2, live, False)]["tasks"] == 1 and rows[(2, live, False)]["current"]
    assert rows[(2, OLD, True)]["tasks"] == 3 and not rows[(2, OLD, True)]["current"]
    [h] = out["holdout"]
    assert h["main"]["tasks"] + h["held"]["tasks"] == 1  # 只有没改钉的 a
    assert {(r["jie"], r["digest"]) for r in out["archive"]} >= {(2, OLD), (2, live)}
    assert [r["digest"] for r in out["archive"] if r["current"]] == [live]
