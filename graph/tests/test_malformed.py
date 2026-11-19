"""畸形提议体（P1-4 的护栏）：validate 只在解析层接异常，所以要证明"输入再怪也不会从内核里抛出来"。

做法：先在一个铺好对象的内核上备齐每种操作的一条合法提议，再随机改坏它的提议体（删字段、把任意深度的
值换成别的类型），固定种子。每一条都要求：

1. validate 不抛异常，只返回 Ok 或 Reject；
2. 返回 Ok 时 apply 也不抛，得到的状态仍是可规范化的 JSON 值（能算状态哈希），重放稳定。

第 2 条是说：凡是 validate 放行的事件体，apply 一定吃得下。校验函数里解析层之外的异常不再被吞掉，
所以这条测试同时守着"收窄异常捕获"没有把输入错误漏成内核崩溃。
"""

import copy
import dataclasses
import random

import pytest
from conftest import ADAPTER, CFG, EXECUTOR, HUMAN, JUDGE, Kernel, explore, reason

from paoding_graph.cards import seen as seen_card
from paoding_graph.parse import BadBody, Obj
from paoding_graph.reducer import KINDS, Ok, Reject, apply, empty_state, validate
from paoding_graph.replay import replay, state_hash

SINAN = {"kind": "sinan", "id": "sn1"}
WATCHDOG = {"kind": "watchdog", "id": "wd"}
GRAPH = {"kind": "graph", "id": "graph"}
R = {"usd_milli": 100, "wall_s": 60}
JUNK = [
    None,
    True,
    False,
    0,
    -1,
    7,
    1.5,
    10**30,
    "",
    "x",
    "0" * 64,
    "goal",
    "f_1",
    "$0",
    [],
    {},
    [1],
    ["x"],
    [[]],
    [None],
    {"a": 1},
    {"judge_id": "replay"},
    {"usd_milli": "many"},
    float("1e308"),
]


