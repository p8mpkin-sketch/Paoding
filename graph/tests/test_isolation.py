"""跨题隔离（I7 等级不出题的推广）：一道题上的提议读不到、也改不了另一道题的任何对象。

三组测试：

1. 审计报告复现的两处缺陷各一条回归：经已关闭的题释放别题的在途租约；Hint 的 about 指向别题节点。
2. 逐项对抗：凡是带引用的操作，把引用换成别题的 id，一律被拒，被引用的题不变。
3. 性质测试（手写随机交错序列，固定种子，常驻 CI）：两题的事件随机交错，其间夹杂跨题引用的提议。
   每一步都核对两件事——
   a. validate 的结果只取决于本题的切片：在完整状态上与在"只重放本题事件"得到的状态上，结果逐字段相同；
   b. 每道题在完整状态里的切片与派生视图，等于只重放本题事件得到的切片与派生视图。
   b 成立即"两题各自的状态互不影响"；a 成立即"别题的事件改变不了本题任何一次裁决"。
"""

import random

import pytest
from conftest import HUMAN, JUDGE, Kernel, explore, reason

from paoding_graph import levels as lv
from paoding_graph import views
from paoding_graph import work as wk
from paoding_graph.reducer import Ok, Reject, apply, empty_state, validate
from paoding_graph.replay import replay

SINAN = {"kind": "sinan", "id": "sn1"}
WATCHDOG = {"kind": "watchdog", "id": "wd"}
R = {"usd_milli": 100, "wall_s": 60}
PIDS = ("P", "Q")


def lease(k, pid, kind, target=None, ttl=10**6, actor=SINAN):
    return k.submit(
        actor,
        pid,
        "lease",
        {"kind": kind, **({"target": target} if target else {}), "holder": actor["id"], "reserve": R, "ttl_s": ttl},
    )


def two_problems():
    """两道题各自走完 Bootstrap，各有一条 Intent、一条在途 explore 租约、一条观察、一条 Hint、一个判官请求。"""
    k, ids = Kernel(), {}
    for pid in PIDS:
        k.open(pid)
        b = lease(k, pid, "bootstrap")
        assert k.submit(SINAN, pid, "release", {"lease": b, "outcome": "nothing"}) == "ok"
        i = k.submit(reason(), pid, "add_intent", {"title": f"i-{pid}", "premises": [], "risk": "r0", "budget": R})
        l = lease(k, pid, "explore", i)
        f = k.obs(pid, title=f"o-{pid}", actor=explore(l))
        a = k.state["facts"][f]["grounds"][0]
        h = k.submit(HUMAN, pid, "hint", {"text": f"h-{pid}"})
        j = k.submit(HUMAN, pid, "request_judge", {"target": f, "judge_id": "replay"})
        ids[pid] = {"intent": i, "lease": l, "fact": f, "art": a, "hint": h, "request": j}
        assert all(v.split("_")[0] in "ilfahj" for v in ids[pid].values()), ids[pid]
    return k, ids


# ---------- 1. 审计报告的两处缺陷 ----------


def test_release_via_closed_problem_cannot_end_other_problems_lease():
    """缺陷 A（reducer 的 _v_release）：题 P 已关闭时，凭 P 提交 release 去结束题 Q 的在途租约。"""
    k, ids = two_problems()
    assert k.submit(HUMAN, "P", "close_problem", {"reason": "收工"}) == "ok"
    ql = ids["Q"]["lease"]
    n = len(k.events)
    for actor in (SINAN, explore(ql), explore(ids["P"]["lease"]), JUDGE):
        assert k.submit(actor, "P", "release", {"lease": ql, "outcome": "done"}) == "scope_mismatch"
    assert k.state["leases"][ql]["active"] and "outcome" not in k.state["leases"][ql]
    assert len(k.events) == n  # P 的链上没有多出事件
    assert wk.intent_status(k.state, "Q", ids["Q"]["intent"]) == "leased"


