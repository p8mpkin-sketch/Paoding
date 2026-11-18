"""D8 reducer 侧与 D9 离线部分：租约、/work、Intent 状态机、消费门、关题与终态、预算账本。

验收：3.1.5 的 3（M0 形态）、5、7、9、15；3.3.5 的 7；3.4.5 的 3、6；3.5.5 的 1、2、5。
（3.1.5 的 2 崩溃恢复见 test_service.py。）
"""
from conftest import HUMAN, JUDGE, Kernel, explore, reason

from paoding_graph import levels as lv
from paoding_graph import work as wk
from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

SINAN = {"kind": "sinan", "id": "sn1"}
WATCHDOG = {"kind": "watchdog", "id": "wd"}
R = {"usd_milli": 100, "wall_s": 60}


def lease(k, kind, target=None, reserve=R, pid="p1", actor=SINAN, ttl=120):
    return k.submit(actor, pid, "lease", {"kind": kind, **({"target": target} if target else {}),
                                          "holder": actor["id"], "reserve": reserve, "ttl_s": ttl})


def release(k, lid, outcome="done", pid="p1", actor=SINAN):
    return k.submit(actor, pid, "release", {"lease": lid, "outcome": outcome})


def boot(k, pid="p1"):
    """走完 Bootstrap，让 reason 出现在 /work。"""
    lid = lease(k, "bootstrap", pid=pid)
    assert lid.startswith("l_"), lid
    assert release(k, lid, "nothing", pid=pid) == "ok"


def add_intent(k, title="i", risk="r0", premises=(), done=None, pid="p1", **kw):
    body = {"title": title, "premises": list(premises), "risk": risk, "budget": R, **kw}
    if done:
        body["done"] = {"judge_id": done, "max_attempts": 2}
    return k.submit(reason(), pid, "add_intent", body)


def kinds(k, pid="p1"):
    return [(w["kind"], w.get("target")) for w in wk.work(k.state, pid)]


# ---------- /work 与租约 ----------

def test_bootstrap_then_reason(k):
    k.open()
    assert kinds(k) == [("bootstrap", None)]
    lid = lease(k, "bootstrap")
    assert kinds(k) == []
    release(k, lid, "nothing")
    assert ("reason", None) in kinds(k)
    rl = lease(k, "reason")
    assert ("reason", None) not in kinds(k)
    release(k, rl)
    assert ("reason", None) not in kinds(k)            # 释放 reason 本身不触发下一轮 reason
    k.submit(HUMAN, "p1", "hint", {"text": "看看配置"})
    assert ("reason", None) in kinds(k)                # 新 Hint 触发


def test_concurrent_lease_exactly_one(k):
    """3.1.5 的 5：两个请求抢同一 Intent，恰好一个成功。"""
    k.open(); boot(k)
    i = add_intent(k)
    a, b = lease(k, "explore", i), lease(k, "explore", i)
    assert a.startswith("l_") and b == "conflict_leased"
    assert wk.intent_status(k.state, "p1", i) == "leased"


def test_lease_must_be_in_work(k):
    k.open()
    assert lease(k, "reason") == "forbidden_op"
    assert lease(k, "bootstrap", actor=JUDGE) == "forbidden_op"


def test_release_only_by_holder(k):
    k.open()
    lid = lease(k, "bootstrap")
    other = {"kind": "sinan", "id": "sn2"}
    assert release(k, lid, actor=other) == "forbidden_op"


def test_expire_and_reopen_keeps_facts(k):
    """3.4.5 的 3：任务中途 CLI 被杀，租约到期，Intent 重开，此前提交的论断仍在。"""
    k.open(); boot(k)
    i = add_intent(k)
    lid = lease(k, "explore", i, ttl=1)
    f = k.obs(actor=explore(lid))
    assert k.state["facts"][f]["yielded_by"] == i               # yields 边由租约推出
    assert k.submit(WATCHDOG, "p1", "expire_lease", {"lease": lid}) == "schema_error"   # 未到期
    k.ts += 2000
    assert k.submit(WATCHDOG, "p1", "expire_lease", {"lease": lid}) == "ok"
    assert wk.intent_status(k.state, "p1", i) == "open"
    assert f in k.state["facts"]
    l2 = lease(k, "explore", i)
    assert k.state["leases"][l2]["attempt"] == 2
    release(k, l2, "failed")
    assert wk.intent_status(k.state, "p1", i) == "abandoned"     # 两次后放弃（3.4.4）


def test_plain_intent_done(k):
    k.open(); boot(k)
    i = add_intent(k)
    release(k, lease(k, "explore", i), "done")
    assert wk.intent_status(k.state, "p1", i) == "done"
    assert ("explore", i) not in kinds(k)