def world():
    """一个各种对象都有的内核，以及每种操作的一条合法提议 (actor, pid, kind, body)。"""
    k = Kernel(dataclasses.replace(CFG, grants_runtime=True))
    k.open("p1", scope_risks=("r0", "r2"))
    boot = k.submit(SINAN, "p1", "lease", {"kind": "bootstrap", "holder": "sn1", "reserve": R, "ttl_s": 600})
    assert k.submit(SINAN, "p1", "release", {"lease": boot, "outcome": "nothing"}) == "ok"
    f = k.obs("p1", title="观察")
    a_exec = k.state["facts"][f]["grounds"][0]
    a_auth = k.art("p1", "authored", b"candidate")
    plain = k.submit(reason(), "p1", "add_intent", {"title": "走一步", "premises": [f], "risk": "r0", "budget": R})
    gated = k.submit(reason(), "p1", "add_intent", {"title": "要审批", "premises": [], "risk": "r2", "budget": R})
    lid = k.submit(
        SINAN, "p1", "lease", {"kind": "explore", "target": plain, "holder": "sn1", "reserve": R, "ttl_s": 600}
    )
    hint = k.submit(HUMAN, "p1", "hint", {"text": "提示"})
    req = k.submit(HUMAN, "p1", "request_judge", {"target": f, "judge_id": "replay"})
    a_judge = k.art("p1", "judge", b"evidence")
    st_in = k.art("p9", "input", b"statement p9")
    net = {"resource": "net", "pattern": "q7.lab:8443", "actions": ["connect"]}
    sreq = k.submit(explore(lid), "p1", "request_scope", {"rules": [net], "why": "要读接口"})
    # 外部时限待绑定的题（external-verdict §5.6）：bind_deadline 的合法样本
    st3 = k.art("p3", "input", b"statement p3")
    open3 = {
        "title": "t",
        "origin": {"statement_ref": st3, "materials": []},
        "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic"},
        "judges": ["exact_match"],
        "deadline": {"source": "external"},
    }
    assert k.submit(HUMAN, "p3", "open_problem", open3) == "ok"
    a_judge3 = k.art("p3", "judge", b"brief receipt")
    assert all(isinstance(x, str) and "_" in x for x in (f, plain, gated, lid, hint, req, a_judge, st_in))
    exec_meta = {
        "sandbox_id": "s",
        "base": "b",
        "baseline_ref": "r",
        "tool": "shell",
        "command": "true",
        "cwd": "/",
        "exit_code": 0,
        "touched": [],
        "started_at": 1,
        "ended_at": 2,
        "truncated": False,
    }
    cases = [
        (
            HUMAN,
            "p9",
            "open_problem",
            {
                "title": "t",
                "origin": {"statement_ref": st_in, "materials": []},
                "goal": {
                    "statement": "g",
                    "check": {
                        "judge_id": "exact_match",
                        "expect": {"d": "ab"},
                        "sealed": [{"vault": "v", "digest": "0" * 64}],
                    },
                    "max_attempts": 3,
                    "accept": "judge",
                },
                "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
                "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
                "env": {"base": "basic"},
                "judges": ["replay", "exact_match"],
                "deadline": {"source": "local", "at": 10**13},
            },
        ),
        (
            EXECUTOR,
            "p1",
            "register_artifact",
            {
                "hash": "1" * 64,
                "size": 3,
                "media_type": "text/plain",
                "class": "exec",
                "parents": [a_exec],
                "exec": exec_meta,
            },
        ),
        (
            ADAPTER,
            "p1",
            "register_artifact",
            {"hash": "2" * 64, "size": 0, "media_type": "text/plain", "class": "authored"},
        ),
        (
            explore(lid),
            "p1",
            "add_fact",
            {
                "title": "新观察",
                "summary": "s",
                "claim_type": "observation",
                "body_ref": a_auth,
                "check": {"judge_id": "replay", "expect": {"exit_code": 0}, "spec_ref": a_auth},
                "premises": [f],
                "grounds": [a_exec],
            },
        ),
        (explore(lid), "p1", "add_fact", {"title": "推断", "claim_type": "inference", "premises": [f]}),
        (
            reason(),
            "p1",
            "add_intent",
            {
                "title": "再走一步",
                "summary": "s",
                "premises": [f],
                "risk": "r2",
                "budget": {**R, "tokens": 5},
                "done": {"judge_id": "replay", "expect": {"x": 1}, "max_attempts": 2},
                "expected_gain": 0.4,
                "needs_scope": [{"resource": "target", "pattern": "x", "actions": ["write"], "risk": "r2"}],
                "touches": [{"rule": 0, "mode": "read"}],
            },
        ),
        (HUMAN, "p1", "request_judge", {"target": "goal", "judge_id": "exact_match", "candidate": a_auth}),
        (JUDGE, "p1", "judge_verdict", {"request": req, "result": "pass", "version": "1", "evidence": [a_judge]}),
        (JUDGE, "p1", "judge_verdict", {"request": req, "result": "inconclusive", "reason": "timeout", "version": "1"}),
        (JUDGE, "p1", "lease", {"kind": "judge", "target": req, "holder": "jr1", "reserve": R, "ttl_s": 60}),
        (SINAN, "p1", "renew", {"lease": lid, "ttl_s": 900}),
        (
            SINAN,
            "p1",
            "release",
            {"lease": lid, "outcome": "done", "transcript_ref": a_auth, "suggestions": ["下一步"]},
        ),
        (WATCHDOG, "p1", "expire_lease", {"lease": lid}),
        (HUMAN, "p1", "abandon_intent", {"intent": gated, "reason": "不做"}),
        (
            HUMAN,
            "p1",
            "approve",
            {"intent": gated, "decision": "approve", "seen": seen_card(k.state, "p1", "approval", gated)},
        ),
        (
            HUMAN,
            "p1",
            "approve",
            {
                "intent": gated,
                "decision": "deny",
                "reason": "不放行",
                "seen": seen_card(k.state, "p1", "approval", gated),
            },
        ),
        (HUMAN, "p1", "hint", {"text": "再看看", "about": f}),
        (HUMAN, "p1", "hint", {"close": hint}),
        (HUMAN, "p1", "profile_override", {"axis": "info", "value": "partial", "reason": "外部依赖"}),
        (
            ADAPTER,
            "p1",
            "cost",
            {
                "task_id": lid,
                "source": "proxy",
                "tokens_in": 5,
                "tokens_cached": 1,
                "tokens_out": 2,
                "usd_milli": 3,
                "wall_s": 1,
                "price_table": "t",
                "model": "m",
            },
        ),
        (HUMAN, "p1", "close_problem", {"reason": "收工", "seen": seen_card(k.state, "p1", "closeout", "p1")}),
        (GRAPH, "p1", "budget_mark", {"mark": 50, "axis": "usd_milli"}),
        (
            explore(lid),
            "p1",
            "request_scope",
            {"rules": [{**net, "pattern": "q8.lab:80"}], "why": "还要一台", "intent": plain},
        ),
        (
            HUMAN,
            "p1",
            "grant_scope",
            {"request": sreq, "decision": "approve", "risk": ["r2"], "seen": seen_card(k.state, "p1", "scope", sreq)},
        ),
        (
            HUMAN,
            "p1",
            "grant_scope",
            {"request": sreq, "decision": "deny", "reason": "不放", "seen": seen_card(k.state, "p1", "scope", sreq)},
        ),
        (HUMAN, "p1", "revoke_scope", {"rule": 1, "reason": "用不到了"}),
        (JUDGE, "p3", "bind_deadline", {"at": 10**13, "evidence": a_judge3}),
    ]
    return k, cases


def paths(v, at=()):
    """值里每一个位置（含容器本身）的路径。"""
    yield at
    if isinstance(v, dict):
        for key, x in v.items():
            yield from paths(x, at + (key,))
    elif isinstance(v, list):
        for n, x in enumerate(v):
            yield from paths(x, at + (n,))