def test_release_after_close_still_needs_the_holder():
    """关题只放宽结局的取值，不放宽归属：非持有者、已结束的租约照旧被拒，持有者照旧能交回。"""
    k, ids = two_problems()
    pl = ids["P"]["lease"]
    assert k.submit(HUMAN, "P", "close_problem", {"reason": "收工"}) == "ok"
    assert k.submit({"kind": "sinan", "id": "sn2"}, "P", "release", {"lease": pl}) == "forbidden_op"
    assert k.submit(JUDGE, "P", "release", {"lease": pl}) == "forbidden_op"  # 判官只管 judge 租约
    assert k.submit(SINAN, "P", "release", {"lease": "l_999"}) == "unknown_ref"
    assert k.submit(explore(pl), "P", "release", {"lease": pl, "outcome": "done"}) == "ok"
    assert k.state["leases"][pl]["outcome"] == "closed"
    assert k.submit(SINAN, "P", "release", {"lease": pl}) == "schema_error"  # 结局不被第二次改写


def test_hint_about_other_problems_node():
    """缺陷 B（reducer 的 _v_hint）：about 只查全局存在。"""
    k, ids = two_problems()
    for key in ("fact", "intent"):
        assert k.submit(HUMAN, "P", "hint", {"text": "x", "about": ids["Q"][key]}) == "scope_mismatch"
    assert k.submit(HUMAN, "P", "hint", {"text": "x", "about": "f_999"}) == "unknown_ref"
    assert k.submit(HUMAN, "P", "hint", {"text": "x", "about": ids["P"]["fact"]}).startswith("h_")
    assert k.submit(HUMAN, "P", "hint", {"text": "x", "about": "goal"}).startswith("h_")


def test_task_token_is_only_valid_in_its_leases_problem():
    """性质测试找出的第三处：任务令牌的会话是别题的租约时，论断会带上别题 Intent 的 yielded_by。"""
    k, ids = two_problems()
    a = k.art("P", "exec", b"own")
    r = k.submit(
        explore(ids["Q"]["lease"]),
        "P",
        "add_fact",
        {
            "title": "t",
            "claim_type": "observation",
            "check": {"judge_id": "replay", "expect": {}},
            "premises": [],
            "grounds": [a],
        },
    )
    assert r == "scope_mismatch"


def test_goal_attempts_are_counted_per_problem():
    """性质测试找出的第四处：Goal 的候选次数按 target == "goal" 计数，而每道题的目标都叫 goal。"""
    k, _ = two_problems()
    for n in range(3):  # 题 Q 用满自己的 3 个候选
        c = k.art("Q", "authored", f"q{n}".encode())
        assert k.submit(
            HUMAN, "Q", "request_judge", {"target": "goal", "judge_id": "exact_match", "candidate": c}
        ).startswith("j_")
    c = k.art("Q", "authored", b"q3")
    assert (
        k.submit(HUMAN, "Q", "request_judge", {"target": "goal", "judge_id": "exact_match", "candidate": c})
        == "quota_exceeded"
    )
    c = k.art("P", "authored", b"p0")  # 题 P 的额度不受影响
    assert k.submit(
        HUMAN, "P", "request_judge", {"target": "goal", "judge_id": "exact_match", "candidate": c}
    ).startswith("j_")


# ---------- 2. 逐项对抗：引用换成别题的 id ----------


