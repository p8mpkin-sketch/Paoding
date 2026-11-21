"""开放道的复核（地图 v0.12 Q34；open-lane §3.6、§12 第 4 条；体质修炼 002）。

- 开题时抄入 review: true 的题，每次有答案的交付各派一个 verify 项；受阻的交付、叫停之后不派；每次交付至多领一次。
- verify 租约花验证份额（与判官同一个池子）。
- review 只由本题在途、核这次交付的复核会话提交；每条主张恰好核一次；依据的 Artifact 真实、属本题、类别可采信；
  说重跑了要附执行留档。
- 复核只给读数：终态、等级与等人看的待办都不变。
- 没抄入的题（这项之前的日志）不复核，视图逐字节不变。
"""

from __future__ import annotations

import dataclasses

from conftest import CFG, HUMAN, Kernel
from test_open_lane import answered, lease_solve, open_lane, release, solver

from paoding_graph import views, wire_schema
from paoding_graph import work as wk

ON = dataclasses.replace(CFG, review_open=True)
SINAN = {"kind": "sinan", "id": "sn1"}


def delivered(k: Kernel, **extra) -> str:
    lid = lease_solve(k)
    did = answered(k, lid, **extra)
    assert did.startswith("d_")
    assert release(k, lid, outcome="done") == "ok"
    return did


def lease_verify(k: Kernel, did: str, usd_milli: int = 200) -> str:
    body = {
        "kind": "verify",
        "target": did,
        "holder": "sn1",
        "reserve": {"usd_milli": usd_milli, "wall_s": 300},
        "ttl_s": 600,
    }
    return k.submit(SINAN, "p1", "lease", body)


def verifier(lid: str) -> dict:
    return {"kind": "adapter", "id": "ad1", "role": "verify", "session": lid}


def review_body(k: Kernel, lid: str, did: str, **extra) -> dict:
    rerun = k.art("p1", "exec", b"rerun output")
    return {
        "delivery": did,
        "claims": [
            {"claim": 0, "verdict": "supported", "note": "输出里确有 42", "refs": [rerun]},
            {"claim": 1, "verdict": "unclear", "note": "没有依据可核"},
        ],
        "reruns": [{"check": 0, "result": "pass", "refs": [rerun]}],
        "counterexamples": [],
        "summary": "2 条主张，1 条有据，1 条看不出",
        **extra,
    }


def submit_review(k: Kernel, lid: str, did: str, **extra) -> str:
    return k.submit(verifier(lid), "p1", "review", review_body(k, lid, did, **extra))


def test_without_the_switch_nothing_is_reviewed():
    k = Kernel()
    assert open_lane(k) == "ok"
    did = delivered(k)
    assert "review" not in k.state["problems"]["p1"]
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]
    assert lease_verify(k, did) == "forbidden_op"  # 不在 /work 里
    assert "review" not in views.status(k.state, "p1")["goal"]["deliveries"][0]


def test_the_switch_is_copied_only_into_open_lane_problems():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    assert k.state["problems"]["p1"]["review"] is True
    k2 = Kernel(ON)
    k2.open("p1")
    assert "review" not in k2.state["problems"]["p1"]


def test_a_delivery_is_reviewed_once_and_only_gets_readings():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    did = delivered(k)
    assert wk.work(k.state, "p1") == [
        {"kind": "verify", "target": did},
        {"kind": "human", "target": "p1", "why": "delivered"},  # 复核不拦人看结果
    ]
    lid = lease_verify(k, did)
    assert lid in k.state["leases"] and k.state["leases"][lid]["kind"] == "verify"
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]
    assert submit_review(k, lid, did) == "ok"
    assert k.submit(verifier(lid), "p1", "release", {"lease": lid, "outcome": "done"}) == "ok"
    st = views.status(k.state, "p1")
    rv = st["goal"]["deliveries"][0]["review"]
    assert rv["readings"] == {
        "claims": 2,
        "supported": 1,
        "unsupported": 0,
        "unclear": 1,
        "reruns": {"pass": 1, "fail": 0, "not_rerun": 0},
        "counterexamples": 0,
    }
    assert rv["summary"]["register"] == "叙述" and rv["claims"][0]["refs"][0]["class"] == "exec"
    assert st["problem"]["terminal"] is None and wk.terminal(k.state, "p1") == "delivered"
    env = {"as_of": k.state["seq"], "head": k.state["seq"], "view_hash": "0" * 64}
    assert wire_schema.validate("StatusView", {**env, **st}) == []
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]


def test_a_follow_up_delivery_gets_its_own_review():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    first = delivered(k)
    lid = lease_verify(k, first)
    assert submit_review(k, lid, first) == "ok"
    assert k.submit(HUMAN, "p1", "follow_up", {"text": "再看看", "seen": {"seq": k.state["seq"]}}) == "ok"
    second = delivered(k)
    assert {"kind": "verify", "target": second} in wk.work(k.state, "p1")
    assert {"kind": "verify", "target": first} not in wk.work(k.state, "p1")


def test_a_verify_session_that_ends_without_readings_is_not_retried():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    did = delivered(k)
    lid = lease_verify(k, did)
    assert k.submit(verifier(lid), "p1", "release", {"lease": lid, "outcome": "nothing"}) == "ok"
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]