def test_idler_cannot_add_intent(k):
    """3.1.5 的 6 与 3.4.5 的 6。"""
    k.open()
    idler = {"kind": "adapter", "id": "ad1", "session": "s", "role": "idler"}
    assert k.submit(idler, "p1", "add_intent", {"title": "x", "premises": [], "risk": "r0",
                                                "budget": R}) == "forbidden_op"


# ---------- 审批门（3.1.5 的 7） ----------

def test_r2_never_in_explore_without_approve(k):
    k.open("p1", scope_risks=("r0", "r2")); boot(k)
    i = add_intent(k, risk="r2", rollback=None) if False else add_intent(k, risk="r2")
    assert wk.intent_status(k.state, "p1", i) == "needs_human"
    assert ("explore", i) not in kinds(k) and ("human", i) in kinds(k)
    assert k.decide("p1", i) == "ok"
    assert ("explore", i) in kinds(k)
    lid = lease(k, "explore", i, ttl=1)
    k.ts += 2000
    k.submit(WATCHDOG, "p1", "expire_lease", {"lease": lid})
    assert wk.intent_status(k.state, "p1", i) == "needs_human"      # 一次批准只管一次租约
    assert ("explore", i) not in kinds(k)


def test_deny_abandons(k):
    k.open("p1", scope_risks=("r2",)); boot(k)
    i = add_intent(k, risk="r2")
    assert k.decide("p1", i, "deny", reason="不放行") == "ok"
    assert wk.intent_status(k.state, "p1", i) == "abandoned"


# ---------- 消费门与坏事实注入（3.1.5 的 3，M0 形态；3.3.5 的 7） ----------

def test_bad_fact_injection_m0(k):
    k.open("p1", scope_risks=("r1",)); boot(k)
    a = k.obs(title="A"); k.verdict("p1", a, "pass")
    i0 = add_intent(k, "on-A-r0", premises=[a])
    i1 = add_intent(k, "on-A-r1", risk="r1", premises=[a])
    assert wk.intent_status(k.state, "p1", i1) == "open"
    lid = lease(k, "explore", i1)
    k.verdict("p1", a, "fail")                                      # 一次失败：E0 + unstable
    _, res = lv.compute(k.state, "p1")
    assert res.levels[a] == "E0" and a in res.unstable
    assert lid in wk.premise_lost(k.state, "p1")                    # 在途租约带 premise_lost
    release(k, lid, "nothing")
    assert wk.intent_status(k.state, "p1", i1) == "blocked"
    assert ("rejudge", a) in kinds(k)                               # /work 给出复判
    k.verdict("p1", a, "fail")                                      # 复判再失败：X
    assert lv.levels(k.state, "p1")[a] == "X"
    assert wk.intent_status(k.state, "p1", i0) == "abandoned"
    assert wk.intent_status(k.state, "p1", i1) == "abandoned"


def test_rejudge_two_passes_restore_e3(k):
    """3.3.5 的 7：复判连续两次通过则回到 E3。"""
    k.open()
    a = k.obs()
    k.verdict("p1", a, "pass"); k.verdict("p1", a, "fail")
    k.verdict("p1", a, "pass")
    assert lv.levels(k.state, "p1")[a] == "E0"
    k.verdict("p1", a, "pass")
    assert lv.levels(k.state, "p1")[a] == "E3"


def test_checked_intent_unblocks_dependent(k):
    """3.1.5 的 9。"""
    k.open(); boot(k)
    cut = add_intent(k, "cut", done="replay")
    nxt = add_intent(k, "next", premises=[cut])
    assert wk.intent_status(k.state, "p1", nxt) == "blocked"
    lid = lease(k, "explore", cut)
    k.verdict("p1", cut, "pass", candidate=k.art("p1", "authored", b"c"))
    release(k, lid)
    assert wk.intent_status(k.state, "p1", cut) == "achieved"
    assert wk.intent_status(k.state, "p1", nxt) == "open"


def test_abandon_rules(k):
    k.open(); boot(k)
    i = add_intent(k)
    lid = lease(k, "explore", i)
    assert k.submit(reason(), "p1", "abandon_intent", {"intent": i}) == "conflict_leased"
    release(k, lid, "nothing")
    assert k.submit(explore(), "p1", "abandon_intent", {"intent": i}) == "forbidden_op"
    assert k.submit(reason(), "p1", "abandon_intent", {"intent": i}) == "ok"
    assert wk.intent_status(k.state, "p1", i) == "abandoned"


# ---------- 关题与终态（3.1.5 的 15） ----------

