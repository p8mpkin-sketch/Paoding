"""任务锁定开题时的功法版本（FJ6）：for_problem 按开题事件里的摘要取那一版功法；散火、换火只影响之后新开的题。"""

from __future__ import annotations

import hashlib
import json

import pytest

from paoding_fenjue import shapes


@pytest.fixture
def switch(tmp_path, monkeypatch):
    """把此刻的功法换成 g（组装根换功法、散火之后同一情形）。"""

    def to(g: dict) -> dict:
        p = tmp_path / "gongfa.json"
        p.write_text(json.dumps({k: v for k, v in g.items() if k != "digest"}, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setenv(shapes.GONGFA_ENV, str(p))
        shapes.gongfa.cache_clear()
        return shapes.gongfa()

    yield to
    monkeypatch.delenv(shapes.GONGFA_ENV, raising=False)
    shapes.gongfa.cache_clear()


def stamp(g: dict, pid: str = "p1") -> dict:
    return {"id": pid, "gongfa": {"jie": g["jie"], "digest": g["digest"]}}


def test_after_sanhuo_a_running_problem_keeps_its_version(switch):
    g0 = shapes.gongfa()
    running = stamp(g0)
    # 001 散火：H6 指回 h6.activity，常设留出撤掉，品阶降一阶
    after = {**g0, "fires": {**g0["fires"], "H6": ["h6.workbench@1", "h6.activity@1", "h6.pd@1"]}, "holdout": {}}
    after["history"] = [*g0["history"], {"jie": 1, "change": "散火 001", "reverts": "001"}]
    after["jie"] = 1
    g1 = switch(after)
    assert g1["digest"] != g0["digest"]
    v = shapes.for_problem(running)
    assert v.pinned and v.digest == g0["digest"]
    assert [f["id"] for f in v.active("H6")] == ["h6.workbench", "h6.activity-ledger", "h6.pd"]
    fresh = shapes.for_problem(stamp(g1, "p2"))
    assert fresh.digest == g1["digest"] and "h6.activity-ledger" not in [f["id"] for f in fresh.active("H6")]
    assert shapes.arm_of(running, "H6") == "main"


def test_the_previous_release_is_still_reachable():
    """#125 之前上线的那一版（没有常设留出）：在它下面开的题照旧没有留出。"""
    old = "9770a71f87236df2e29e320e75b1c9a6c3bc2ef64d449fb54954dd25a390ace9"
    v = shapes.for_problem({"id": "p1", "gongfa": {"jie": 2, "digest": old}})
    assert v.pinned and v.digest == old and v.holdout_permille() == 0
    assert all(not v.in_holdout(f"p{i}", "H6") for i in range(200))


def test_holdout_split_follows_the_pinned_permille(switch):
    g0 = shapes.gongfa()
    switch({**g0, "holdout_permille": 1000})  # 此刻的功法把比例拉满
    assert shapes.in_holdout("p1", "H6")
    assert not shapes.for_problem(stamp(g0)).in_holdout("p1", "H6")  # 开题时的 10%：p1 不在留出


def test_problems_without_a_known_stamp_fall_back_to_the_live_gongfa():
    live = shapes.gongfa()["digest"]
    for p in ({"id": "p1"}, {"id": "p1", "gongfa": {"jie": 9, "digest": "f" * 64}}):
        v = shapes.for_problem(p)
        assert v.digest == live and not v.pinned
    assert shapes.arm_of({"id": "p1", "gongfa": {"jie": 9, "digest": "f" * 64}}, "H6") is None


def test_prompts_come_from_the_pinned_assets():
    v = shapes.current()
    f = v.form("solve")
    text = v.asset(f["ref"], "adapter/prompts/solve.md")
    assert hashlib.sha256(text).hexdigest() == next(a["sha256"] for a in shapes.fire("h1.solo")["assets"])


def test_a_tampered_archive_is_refused(monkeypatch):
    g, read = {**shapes._gongfa_source(), "jie": 7}, shapes._read
    monkeypatch.setattr(shapes, "_read", lambda name: g if name.startswith("archive/gongfa/") else read(name))
    shapes.at.cache_clear()
    try:
        with pytest.raises(ValueError, match="存档被改过"):
            shapes.at("0" * 64)
    finally:
        shapes.at.cache_clear()


def test_a_repinned_problem_follows_its_last_repin():
    """体质修炼 003：人改钉过的题从下一次派工起用改钉的那一版；开题时记下的摘要留着，只是不再生效。"""
    old = "9770a71f87236df2e29e320e75b1c9a6c3bc2ef64d449fb54954dd25a390ace9"
    live = shapes.gongfa()
    p = {**stamp(live), "repins": [{"seq": 9, "ts": 0, "to": {"jie": 2, "digest": old}, "reason": "r"}]}
    assert shapes.stamp_of(p) == {"jie": 2, "digest": old}
    v = shapes.for_problem(p)
    assert v.pinned and v.digest == old and v.holdout_permille() == 0  # 那一版没有常设留出
    back = {**p, "repins": [*p["repins"], {"seq": 12, "ts": 0, "to": dict(p["gongfa"]), "reason": "改回"}]}
    assert shapes.for_problem(back).digest == live["digest"]  # 看最后一条
    assert shapes.stamp_of(stamp(live)) == p["gongfa"] and shapes.stamp_of(None) is None


def test_kernel_config_carries_every_archived_version():
    """组装根抄给内核的功法存档表：每一版的 (摘要, 品阶, 席位 → 形态)，此刻的那一版也在里面。"""
    cfg = shapes.kernel_config()
    archive = {dg: (jie, dict(forms)) for dg, jie, forms in cfg["gongfa_archive"]}
    assert set(archive) == set(shapes.archived_digests())
    assert archive[shapes.gongfa()["digest"]] == (cfg["gongfa"][0], dict(cfg["forms"]))
