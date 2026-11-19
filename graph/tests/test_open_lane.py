"""开放道的内核（docs/design/open-lane/ §3、§5、§8；cz 2026-11-19 裁决）。

- accept=open：Goal 没有判官、不设候选次数；judges 为空；画像判定轴 none；判定来源 self。
- 派工只有 solve：一个会话做到底；未交付就接力，至多 OPEN_RELAYS 个；交付之后不再派，等人看。
- deliver 只由本题在途的 solve 会话提交；内核只查依据真实存在、类别可采信，不查结论对不对。
- 终态 delivered 只来自 answered/partial 的交付；blocked 不算。人关题可带反馈，反馈不改终态。
- 裁决附加条件 1：开放道的终态与计数永不进入严格道的统计（solved、每解成本），见 test_readings_*。
"""

from __future__ import annotations

from conftest import HUMAN, Kernel

from paoding_graph import views
from paoding_graph import work as wk

SOLVE = {"kind": "adapter", "id": "ad1", "role": "solve"}


def open_lane(k: Kernel, pid: str = "p1", **goal) -> str:
    st = k.art(pid, "input", b"statement " + pid.encode())
    return k.submit(
        HUMAN,
        pid,
        "open_problem",
        {
            "title": "t",
            "origin": {"statement_ref": st, "materials": []},
            "goal": {"statement": "帮我查清楚 X", "accept": "open", **goal},
            "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
            "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
            "env": {"base": "basic", "baseline_ref": "base@1"},
            "judges": [],
        },
    )


def lease_solve(k: Kernel, pid: str = "p1") -> str:
    return k.submit(
        {"kind": "sinan", "id": "sn1"},
        pid,
        "lease",
        {"kind": "solve", "holder": "sn1", "reserve": {"usd_milli": 1000, "wall_s": 600}, "ttl_s": 600},
    )


def solver(lid: str) -> dict:
    return {**SOLVE, "session": lid}


def release(k: Kernel, lid: str, pid: str = "p1", outcome: str = "nothing") -> str:
    return k.submit(solver(lid), pid, "release", {"lease": lid, "outcome": outcome})


def answered(k: Kernel, lid: str, pid: str = "p1", **extra) -> str:
    ans = k.art(pid, "authored", b"the answer", actor=solver(lid))
    proof = k.art(pid, "exec", b"curl output")
    body = {
        "outcome": "answered",
        "answer": ans,
        "claims": [{"text": "X 是 42", "refs": [proof]}, {"text": "顺带一提", "refs": []}],
        "self_check": [{"what": "再请求一次", "result": "pass", "refs": [proof]}],
        "unverified": ["没有核对第二个来源"],
        **extra,
    }
    return k.submit(solver(lid), pid, "deliver", body)


# ---------------------------------------------------------------- 开题


def test_open_lane_opens_without_any_criterion():
    k = Kernel()
    assert open_lane(k) == "ok"
    p = k.state["problems"]["p1"]
    assert p["goal"] == {"statement": "帮我查清楚 X", "accept": "open", "authority": "self"}
    assert p["judges"] == [] and p["judge_snapshot"] == {}
    assert p["profile"]["judge"] == "none"


def test_open_lane_shape_rules():
    k = Kernel()
    assert open_lane(k, "a", check={"judge_id": "replay"}) == "schema_error"  # 开放道不登记判据
    assert open_lane(k, "b", max_attempts=3) == "schema_error"
    assert open_lane(k, "c", acceptance=[{"text": "x", "src": "human"}]) == "schema_error"
    assert open_lane(k, "d", self_checks=[{"text": "make test", "src": "model"}]) == "schema_error"  # 只许原文或人
    assert open_lane(k, "e", self_checks=[{"text": "make test", "src": "span"}]) == "ok"
    assert k.state["problems"]["e"]["goal"]["self_checks"] == [{"id": "c1", "text": "make test", "src": "span"}]
    st = k.art("f", "input", b"s")
    body = {
        "title": "t",
        "origin": {"statement_ref": st, "materials": []},
        "goal": {"statement": "g", "accept": "open"},
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["replay"],
    }
    assert k.submit(HUMAN, "f", "open_problem", body) == "schema_error"  # 开放道不启用判官
    # 判定道不收 self_checks
    assert k.open("g") == "ok"