def broken(rng: random.Random, body: dict) -> dict:
    """改坏一处或两处：删掉一个字段，或把某个位置的值换成别的东西。"""
    out = copy.deepcopy(body)
    for _ in range(rng.choice([1, 1, 2])):
        where = [p for p in paths(out) if p]
        if not where:
            return rng.choice([x for x in JUNK if isinstance(x, dict)])
        *head, last = rng.choice(where)
        node = out
        for key in head:
            node = node[key]
        if isinstance(node, dict) and rng.random() < 0.3:
            del node[last]
        elif isinstance(node, dict) and rng.random() < 0.1:
            node[rng.choice(["extra", "seen", "terminal", "producer", "profile", "card_hash"])] = rng.choice(JUNK)
        else:
            node[last] = copy.deepcopy(rng.choice(JUNK))
    return out


def test_every_kind_has_a_valid_case():
    """护栏自身不空转：每种操作都有合法样本，且在原样提交时确实被接受（expire 要等到期，单独看）。"""
    k, cases = world()
    assert {kind for _, _, kind, _ in cases} == set(KINDS)
    for actor, pid, kind, body in cases:
        ts = k.ts + (10**9 if kind == "expire_lease" else 1)
        r = validate(k.state, actor, pid, kind, body, k.cfg, ts)
        assert isinstance(r, Ok), (kind, body, r)


@pytest.mark.parametrize("seed", range(40))
def test_malformed_bodies_never_raise(seed):
    rng = random.Random(seed)
    k, cases = world()
    oks = rejects = 0
    for n in range(150):
        actor, pid, kind, body = rng.choice(cases)
        bad = broken(rng, body)
        ts = k.ts + rng.choice([1, 10**9])
        r = validate(k.state, actor, pid, kind, bad, k.cfg, ts)  # 1：不抛
        assert isinstance(r, (Ok, Reject)), (kind, bad, r)
        if isinstance(r, Reject):
            rejects += 1
            continue
        oks += 1
        ev = {
            "v": 1,
            "seq": k.state["seq"] + 1,
            "problem_id": pid,
            "ts": ts,
            "actor": actor,
            "kind": kind,
            "body": r.body,
            "idem_key": f"k{n}",
            "prev_hash": "0" * 64,
            "hash": "0" * 64,
        }
        after = apply(k.state, ev)  # 2：放行的事件体 apply 吃得下
        state_hash(after)  # 状态仍是可规范化的 JSON 值
        assert state_hash(apply(k.state, copy.deepcopy(ev))) == state_hash(after)
    assert rejects > 60 and oks > 5  # 两种结果都出现过


@pytest.mark.parametrize("body", [None, 0, "x", [], [{}], True])
def test_body_must_be_an_object(k, body):
    k.open()
    for kind in KINDS:
        r = validate(k.state, HUMAN, "p1", kind, body, k.cfg)
        assert isinstance(r, Reject) and r.code in ("schema_error", "forbidden_op"), (kind, r)


def test_kernel_bugs_are_not_disguised_as_schema_errors(k, monkeypatch):
    """解析层之外的异常原样抛出：内核自己的缺陷不该看起来像调用方的输入错误。"""
    from paoding_graph import reducer

    k.open()

    def boom(*a, **kw):
        raise KeyError("内核缺陷")

    monkeypatch.setattr(reducer.wk, "terminal", boom)
    with pytest.raises(KeyError):
        validate(k.state, HUMAN, "p1", "close_problem", {"reason": "r"}, k.cfg)


def test_obj_accessors():
    o = Obj({"s": "a", "n": 3, "f": 1.5, "l": ["x"], "o": {"k": 1}, "t": 7, "z": None})
    assert (o.string("s"), o.integer("n"), o.number("f"), o.strings("l"), o.child("o").integer("k")) == (
        "a",
        3,
        1.5,
        ["x"],
        1,
    )
    assert o.text("t") == "7" and o.string("missing", "d") == "d" and o.opt_string("z") is None
    assert o.array("z", None) == [] and o.integer("missing", 9) == 9
    for bad in (
        lambda: o.string("n"),
        lambda: o.req("missing"),
        lambda: o.integer("l"),
        lambda: o.integer("s"),
        lambda: o.number("s"),
        lambda: o.strings("o"),
        lambda: o.child("s"),
        lambda: o.text("o"),
        lambda: o.opt_string("n"),
        lambda: Obj([]),
        lambda: Obj({1: 2}),
        lambda: Obj({"b": True}).integer("b"),
        lambda: Obj({"x": float("nan")}).number("x"),
        lambda: Obj({"l": [1]}).strings("l"),
        lambda: Obj({"l": [{}]}).children("l")[0].req("k"),
    ):
        with pytest.raises(BadBody):
            bad()


def test_replay_of_world_is_stable():
    k, _ = world()
    assert state_hash(replay(k.events, apply, empty_state())) == state_hash(k.state)
