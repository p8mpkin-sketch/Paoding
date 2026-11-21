"""体质修炼 001 的试炼（T4-1 功法摘要入开题、T4-2 会话形态入租约；docs/design/fenjue/tizhi-001-gongfa-in-events.md）。

内核只认两个不透明的配置值，这里不引功法组件，直接给值：
- T4-1：配置给了 gongfa，开题事件体带 {jie, digest}，原样存进题；提交体里给的拒；不进画像与等级；
- T4-2：配置给了 forms，租约事件体按席位带 form；席位没配形态（判官）就不带；提交体里给的不认；
- R2：apply 不读配置，同一份日志从头重放与在线状态相同，与写它时的配置无关；
- R3：同一份日志里先有无字段的旧题、再有带字段的新题，混放重放照旧。

这些测试台由 tests/fenjue/record_goldens.py 录成黄金日志（gongfa 道），冻结之后照 R1 逐字节回放。
"""

from __future__ import annotations

import dataclasses

from conftest import CFG, HUMAN, Kernel
from test_open_lane import answered, lease_solve, open_lane, release

from paoding_graph import views
from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

SINAN = {"kind": "sinan", "id": "sn1"}
GONGFA = (2, "a" * 64)
FORMS = (
    ("bootstrap", "h1.triad@1"),
    ("explore", "h1.triad@1"),
    ("reason", "h1.triad@1"),
    ("recall", "h1.recall@1"),
    ("solve", "h1.solo@2"),
)
FENJUE = dataclasses.replace(CFG, gongfa=GONGFA, forms=FORMS)


def lease(k: Kernel, kind: str, pid: str = "p1", **extra) -> str:
    body = {"kind": kind, "holder": "sn1", "reserve": {"usd_milli": 200, "wall_s": 600}, "ttl_s": 600, **extra}
    return k.submit(SINAN, pid, "lease", body)


def body_of(k: Kernel, pid: str, kind: str) -> list[dict]:
    return [e["body"] for e in k.events if e["problem_id"] == pid and e["kind"] == kind]


def body_of_open(k: Kernel, st: str) -> dict:
    return {
        "title": "t",
        "origin": {"statement_ref": st, "materials": []},
        "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
        "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["exact_match"],
    }


def test_t4_1_gongfa_is_stamped_on_open_and_kept_out_of_the_profile():
    k, plain = Kernel(FENJUE), Kernel()
    assert k.open() == "ok" and plain.open() == "ok"
    assert body_of(k, "p1", "open_problem")[0]["gongfa"] == {"jie": 2, "digest": "a" * 64}
    assert "gongfa" not in body_of(plain, "p1", "open_problem")[0]
    p, q = k.state["problems"]["p1"], plain.state["problems"]["p1"]
    assert p["gongfa"] == {"jie": 2, "digest": "a" * 64} and "gongfa" not in q
    assert p["profile"] == q["profile"]  # 不进画像与等级
    assert views.status(k.state, "p1")["problem"]["gongfa"] == p["gongfa"]
    assert "gongfa" not in views.status(plain.state, "p1")["problem"]


def test_t4_1_submitters_cannot_choose_the_gongfa():
    k = Kernel(FENJUE)
    st = k.art("p1", "input", b"statement p1")
    body = dict(body_of_open(k, st), gongfa={"jie": 9, "digest": "f" * 64})
    assert k.submit(HUMAN, "p1", "open_problem", body) == "schema_error"


def test_t4_2_form_is_stamped_per_seat_and_submitters_cannot_choose_it():
    k = Kernel(FENJUE)
    assert k.open() == "ok"
    lid = lease(k, "bootstrap", form="h1.solo@9")  # 提交体里的不认
    assert lid.startswith("l_")
    assert body_of(k, "p1", "lease")[0]["form"] == "h1.triad@1"
    assert k.state["leases"][lid]["form"] == "h1.triad@1"
    assert views.status(k.state, "p1")["leases"][0]["form"] == "h1.triad@1"
    k.cfg = dataclasses.replace(FENJUE, forms=())  # 席位没配形态：不写
    assert open_lane(k, "p2") == "ok"
    assert lease_solve(k, "p2").startswith("l_")
    assert "form" not in body_of(k, "p2", "lease")[0]


def test_r2_r3_old_and_new_problems_replay_together_whatever_the_config():
    k = Kernel()
    assert open_lane(k, "old") == "ok"
    lid = lease_solve(k, "old")
    assert answered(k, lid, "old").startswith("d_") and release(k, lid, "old", outcome="done") == "ok"
    k.cfg = FENJUE  # 组装根换上功法（设置层热更新同一做法）
    assert open_lane(k, "new") == "ok"
    lid = lease_solve(k, "new")
    assert answered(k, lid, "new").startswith("d_") and release(k, lid, "new", outcome="done") == "ok"
    assert k.open("strict") == "ok" and lease(k, "bootstrap", "strict").startswith("l_")
    again = replay(k.events, apply, empty_state())  # apply 不读配置（R2）
    assert state_hash(again) == state_hash(k.state)
    assert "gongfa" not in again["problems"]["old"] and again["problems"]["new"]["gongfa"]["jie"] == 2
    forms = sorted((lz["problem_id"], lz.get("form")) for lz in again["leases"].values())
    assert forms == [("new", "h1.solo@2"), ("old", None), ("strict", "h1.triad@1")]