def test_terminal_solved_auto_followup(k):
    k.open(); boot(k)
    k.verdict("p1", "goal", "pass", judge="exact_match", candidate=k.art("p1", "authored", b"ans"))
    assert wk.followups(k.state, "p1") == [("close_problem", {"terminal": "solved", "card_hash": None,
                                                               "by": "goal_e3"})]
    assert k.submit({"kind": "graph", "id": "graph"}, "p1", "close_problem", {"terminal": "solved"}) == "ok"
    assert k.state["problems"]["p1"]["terminal"] == "solved"
    assert wk.work(k.state, "p1") == [] and wk.active_leases(k.state, "p1") == []


def test_terminal_unsolved_by_human(k):
    k.open()
    assert k.submit(HUMAN, "p1", "close_problem", {"terminal": "solved"}) == "schema_error"   # 终态不由人申报
    assert k.submit(HUMAN, "p1", "close_problem", {}) == "ok"
    assert k.state["problems"]["p1"]["terminal"] == "unsolved"
    assert k.submit(HUMAN, "p1", "hint", {"text": "x"}) == "schema_error"


def test_graph_cannot_close_unsolved(k):
    k.open()
    assert k.submit({"kind": "graph", "id": "graph"}, "p1", "close_problem", {}) == "schema_error"


def test_stall_goes_to_human(k):
    k.open(); boot(k)
    release(k, lease(k, "reason"))
    assert ("human", "p1") in kinds(k)


# ---------- 预算（3.5.5 的 1、2、5） ----------

def test_reservations_cap(k):
    """3.5.5 的 1：三个并发租约的预留之和超过上限，只有放得下的被批准。cap = 5000。"""
    k.open(); boot(k)
    ids = [add_intent(k, f"i{n}") for n in range(3)]
    big = {"usd_milli": 2000, "wall_s": 60}
    out = [lease(k, "explore", i, reserve=big) for i in ids]
    assert [o.startswith("l_") for o in out] == [True, True, False] and out[2] == "over_budget"


def test_bootstrap_share(k):
    k.open()
    assert lease(k, "bootstrap", reserve={"usd_milli": 1501, "wall_s": 1}) == "over_budget"   # 0.3 × 5000


def test_verify_pool(k):
    k.open()
    f = k.obs()
    rid = k.submit(HUMAN, "p1", "request_judge", {"target": f, "judge_id": "replay"})
    assert lease(k, "judge", rid, reserve={"usd_milli": 1001, "wall_s": 1}, actor=JUDGE) == "over_budget"
    assert lease(k, "judge", rid, reserve={"usd_milli": 1000, "wall_s": 1}, actor=JUDGE).startswith("l_")


def cost(k, lid, usd, actor=None):
    return k.submit(actor or {"kind": "adapter", "id": "ad1", "session": lid}, "p1", "cost", {
        "task_id": lid, "source": "proxy", "tokens_in": 10, "tokens_cached": 0, "tokens_out": 5,
        "usd_milli": usd, "wall_s": 3, "price_table": "anthropic@2026-11"})


def follow(k):
    for kind, body in wk.followups(k.state, "p1"):
        assert k.submit({"kind": "graph", "id": "graph"}, "p1", kind, body) == "ok"


def test_budget_mark_and_review_period(k):
    """3.5.5 的 2：越过 50%，复盘期内 /work 不给 explore，直到带 reflect 的 reason 释放。"""
    k.open(); boot(k)
    i = add_intent(k)
    lid = lease(k, "explore", i)
    cost(k, lid, 2600)
    follow(k)
    assert k.state["problems"]["p1"]["marks"] == [50]
    release(k, lid, "nothing")
    assert not any(w[0] == "explore" for w in kinds(k))
    reason_item = [w for w in wk.work(k.state, "p1") if w["kind"] == "reason"]
    assert reason_item == [{"kind": "reason", "reflect": True}]
    rl = lease(k, "reason")
    assert k.state["leases"][rl]["reflect"] is True
    release(k, rl)
    assert ("explore", i) in kinds(k)


def test_ledger_replays(k):
    """3.5.5 的 5：重放后账本投影与运行时一致。"""
    k.open(); boot(k)
    i = add_intent(k)
    lid = lease(k, "explore", i)
    cost(k, lid, 700); cost(k, lid, 300)
    live = wk.budget_view(k.state, "p1")
    again = wk.budget_view(replay(k.events, apply, empty_state()), "p1")
    assert live == again and live["spent"]["usd_milli"] == 1000 and live["reserved"]["usd_milli"] == 100
    assert state_hash(replay(k.events, apply, empty_state())) == state_hash(k.state)


def test_cost_requires_task(k):
    k.open()
    assert cost(k, "l_999", 1) == "unknown_ref"