def test_lane_and_accept_must_match():
    k = Kernel()
    rec = k.art("p1", "input", b"derivation")
    st = k.art("p1", "input", b"statement")
    base = {
        "title": "t",
        "goal": {"statement": "g", "accept": "open"},
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": [],
    }
    confirm = {**base, "origin": {"statement_ref": st, "materials": [], "draft": {"record": rec, "lane": "confirm"}}}
    assert k.submit(HUMAN, "p1", "open_problem", confirm) == "schema_error"
    good = {**base, "origin": {"statement_ref": st, "materials": [], "draft": {"record": rec, "lane": "open"}}}
    assert k.submit(HUMAN, "p1", "open_problem", good) == "ok"


# ---------------------------------------------------------------- 派工与接力


def test_work_offers_only_solve_and_relays_up_to_the_limit():
    k = Kernel()
    open_lane(k)
    assert wk.work(k.state, "p1") == [{"kind": "solve"}]
    for _ in range(wk.OPEN_RELAYS):
        lid = lease_solve(k)
        assert lid.startswith("l_"), lid
        assert wk.work(k.state, "p1") == []  # 一次只有一个求解会话
        assert lease_solve(k) == "conflict_leased"
        assert release(k, lid) == "ok"
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "stalled"}]
    assert lease_solve(k) == "forbidden_op"  # 接力用完：不在 /work 里


def test_strict_kinds_are_not_offered_on_the_open_lane():
    k = Kernel()
    open_lane(k)
    for kind in ("bootstrap", "reason"):
        body = {"kind": kind, "holder": "sn1", "reserve": {"usd_milli": 10, "wall_s": 10}, "ttl_s": 60}
        assert k.submit({"kind": "sinan", "id": "sn1"}, "p1", "lease", body) == "forbidden_op"


# ---------------------------------------------------------------- 交付


def test_deliver_records_answer_claims_and_stops_dispatch():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    did = answered(k, lid)
    assert did.startswith("d_"), did
    d = k.state["problems"]["p1"]["deliveries"][0]
    assert d["outcome"] == "answered" and d["lease"] == lid
    assert d["claims"][1] == {"text": "顺带一提", "refs": []}  # 无依据的主张允许存在
    assert release(k, lid, outcome="done") == "ok"
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]
    assert wk.terminal(k.state, "p1") == "delivered"
    assert wk.followups(k.state, "p1") == []  # 交付不关题


def test_deliver_checks_refs_mechanically():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    note = k.art("p1", "authored", b"my notes", actor=solver(lid))
    bad = {"outcome": "answered", "answer": note, "claims": [{"text": "x", "refs": [note]}]}
    assert k.submit(solver(lid), "p1", "deliver", bad) == "inadmissible_class"  # 模型写的不算依据
    ghost = {"outcome": "answered", "answer": note, "claims": [{"text": "x", "refs": ["a_999"]}]}
    assert k.submit(solver(lid), "p1", "deliver", ghost) == "unknown_ref"  # 编造的编号
    assert k.submit(solver(lid), "p1", "deliver", {"outcome": "answered"}) == "schema_error"  # 没有答案
    assert k.submit(solver(lid), "p1", "deliver", {"outcome": "blocked"}) == "schema_error"  # 受阻要写 needs
    wrong = {"outcome": "answered", "answer": note, "self_check": [{"what": "x", "result": "pass", "item": "c9"}]}
    assert k.submit(solver(lid), "p1", "deliver", wrong) == "unknown_ref"