def cross_ops(own: dict, other: dict) -> list[tuple[dict, str, dict]]:
    """在本题上提交、却引用别题对象的提议。own 只用来填合法的其余字段。"""
    fact = {
        "title": "x",
        "claim_type": "observation",
        "check": {"judge_id": "replay", "expect": {"x": 1}},
        "premises": [],
        "grounds": [own["art"]],
    }
    cost = {"source": "proxy", "usd_milli": 1, "price_table": "t"}
    return [
        (SINAN, "release", {"lease": other["lease"], "outcome": "done"}),
        (explore(other["lease"]), "release", {"lease": other["lease"], "outcome": "done"}),
        (SINAN, "renew", {"lease": other["lease"]}),
        (WATCHDOG, "expire_lease", {"lease": other["lease"]}),
        ({"kind": "adapter", "id": "ad1"}, "cost", {**cost, "task_id": other["lease"]}),
        (HUMAN, "hint", {"text": "x", "about": other["fact"]}),
        (HUMAN, "hint", {"text": "x", "about": other["intent"]}),
        (HUMAN, "hint", {"close": other["hint"]}),
        (HUMAN, "approve", {"intent": other["intent"], "decision": "approve"}),
        (HUMAN, "abandon_intent", {"intent": other["intent"]}),
        (HUMAN, "request_judge", {"target": other["fact"], "judge_id": "replay"}),
        (JUDGE, "judge_verdict", {"request": other["request"], "result": "pass", "version": "1"}),
        (explore("s"), "add_fact", {**fact, "premises": [other["fact"]]}),
        (explore("s"), "add_fact", {**fact, "grounds": [other["art"]]}),
        (explore("s"), "add_fact", {**fact, "body_ref": other["art"]}),
        (explore("s"), "add_fact", {**fact, "check": {"judge_id": "replay", "spec_ref": other["art"]}}),
        (explore(other["lease"]), "add_fact", fact),
        (reason(), "add_intent", {"title": "x", "premises": [other["fact"]], "risk": "r0", "budget": R}),
        (
            {"kind": "executor", "id": "ex1"},
            "register_artifact",
            {"hash": "0" * 64, "size": 0, "media_type": "text/plain", "class": "authored", "parents": [other["art"]]},
        ),
    ]


@pytest.mark.parametrize("closed", [False, True], ids=["open", "closed"])
def test_every_cross_problem_reference_is_rejected(closed):
    k, ids = two_problems()
    if closed:
        assert k.submit(HUMAN, "P", "close_problem", {"reason": "收工"}) == "ok"
    before, n = k.state, len(k.events)
    for actor, kind, body in cross_ops(ids["P"], ids["Q"]):
        r = validate(k.state, actor, "P", kind, body, k.cfg, k.ts + 1)
        assert isinstance(r, Reject), (kind, body, r)
        assert k.submit(actor, "P", kind, body) == r.code
    assert k.state is before and len(k.events) == n


# ---------- 3. 性质测试：两题事件交错，各自状态互不影响 ----------


def slice_of(state: dict, pid: str) -> dict:
    """状态里属于一道题的全部内容。"""
    mine = lambda coll: {i: x for i, x in state[coll].items() if x["problem_id"] == pid}  # noqa: E731
    intents = mine("intents")
    return {
        "problem": state["problems"].get(pid),
        **{c: mine(c) for c in ("artifacts", "facts", "requests", "leases", "hints")},
        "intents": intents,
        "verdicts": [v for v in state["verdicts"] if v["problem_id"] == pid],
        "costs": [c for c in state["costs"] if c["problem_id"] == pid],
        "content_keys": state["content_keys"].get(pid, {}),
        "approvals": {i: v for i, v in state["approvals"].items() if i in intents},
        "lease_seqs": {i: v for i, v in state["lease_seqs"].items() if i in intents},
        "abandoned": [i for i in state["abandoned"] if i in intents],
        "decisions": {i: v for i, v in state.get("decision_reasons", {}).items() if i in intents},
    }


def derived(state: dict, pid: str) -> dict:
    """本题的派生量：等级、/work、账本、状态视图。全部是状态的纯函数。"""
    if pid not in state["problems"]:
        return {}
    return {
        "levels": lv.levels(state, pid),
        "work": wk.work(state, pid),
        "budget": wk.budget_view(state, pid),
        "status": views.status(state, pid),
        "terminal": wk.terminal(state, pid),
    }


