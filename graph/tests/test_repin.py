"""体质修炼 003（docs/design/fenjue/tizhi-003-pinned-forms.md）的试炼。

内核只认不透明的值：功法存档表 Config.gongfa_archive = ((摘要, 品阶, 席位 → 形态), …)。这里不引功法组件，直接给值：
- T4-3：领租约时 lease.form 按题生效的那一版查表；不给表时与 F3 逐字节相同；
- T4-4：repin 只有人能提交；只许改到表里有的、更低的一版；写原因；焚决之前的题、关过的题拒；开题时的 gongfa 不动；
- R2：apply 不读配置，从头重放与在线状态相同。

这些测试台由 tests/fenjue/record_goldens.py 录成黄金日志（repin 道），冻结之后照 R1 逐字节回放。
"""

from __future__ import annotations

import dataclasses

from conftest import CFG, HUMAN, Kernel
from test_gongfa_fields import SINAN, body_of, lease
from test_open_lane import lease_solve, open_lane

from paoding_graph import views
from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

OLD, NEW = "a" * 64, "b" * 64
ARCHIVE = (
    (OLD, 1, (("solve", "h1.solo@1"),)),
    (NEW, 2, (("solve", "h1.solo@2"),)),
)
LIVE = dataclasses.replace(CFG, gongfa=(2, NEW), forms=(("solve", "h1.solo@2"),), gongfa_archive=ARCHIVE)
DOWN = {"to": {"jie": 1, "digest": OLD}, "reason": "新火在真实任务上出事"}


def test_t4_3_without_the_archive_the_lease_is_what_f3_wrote():
    k = Kernel(dataclasses.replace(LIVE, gongfa_archive=()))
    assert open_lane(k, "p1") == "ok"
    lease_solve(k, "p1")
    assert body_of(k, "p1", "lease")[0]["form"] == "h1.solo@2"


def test_t4_3_a_task_opened_under_an_older_version_leases_that_versions_form():
    k = Kernel(dataclasses.replace(LIVE, gongfa=(1, OLD)))
    assert open_lane(k, "old") == "ok"
    k.cfg = LIVE  # 组装根换上新功法（重新装载）
    assert open_lane(k, "new") == "ok"
    lease_solve(k, "old")
    lease_solve(k, "new")
    assert body_of(k, "old", "lease")[0]["form"] == "h1.solo@1"  # 照开题那一版，不照此刻的配置
    assert body_of(k, "new", "lease")[0]["form"] == "h1.solo@2"
    k2 = Kernel(dataclasses.replace(LIVE, gongfa=(9, "f" * 64)))  # 表里没有的版本：退回 forms（F3 原样）
    assert open_lane(k2, "x") == "ok"
    lease_solve(k2, "x")
    assert body_of(k2, "x", "lease")[0]["form"] == "h1.solo@2"


def test_t4_4_a_human_moves_a_running_task_down_and_the_next_lease_follows():
    k = Kernel(LIVE)
    assert open_lane(k, "p1") == "ok"
    first = lease_solve(k, "p1")
    assert k.submit(HUMAN, "p1", "repin", DOWN) == "ok"
    p = k.state["problems"]["p1"]
    assert p["gongfa"] == {"jie": 2, "digest": NEW}  # 开题时记下的不动
    assert [r["to"] for r in p["repins"]] == [{"jie": 1, "digest": OLD}] and p["repins"][0]["reason"] == DOWN["reason"]
    assert k.state["leases"][first]["active"]  # 在跑的会话不受影响
    assert k.submit(SINAN, "p1", "release", {"lease": first, "outcome": "nothing"}) == "ok"
    assert lease_solve(k, "p1").startswith("l_")
    assert body_of(k, "p1", "lease")[-1]["form"] == "h1.solo@1"  # 下一次派工起用改钉的那一版
    assert views.status(k.state, "p1")["problem"]["repins"][0]["to"]["jie"] == 1
    again = replay(k.events, apply, empty_state())  # R2：apply 不读配置
    assert state_hash(again) == state_hash(k.state)


def test_t4_4_who_and_where_a_task_can_be_repinned():
    k = Kernel(LIVE)
    assert open_lane(k, "p1") == "ok"
    assert k.submit(SINAN, "p1", "repin", DOWN) == "forbidden_op"  # 只有人
    assert k.submit(HUMAN, "p1", "repin", {**DOWN, "reason": " "}) == "schema_error"  # 要写原因
    assert k.submit(HUMAN, "p1", "repin", {**DOWN, "extra": 1}) == "schema_error"
    assert k.submit(HUMAN, "p1", "repin", {**DOWN, "to": {"jie": 1, "digest": "c" * 64}}) == "unknown_ref"
    assert k.submit(HUMAN, "p1", "repin", {**DOWN, "to": {"jie": 2, "digest": OLD}}) == "unknown_ref"  # 品阶对不上
    assert k.submit(HUMAN, "p1", "repin", {**DOWN, "to": {"jie": 2, "digest": NEW}}) == "conflict"  # 已经在这一版
    assert k.submit(HUMAN, "p1", "repin", DOWN) == "ok"
    assert k.submit(HUMAN, "p1", "repin", DOWN) == "conflict"
    pre = Kernel(dataclasses.replace(LIVE, gongfa=None))  # 焚决之前开的题：没有版本可改
    assert open_lane(pre, "p1") == "ok"
    pre.cfg = LIVE
    assert pre.submit(HUMAN, "p1", "repin", DOWN) == "forbidden_op"
    off = Kernel(dataclasses.replace(LIVE, gongfa_archive=()))  # 不给存档表：不收 repin
    assert open_lane(off, "p1") == "ok"
    assert off.submit(HUMAN, "p1", "repin", DOWN) == "unknown_ref"
    assert k.submit(HUMAN, "p1", "close_problem", {"reason": "先这样"}) == "ok"
    assert k.submit(HUMAN, "p1", "repin", {**DOWN, "to": {"jie": 2, "digest": NEW}}) == "schema_error"  # 关过的题


def test_r1_r3_tasks_with_and_without_repins_replay_together():
    k = Kernel()
    assert open_lane(k, "plain") == "ok"
    k.cfg = LIVE
    assert open_lane(k, "pinned") == "ok"
    assert k.submit(HUMAN, "pinned", "repin", DOWN) == "ok"
    assert lease(k, "solve", "pinned").startswith("l_")
    again = replay(k.events, apply, empty_state())
    assert state_hash(again) == state_hash(k.state)
    assert "repins" not in again["problems"]["plain"] and len(again["problems"]["pinned"]["repins"]) == 1