def test_deliver_only_by_the_live_solve_session():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    ans = k.art("p1", "authored", b"a", actor=solver(lid))
    body = {"outcome": "answered", "answer": ans}
    assert k.submit(solver("l_404"), "p1", "deliver", body) == "forbidden_op"
    assert k.submit(HUMAN, "p1", "deliver", body) == "forbidden_op"
    explore = {"kind": "adapter", "id": "ad1", "session": lid, "role": "explore"}
    assert k.submit(explore, "p1", "deliver", body) == "forbidden_op"
    release(k, lid)
    assert k.submit(solver(lid), "p1", "deliver", body) == "forbidden_op"  # 租约已结束


def test_strict_lane_has_no_deliver_and_open_lane_has_no_goal_judge():
    k = Kernel()
    k.open("s")
    lid = k.submit(
        {"kind": "sinan", "id": "sn1"},
        "s",
        "lease",
        {"kind": "bootstrap", "holder": "sn1", "reserve": {"usd_milli": 100, "wall_s": 60}, "ttl_s": 60},
    )
    sess = {"kind": "adapter", "id": "ad1", "session": lid, "role": "solve"}
    ans = k.art("s", "authored", b"a", actor=sess)
    assert k.submit(sess, "s", "deliver", {"outcome": "answered", "answer": ans}) == "forbidden_op"
    open_lane(k)
    olid = lease_solve(k)
    cand = k.art("p1", "authored", b"42", actor=solver(olid))
    rj = {"target": "goal", "judge_id": "exact_match", "candidate": cand}
    assert k.submit(solver(olid), "p1", "request_judge", rj) == "unknown_ref"  # 开放道的 Goal 没有判据


def test_blocked_delivery_is_honest_and_not_delivered():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    body = {"outcome": "blocked", "needs": ["要 git.lab:8443 的访问权限"], "unverified": ["仓库是否存在"]}
    assert k.submit(solver(lid), "p1", "deliver", body).startswith("d_")
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "blocked"}]
    assert wk.terminal(k.state, "p1") == "unsolved"  # 受阻不算交付
    assert k.submit(HUMAN, "p1", "close_problem", {"reason": "先这样"}) == "ok"
    assert k.state["problems"]["p1"]["terminal"] == "unsolved"


def test_human_close_with_feedback_keeps_terminal():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    answered(k, lid)
    assert k.submit(HUMAN, "p1", "close_problem", {"feedback": "maybe"}) == "schema_error"
    assert k.submit(HUMAN, "p1", "close_problem", {"feedback": "rejected"}) == "ok"
    p = k.state["problems"]["p1"]
    assert p["terminal"] == "delivered" and p["feedback"] == "rejected"  # 不采纳也不改终态
    k.open("s")
    assert k.submit(HUMAN, "s", "close_problem", {"feedback": "adopted"}) == "schema_error"  # 判定道没有反馈


def test_graph_never_auto_closes_the_open_lane():
    k = Kernel()
    open_lane(k)
    lid = lease_solve(k)
    answered(k, lid)
    assert k.submit({"kind": "graph", "id": "g"}, "p1", "close_problem", {}) == "schema_error"


# ---------------------------------------------------------------- 读数隔离（裁决附加条件 1：写成断言）