def alone(k: Kernel, pid: str) -> dict:
    """只重放本题事件得到的状态；全局时钟与序号取完整状态的值（它们是共享的，不属于任何一道题）。"""
    s = replay([e for e in k.events if e["problem_id"] == pid], apply, empty_state())
    return {**s, "now": k.state["now"], "seq": k.state["seq"]}


def pick(rng, xs):
    xs = sorted(xs)
    return rng.choice(xs) if xs else None


def own_op(rng: random.Random, k: Kernel, pid: str):
    """本题上随机一条提议，引用只取本题的对象。可能合法也可能被拒，两种都要与切片上的结果一致。"""
    s = slice_of(k.state, pid)
    active = [l for l, x in s["leases"].items() if x["active"]]
    work = wk.work(k.state, pid)
    lid, fid, iid = pick(rng, active), pick(rng, s["facts"]), pick(rng, s["intents"])
    session = explore(pick(rng, [l for l in active if s["leases"][l]["kind"] == "explore"]) or f"s-{pid}")
    c = rng.randrange(17)
    if c == 0 and work:
        w = rng.choice(work)
        if w["kind"] in ("bootstrap", "reason", "explore", "judge"):
            actor = JUDGE if w["kind"] == "judge" else SINAN
            return (
                actor,
                "lease",
                {
                    "kind": w["kind"],
                    **({"target": w["target"]} if w.get("target") else {}),
                    "holder": actor["id"],
                    "reserve": R,
                    "ttl_s": rng.choice([1, 10**6]),
                },
            )
    if c in (1, 2) and lid:
        l = s["leases"][lid]
        actor = JUDGE if l["kind"] == "judge" else rng.choice([SINAN, explore(lid)])
        return actor, "release", {"lease": lid, "outcome": rng.choice(["done", "failed", "nothing"])}
    if c == 3 and lid:
        return SINAN, "renew", {"lease": lid, "ttl_s": 10**6}
    if c == 4 and lid:
        k.ts += rng.choice([0, 2000])  # 时钟是共享的：两题的短租约一起到期
        return WATCHDOG, "expire_lease", {"lease": lid}
    if c in (5, 6):
        a = k.art(pid, "exec", f"e{len(k.events)}".encode())
        return (
            session,
            "add_fact",
            {
                "title": f"o{rng.randrange(6)}",
                "claim_type": "observation",
                "check": {"judge_id": "replay", "expect": {"n": rng.randrange(6)}},
                "premises": [fid] if fid and rng.random() < 0.4 else [],
                "grounds": [a],
            },
        )
    if c == 7 and fid:
        return session, "add_fact", {"title": f"d{rng.randrange(4)}", "claim_type": "inference", "premises": [fid]}
    if c in (8, 9):
        return (
            rng.choice([reason(f"r-{pid}"), HUMAN]),
            "add_intent",
            {
                "title": f"i{rng.randrange(6)}",
                "premises": [fid] if fid and rng.random() < 0.5 else [],
                "risk": rng.choice(["r0", "r0", "r2"]),
                "budget": R,
                **({"done": {"judge_id": "replay", "max_attempts": 2}} if rng.random() < 0.3 else {}),
                **({"expected_gain": rng.random()} if rng.random() < 0.3 else {}),
            },
        )
    if c == 10:
        target = rng.choice(["goal", fid or "goal", iid or "goal"])
        cand = pick(rng, s["artifacts"]) if target == "goal" or target in s["intents"] else None
        return (
            HUMAN,
            "request_judge",
            {
                "target": target,
                "judge_id": rng.choice(["replay", "exact_match"]),
                **({"candidate": cand} if cand else {}),
            },
        )
    if c == 11:
        rid = pick(rng, [r for r, x in s["requests"].items() if x.get("verdict_seq") is None])
        if rid:
            ev = k.art(pid, "judge", f"v{len(k.events)}".encode())
            return (
                JUDGE,
                "judge_verdict",
                {
                    "request": rid,
                    "version": "1",
                    "evidence": [ev],
                    "result": rng.choice(["pass", "pass", "fail", "flaky"]),
                },
            )
    if c == 12:
        hid = pick(rng, s["hints"])
        if hid and rng.random() < 0.3:
            return HUMAN, "hint", {"close": hid}
        return HUMAN, "hint", {"text": "h", **({"about": rng.choice([fid or "goal", iid or "goal", "goal"])})}
    if c == 13 and iid:
        d = rng.choice(["approve", "deny"])
        return HUMAN, "approve", {"intent": iid, "decision": d, **({"reason": "r"} if d == "deny" else {})}
    if c == 14 and iid:
        return rng.choice([HUMAN, reason(f"r-{pid}")]), "abandon_intent", {"intent": iid}
    if c == 15 and s["leases"]:
        return (
            {"kind": "adapter", "id": "ad1"},
            "cost",
            {
                "task_id": pick(rng, s["leases"]),
                "source": "proxy",
                "usd_milli": rng.randrange(400),
                "tokens_in": rng.randrange(50),
                "price_table": "t",
            },
        )
    if c == 16 and rng.random() < 0.08:
        return HUMAN, "close_problem", {"reason": "r"}
    return HUMAN, "hint", {"text": "填充"}


