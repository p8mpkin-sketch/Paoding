"""资源占用 touches（规格 v1.5 §4.1、增量 11、第 52 条）。

覆盖：add_intent 里只许收窄的校验（与风险上限同一处）、缺省的保守展开、/work 派生资源冲突、
租约在冲突时被拒、两个会话同写一条规则时第二个排队，以及重放不变。
"""

import random

import pytest
from conftest import reason
from test_leases import SINAN, R, add_intent, boot, kinds, lease, release

from paoding_graph import work as wk
from paoding_graph.reducer import apply, empty_state, validate
from paoding_graph.replay import replay, state_hash

W = "write"


def opened(k, risks=("r0", "r1", "r1")):
    k.open(scope_risks=risks)
    boot(k)
    rid = lease(k, "reason")
    assert rid.startswith("l_"), rid
    return rid


def t(rule, mode=W):
    return {"rule": rule, "mode": mode}


def rejected(k, **kw):
    """返回拒绝码；被收下时测试失败。"""
    out = k.submit(reason(), "p1", "add_intent", {"title": "x", "premises": [], "budget": R, **kw})
    assert not out.startswith("i_"), out
    return out


# ---------- add_intent：只许收窄，与风险上限同一处 ----------


def test_touches_are_stored_normalized(k):
    opened(k)
    iid = add_intent(k, risk="r1", touches=[t(2), t(0, "read")])
    assert k.state["intents"][iid]["touches"] == [t(0, "read"), t(2)]
    assert wk.holds(k.state, iid) == {0: "read", 2: W}


@pytest.mark.parametrize(
    ("risk", "touches", "code"),
    [
        ("r0", [t(1)], "scope_mismatch"),  # 规则风险高于 Intent 的 risk：越过 I5
        ("r0", [t(1, "read")], "scope_mismatch"),  # 读也不行：能力本身就超了
        ("r1", [t(0)], "scope_mismatch"),  # r0 规则只能读
        ("r1", [t(3)], "unknown_ref"),  # 下标越界
        ("r1", [t(-1)], "unknown_ref"),
        ("r1", [t(1), t(1, "read")], "schema_error"),  # 同一规则只列一次
        ("r1", [{"rule": 1, "mode": "append"}], "schema_error"),
        ("r1", [{"rule": 1, "mode": W, "why": "x"}], "schema_error"),
        ("r2", [t(1)], "scope_mismatch"),  # 风险上限的拒绝先于 touches，同一处检查
    ],
)
def test_touches_may_only_narrow(k, risk, touches, code):
    opened(k)
    assert rejected(k, risk=risk, touches=touches) == code


def test_touches_cannot_name_rules_that_are_only_requested(k):
    """needs_scope 只是申请，还没授权，不能被占用；下标只指 Problem.scope。"""
    opened(k, risks=("r0",))
    need = [{"resource": "target", "pattern": "x", "actions": ["write"], "risk": "r1"}]
    assert rejected(k, risk="r1", needs_scope=need, touches=[t(1)]) == "unknown_ref"


def test_empty_touches_is_the_narrowest(k):
    opened(k)
    iid = add_intent(k, risk="r1", touches=[])
    assert k.state["intents"][iid]["touches"] == [] and wk.holds(k.state, iid) == {}


def test_default_expands_conservatively(k):
    """不声明：全部 risk ≤ Intent 风险的规则，r1 以上按写。"""
    opened(k)
    lo, hi, plain = add_intent(k, risk="r0"), add_intent(k, risk="r1"), add_intent(k, risk="r1")
    assert wk.holds(k.state, lo) == {0: "read"}
    assert wk.holds(k.state, hi) == {0: "read", 1: W, 2: W}
    assert "touches" not in k.state["intents"][plain]


# ---------- /work 派生资源冲突 ----------