def test_blocked_deliveries_and_halted_problems_are_not_reviewed():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    lid = lease_solve(k)
    body = {"outcome": "blocked", "claims": [], "self_check": [], "unverified": [], "needs": ["要一个账号"]}
    assert k.submit(solver(lid), "p1", "deliver", body).startswith("d_")
    assert [w["kind"] for w in wk.work(k.state, "p1")] == ["human"]
    k2 = Kernel(ON)
    assert open_lane(k2) == "ok"
    delivered(k2)
    assert k2.submit(HUMAN, "p1", "halt", {}) == "ok"
    assert [w["kind"] for w in wk.work(k2.state, "p1")] == ["human"]


def test_verify_leases_draw_on_the_verify_share():
    k = Kernel(ON)
    assert open_lane(k) == "ok"  # 题预算 5000、验证份额 0.2 → 1000
    did = delivered(k)
    assert lease_verify(k, did, usd_milli=1001) == "over_budget"
    lid = lease_verify(k, did, usd_milli=600)
    body = {"task_id": lid, "source": "proxy", "usd_milli": 250, "wall_s": 0, "price_table": "t"}
    assert k.submit({**verifier(lid)}, "p1", "cost", body) == "ok"
    b = wk.budget_view(k.state, "p1")
    assert b["verify_spent"]["usd_milli"] == 250 and b["by_kind"]["verify"]["usd_milli"] == 250


def test_only_the_verify_session_for_this_delivery_can_review():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    did = delivered(k)
    lid = lease_verify(k, did)
    body = review_body(k, lid, did)
    assert k.submit(solver(lid), "p1", "review", body) == "forbidden_op"  # 席位不对
    assert k.submit(HUMAN, "p1", "review", body) == "forbidden_op"
    assert k.submit(verifier("L999"), "p1", "review", body) == "forbidden_op"  # 不是在途的复核会话
    assert k.submit(verifier(lid), "p1", "review", {**body, "delivery": "d_1"}) == "scope_mismatch"
    ans = k.art("p1", "authored", b"x", actor=verifier(lid))
    deliver = {"outcome": "answered", "answer": ans, "claims": [], "self_check": [], "unverified": []}
    assert k.submit(verifier(lid), "p1", "deliver", deliver) == "forbidden_op"  # 复核会话不能交付


def test_review_bodies_are_checked_mechanically():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    did = delivered(k)
    lid = lease_verify(k, did)
    good = review_body(k, lid, did)

    def bad(**patch) -> str:
        return k.submit(verifier(lid), "p1", "review", {**good, **patch})

    assert bad(claims=good["claims"][:1]) == "schema_error"  # 每条主张都要核
    assert bad(claims=[good["claims"][0], {**good["claims"][1], "claim": 0}]) == "schema_error"  # 重复
    assert bad(claims=[good["claims"][0], {**good["claims"][1], "verdict": "true"}]) == "schema_error"
    assert bad(claims=[good["claims"][0], {**good["claims"][1], "note": " "}]) == "schema_error"
    authored = k.art("p1", "authored", b"opinion", actor=verifier(lid))
    assert bad(claims=[good["claims"][0], {**good["claims"][1], "refs": [authored]}]) == "inadmissible_class"
    assert bad(reruns=[{"check": 1, "result": "pass", "refs": good["reruns"][0]["refs"]}]) == "schema_error"
    assert bad(reruns=[{"check": 0, "result": "pass"}]) == "schema_error"  # 说重跑了要附留档
    assert bad(reruns=[{"check": 0, "result": "not_rerun", "note": "没有网络"}]) == "ok"
    assert bad() == "conflict"  # 一次交付只复核一次


def test_review_does_not_change_the_problems_list_or_levels():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    did = delivered(k)
    before = views.problems(k.state)["totals"]
    lid = lease_verify(k, did)
    assert submit_review(k, lid, did) == "ok"
    after = views.problems(k.state)["totals"]
    assert {a: b for a, b in after.items() if a != "spent_usd_milli"} == {
        a: b for a, b in before.items() if a != "spent_usd_milli"
    }


def test_open_readings_table_counts_deliveries_feedback_and_reviews():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    did = delivered(k)
    lid = lease_verify(k, did)
    assert submit_review(k, lid, did) == "ok"
    assert k.submit(verifier(lid), "p1", "release", {"lease": lid, "outcome": "done"}) == "ok"
    assert k.submit(HUMAN, "p1", "close_problem", {"feedback": "adopted"}) == "ok"
    assert open_lane(k, "p2") == "ok"
    k.open("p3")  # 严格道的题不进这张表
    r = views.open_readings(k.state)
    assert r["problems"] == 2 and r["terminals"] == {"delivered": 1, "unsolved": 0, "open": 1}
    assert r["deliveries"] == 1 and r["outcomes"] == {"answered": 1, "partial": 0, "blocked": 0}
    assert r["feedback"] == {"adopted": 1, "rejected": 0, "none": 0} and r["adoption_rate"] == 1.0
    assert r["review"]["deliveries"] == 1 and r["review"]["supported"] == 1 and r["review"]["reruns"]["pass"] == 1
    env = {"as_of": k.state["seq"], "head": k.state["seq"], "view_hash": "0" * 64}
    assert wire_schema.validate("OpenReadingsView", {**env, **r}) == []