def foreign_op(rng: random.Random, k: Kernel, pid: str, other: str):
    """本题上的提议，引用换成别题的对象。"""
    o = slice_of(k.state, other)
    refs = {
        key: pick(rng, o[coll])
        for key, coll in (
            ("lease", "leases"),
            ("fact", "facts"),
            ("intent", "intents"),
            ("art", "artifacts"),
            ("hint", "hints"),
            ("request", "requests"),
        )
    }
    own = {"art": k.art(pid, "exec", f"x{len(k.events)}".encode())}
    usable = [op for op in cross_ops(own, {key: v or "none" for key, v in refs.items()}) if not _mentions(op, "none")]
    return rng.choice(usable) if usable else None


def _mentions(op, token) -> bool:
    actor, _, body = op
    return token in repr(body) or actor.get("session") == token


@pytest.mark.parametrize("seed", range(60))
def test_two_problems_interleaved_do_not_affect_each_other(seed):
    rng = random.Random(seed)
    k = Kernel()
    for pid in PIDS:
        assert k.open(pid) == "ok"
    accepted = rejected = crossed = 0
    for step in range(120):
        pid = rng.choice(PIDS)
        other = PIDS[1 - PIDS.index(pid)]
        cross = rng.random() < 0.2
        op = foreign_op(rng, k, pid, other) if cross else None
        cross = op is not None
        actor, kind, body = op or own_op(rng, k, pid)
        full = validate(k.state, actor, pid, kind, body, k.cfg, k.ts + 1)
        solo = validate(alone(k, pid), actor, pid, kind, body, k.cfg, k.ts + 1)
        if cross:
            assert isinstance(full, Reject), (step, kind, body, full)  # 引用别题对象：一律被拒
            crossed += 1
        else:
            assert full == solo, (step, kind, body, full, solo)  # a：裁决只取决于本题的切片
        code = k.submit(actor, pid, kind, body)
        accepted, rejected = accepted + isinstance(full, Ok), rejected + isinstance(full, Reject)
        assert (code in ("ok",) or "_" in code and code.split("_")[1].isdigit()) == isinstance(full, Ok)
        if step % 8 == 0 or step == 119:
            for p in PIDS:  # b：切片与派生视图不受别题事件影响
                solo_state = alone(k, p)
                assert slice_of(k.state, p) == slice_of(solo_state, p), (step, p)
                assert derived(k.state, p) == derived(solo_state, p), (step, p)
    assert accepted >= 10 and rejected >= 3 and crossed >= 3  # 测试没有空转