def test_two_sessions_writing_the_same_rule_second_queues(k):
    """验收用例：两个会话同时写同一条规则，第二个排队；第一个结束后第二个才可开。"""
    rid = opened(k)
    a = add_intent(k, "a", risk="r1", touches=[t(1)])
    b = add_intent(k, "b", risk="r1", touches=[t(1)])
    c = add_intent(k, "c", risk="r1", touches=[t(2)])
    assert release(k, rid) == "ok"
    assert {("explore", a), ("explore", b), ("explore", c)} <= set(kinds(k))
    la = lease(k, "explore", a)
    assert la.startswith("l_"), la
    # 第二个排队：不在 /work 里，司南拿 /work 之前的快照来领也被内核拒绝
    assert ("explore", b) not in kinds(k) and ("explore", c) in kinds(k)
    assert wk.intent_status(k.state, "p1", b) == "open"
    assert lease(k, "explore", b) == "conflict_leased"
    body = {"kind": "explore", "target": b, "holder": "sn1", "reserve": R, "ttl_s": 120}
    assert validate(k.state, SINAN, "p1", "lease", body, k.cfg, k.ts + 1).detail.startswith(f"规则 1 正被在途租约 {la}")
    lc = lease(k, "explore", c)  # 不同的写规则照常并行
    assert lc.startswith("l_"), lc
    assert release(k, la) == "ok"
    assert ("explore", b) in kinds(k)
    lb = lease(k, "explore", b)
    assert lb.startswith("l_"), lb


def test_readers_share_but_a_writer_excludes_them(k):
    rid = opened(k)
    r1 = add_intent(k, "r1", risk="r1", touches=[t(1, "read")])
    r2 = add_intent(k, "r2", risk="r1", touches=[t(1, "read")])
    wr = add_intent(k, "w", risk="r1", touches=[t(1)])
    assert release(k, rid) == "ok"
    l1 = lease(k, "explore", r1)
    assert lease(k, "explore", r2).startswith("l_")
    assert ("explore", wr) not in kinds(k)
    assert lease(k, "explore", wr) == "conflict_leased"
    assert release(k, l1, "nothing") == "ok"
    assert ("explore", wr) not in kinds(k)  # 另一个读者还在途


def test_undeclared_r1_intents_are_mutually_exclusive(k):
    """缺省保守：不声明 touches 的 r1 Intent 之间按写冲突串行；r0 的之间照旧并行。"""
    rid = opened(k)
    a, b = add_intent(k, "a", risk="r1"), add_intent(k, "b", risk="r1")
    x, y = add_intent(k, "x"), add_intent(k, "y")
    assert release(k, rid) == "ok"
    assert lease(k, "explore", x).startswith("l_") and lease(k, "explore", y).startswith("l_")
    assert lease(k, "explore", a).startswith("l_")
    assert ("explore", b) not in kinds(k)


def test_conflict_holds_after_the_queued_intent_is_leased_and_replays(k):
    rid = opened(k)
    a = add_intent(k, "a", risk="r1", touches=[t(1)])
    b = add_intent(k, "b", risk="r1", touches=[t(1)])
    assert release(k, rid) == "ok"
    la = lease(k, "explore", a)
    assert release(k, la, "nothing") == "ok"
    lb = lease(k, "explore", b)
    assert lb.startswith("l_")
    assert ("explore", a) not in kinds(k)  # a 回到 open，但 b 正写规则 1
    again = replay(k.events, apply, empty_state())
    assert state_hash(again) == state_hash(k.state) and kinds(k) == [
        (w["kind"], w.get("target")) for w in wk.work(again, "p1")
    ]


def test_no_two_live_leases_ever_clash(k):
    """性质：随机的 Intent 与租约序列下，任意两个在途 explore 租约的占用之间没有写冲突。"""
    rng = random.Random(7)
    rid = opened(k, risks=("r0", "r1", "r1", "r1"))
    ids = []
    for n in range(8):
        risk = rng.choice(("r0", "r1"))
        rules = [r for r in range(4) if risk == "r1" or r == 0]
        picked = rng.sample(rules, rng.randint(0, len(rules)))
        kw = (
            {}
            if rng.random() < 0.3
            else {"touches": [t(r, "read" if r == 0 else rng.choice(("read", W))) for r in picked]}
        )
        ids.append(add_intent(k, f"i{n}", risk=risk, **kw))
    assert release(k, rid) == "ok"
    live: list[str] = []
    for _ in range(60):
        if live and rng.random() < 0.4:
            assert release(k, live.pop(rng.randrange(len(live))), "nothing") == "ok"
            continue
        lease(k, "explore", rng.choice(ids))  # 冲突的、不在 /work 里的都会被拒
        live = [l["id"] for l in wk.active_leases(k.state, "p1") if l["kind"] == "explore"]
        held = [wk.holds(k.state, k.state["leases"][l]["target"]) for l in live]
        assert all(not wk.clash(p, q) for n, p in enumerate(held) for q in held[n + 1 :])