def _mixed() -> Kernel:
    """一道本地判定解出的题、一道开放道交付的题、一道开放道受阻的题、一道开放道还开着的题。"""
    k = Kernel()
    k.open("s")
    ans = k.art("s", "authored", b"42")
    rid = k.submit(
        {"kind": "adapter", "id": "ad1", "session": "x", "role": "explore"},
        "s",
        "request_judge",
        {"target": "goal", "judge_id": "exact_match", "candidate": ans},
    )
    assert rid.startswith("j_"), rid
    ev = k.art("s", "judge", b"verdict")
    k.submit(
        {"kind": "judge", "id": "jr1"},
        "s",
        "judge_verdict",
        {"request": rid, "result": "pass", "evidence": [ev], "version": "1"},
    )
    if not k.state["problems"]["s"].get("closed"):
        k.submit(HUMAN, "s", "close_problem", {})
    for pid, outcome in (("o1", "answered"), ("o2", "blocked"), ("o3", None)):
        open_lane(k, pid)
        if outcome is None:
            continue
        lid = lease_solve(k, pid)
        k.submit(
            {"kind": "adapter", "id": "ad1", "session": lid},
            pid,
            "cost",
            {"task_id": lid, "source": "proxy", "usd_milli": 700, "wall_s": 3, "price_table": "t"},
        )
        if outcome == "answered":
            answered(k, lid, pid)
        else:
            k.submit(solver(lid), pid, "deliver", {"outcome": "blocked", "needs": ["凭据"]})
        k.submit(HUMAN, pid, "close_problem", {"feedback": "adopted"} if outcome == "answered" else {})
    return k


def test_readings_open_lane_never_enters_strict_statistics():
    k = _mixed()
    v = views.problems(k.state)
    t = v["totals"]
    by = t["by_authority"]
    strict_solved = sum(1 for p in k.state["problems"].values() if p.get("terminal") == "solved")
    # 严格道的统计只数判官判出的 solved：开放道的题无论交付与否都不进分子
    assert t["solved"] == by["local"]["solved"] == strict_solved
    # 每解成本只算严格道的花费：开放道两道题各花了 700，一分也不进
    strict_spent = sum(
        wk.budget_view(k.state, pid)["spent"]["usd_milli"]
        for pid, p in k.state["problems"].items()
        if p["goal"]["accept"] != "open"
    )
    assert t["spent_usd_milli"] == strict_spent + 1400
    assert t["cost_per_solve_usd_milli"] == strict_spent // strict_solved
    # delivered 只在 self 一行；self 一行永远没有 solved 与 accepted；其他行永远没有 delivered
    assert by["self"] == {"problems": 3, "solved": 0, "accepted": 0, "delivered": 1, "unsolved": 1, "open": 1}
    for a in ("local", "external", "human"):
        assert by[a]["delivered"] == 0
    # 每一道开放道的题，列表里的判定来源都是 self，徽章写明未经判定
    for it in v["items"]:
        if it["id"].startswith("o"):
            assert it["authority"] == "self"
            assert it["terminal"] in (None, "delivered", "unsolved")
            assert it["terminal_badge"]["label"] == views.OPEN_BADGE_LABEL and it["terminal_badge"]["judge_id"] == ""


def test_readings_terminal_values_never_cross_lanes():
    """四个终态各有唯一来源：开放道的题只可能是 delivered 或 unsolved；判定道的题永远不会是 delivered。"""
    k = _mixed()
    for pid, p in k.state["problems"].items():
        if not p.get("closed"):
            continue
        if p["goal"]["accept"] == "open":
            assert p["terminal"] in ("delivered", "unsolved"), pid
        else:
            assert p["terminal"] != "delivered", pid


def test_status_view_of_an_open_problem_matches_the_wire_schema():
    from paoding_graph import wire_schema

    k = _mixed()
    st = views.status(k.state, "o1")
    g = st["goal"]
    assert g["accept"] == "open" and g["authority"] == "self"
    assert g["predicate"]["verdicts"] == [] and g["predicate"]["level"] is None
    d = g["deliveries"][0]
    assert [c["supported"] for c in d["claims"]] == [True, False]
    assert d["claims"][0]["refs"][0]["class"] == "exec"
    assert g["feedback"] == "adopted"
    env = {"as_of": k.state["seq"], "head": k.state["seq"], "view_hash": "0" * 64}
    assert wire_schema.validate("StatusView", {**env, **st}) == []
    assert wire_schema.validate("ProblemsView", {**env, **views.problems(k.state)}) == []
