"""外部裁决一期的内核部分（docs/design/external-verdict/ §5.2、§5.3、§5.6、§11 一期）。

- 开题三条检查：判官快照有连接器、判据带 binding 且连接器一致、max_attempts 不超平台额度；变异逐条被拒。
- goal.authority 是派生量：external 时写进事件体，local 时事件体与旧版逐字相同；提交时不接受。
- 待定：延迟判官的 inconclusive(pending) 带 recheck_at，不进裁决序列、等级不变；/work 派生带 not_before 的复判，
  同一候选的复判不消耗次数；回执通过后 Goal 到 E3、终态 solved。
- deadline：local 开题即给；external 开题时附出处给，或留待 bind_deadline 绑定一次。
"""

import copy
import dataclasses

import pytest
from conftest import CFG, HUMAN, JUDGE, Kernel

from paoding_graph import levels as lv
from paoding_graph import work as wk
from paoding_graph.reducer.problem import authority_of

CONN = {"id": "plat", "version": "2", "digest": "c" * 64}
EXT = {
    "version": "1",
    "grade": "decisive",
    "kind": "deferred",
    "max_cost": 0.0,
    "authority": "external",
    "connector": CONN,
}
XCFG = dataclasses.replace(CFG, judges={**CFG.judges, "ext": EXT, "ext_unloaded": {**EXT, "connector": None}})
XCFG.judges["ext_unloaded"].pop("connector")
SINAN = {"kind": "sinan", "id": "sn1"}


def body(**over) -> dict:
    b = {
        "title": "平台任务 T-17",
        "origin": {"statement_ref": "$st", "materials": []},
        "goal": {
            "statement": "平台回执为通过",
            "check": {"judge_id": "ext", "binding": {"connector": "plat", "task": "T-17", "max_submissions": 3}},
            "max_attempts": 3,
            "accept": "judge",
        },
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 14_400, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic"},
        "judges": ["ext", "exact_match"],
    }
    b.update(over)
    return b


def opened(b=None, cfg=XCFG, pid="p1"):
    k = Kernel(cfg)
    st = k.art(pid, "input", b"statement")
    b = copy.deepcopy(b or body())
    b["origin"]["statement_ref"] = st
    return k, k.submit(HUMAN, pid, "open_problem", b)


# ---------- 开题 ----------


def test_external_open_derives_authority_and_deferred_profile():
    k, r = opened()
    assert r == "ok"
    p = k.state["problems"]["p1"]
    assert p["goal"]["authority"] == "external"
    assert p["goal"]["check"]["binding"] == {"connector": "plat", "task": "T-17", "max_submissions": 3}
    assert p["judge_snapshot"]["ext"]["connector"] == CONN  # 档案摘要随开题进快照，重放不读档案
    assert p["profile"]["judge"] == "deferred"  # 画像推导不变：kind=deferred → deferred
    assert "deadline" not in p and "wall_mode" not in p


def test_local_open_body_unchanged():
    k = Kernel(XCFG)
    k.open("p1")
    ev = k.events[-1]["body"]
    assert "authority" not in ev["goal"] and "binding" not in ev["goal"]["check"]
    assert not {"deadline", "wall_mode", "life_s"} & set(ev)


def _set(path, value):
    def f(b):
        *head, last = path.split(".")
        x = b
        for p in head:
            x = x[p]
        if value is KeyError:
            del x[last]
        else:
            x[last] = value

    return f


MUTATIONS = {
    "连接器未加载": (_set("goal.check.judge_id", "ext_unloaded"), "unknown_ref"),
    "缺 binding": (_set("goal.check.binding", KeyError), "schema_error"),
    "连接器不符": (_set("goal.check.binding.connector", "other"), "schema_error"),
    "超平台额度": (_set("goal.max_attempts", 4), "schema_error"),
    "binding 缺键": (_set("goal.check.binding.task", KeyError), "schema_error"),
    "额度非正": (_set("goal.check.binding.max_submissions", 0), "schema_error"),
    "提交 authority": (_set("goal.authority", "local"), "schema_error"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_open_mutations_rejected(name):
    mutate, code = MUTATIONS[name]
    b = body()
    if name == "连接器未加载":
        b["judges"] = ["ext_unloaded"]
        b["goal"]["check"]["judge_id"] = "ext_unloaded"
    else:
        mutate(b)
    _, r = opened(b)
    assert r == code, name


def test_binding_only_for_external_goal():
    b = body()
    b["goal"]["check"]["judge_id"] = "exact_match"
    _, r = opened(b)
    assert r == "schema_error"


def test_binding_not_accepted_on_fact_check():
    k = Kernel(XCFG)
    k.open("p1")
    g = k.art("p1", "exec", b"o")
    r = k.submit(
        {"kind": "adapter", "id": "ad1", "session": "L1", "role": "explore"},
        "p1",
        "add_fact",
        {
            "title": "o",
            "summary": "",
            "claim_type": "observation",
            "premises": [],
            "grounds": [g],
            "check": {"judge_id": "replay", "binding": {"connector": "plat", "task": "T", "max_submissions": 1}},
        },
    )
    assert r == "schema_error"


def test_authority_of():
    assert authority_of(EXT, "judge") == "external"
    assert authority_of(CFG.judges["exact_match"], "judge") == "local"
    assert authority_of(EXT, "human") == "human"


# ---------- 待定 ----------


def _judge_once(k, rid, result, **extra):
    a = k.art("p1", "judge", f"receipt {result} {extra}".encode())
    lid = k.submit(
        JUDGE,
        "p1",
        "lease",
        {"kind": "judge", "target": rid, "holder": "jr1", "reserve": {"usd_milli": 1, "wall_s": 60}, "ttl_s": 60},
    )
    v = k.submit(
        JUDGE, "p1", "judge_verdict", {"request": rid, "result": result, "version": "1", "evidence": [a], **extra}
    )
    k.submit(JUDGE, "p1", "release", {"lease": lid, "outcome": "done"})
    return v


def test_pending_then_pass_solves_without_spending_attempts():
    b = body()
    b["goal"]["max_attempts"] = 1
    b["goal"]["check"]["binding"]["max_submissions"] = 1
    k, r = opened(b)
    assert r == "ok"
    cand = k.art("p1", "input", b"FLAG-1")
    rid = k.submit(HUMAN, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": cand})
    assert _judge_once(k, rid, "inconclusive", reason="pending", recheck_at=5_000) == "ok"
    assert k.state["requests"][rid]["recheck_at"] == 5_000
    assert lv.levels(k.state, "p1")["goal"] == "E0"  # 待定不进裁决序列，等级不变
    items = [i for i in wk.work(k.state, "p1") if i["kind"] == "rejudge"]
    assert items == [
        {
            "kind": "rejudge",
            "target": "goal",
            "judge": "ext",
            "version": "1",
            "candidate": cand,
            "not_before": 5_000,
            "why": "pending",
        }
    ]
    assert not any(i.get("why") == "stalled" for i in wk.work(k.state, "p1"))  # 等回执不是停滞
    # 复判：同一候选再请求一次，不消耗次数（max_attempts=1 也放行）
    rid2 = k.submit(SINAN, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": cand})
    assert rid2.startswith("j_")
    assert not [i for i in wk.work(k.state, "p1") if i["kind"] == "rejudge"]  # 有更新的请求，不再派生
    assert _judge_once(k, rid2, "pass", reason="ok") == "ok"
    assert lv.levels(k.state, "p1")["goal"] == "E3"
    assert wk.terminal(k.state, "p1") == "solved"
    # 换一个候选就是新的提交，受平台额度约束
    other = k.art("p1", "input", b"FLAG-2")
    assert (
        k.submit(HUMAN, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": other})
        == "quota_exceeded"
    )


def test_pending_shape_rules():
    k, _ = opened()
    cand = k.art("p1", "input", b"F")
    rid = k.submit(HUMAN, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": cand})
    assert _judge_once(k, rid, "inconclusive", reason="pending") == "schema_error"  # 缺 recheck_at
    assert _judge_once(k, rid, "inconclusive", reason="pending", recheck_at=0) == "schema_error"
    assert _judge_once(k, rid, "inconclusive", reason="timeout", recheck_at=9) == "schema_error"  # 只随 pending
    assert _judge_once(k, rid, "fail", reason="pending", recheck_at=9) == "schema_error"


def test_pending_only_for_deferred_judges():
    k = Kernel(XCFG)
    k.open("p1")
    cand = k.art("p1", "input", b"F")
    rid = k.submit(HUMAN, "p1", "request_judge", {"target": "goal", "judge_id": "exact_match", "candidate": cand})
    assert _judge_once(k, rid, "inconclusive", reason="pending", recheck_at=9) == "schema_error"


# ---------- deadline ----------


def test_deadline_shapes():
    for dl, code in [
        ({"source": "local", "at": 10**12}, "ok"),
        ({"source": "local"}, "schema_error"),
        ({"source": "external"}, "ok"),
        ({"source": "external", "at": 10**12}, "schema_error"),  # 开题时给 at 必须附出处
        ({"source": "remote"}, "schema_error"),
        ({"source": "local", "at": -1}, "schema_error"),
        ({"source": "local", "at": 1, "extra": 1}, "schema_error"),
    ]:
        _, r = opened(body(deadline=dl))
        assert r == code, dl


def test_deadline_bound_at_open_needs_input_notice():
    k = Kernel(XCFG)
    st = k.art("p1", "input", b"statement")
    notice = k.art("p1", "input", b"resource notice")
    b = body(deadline={"source": "external", "at": 10**12, "bound_by": notice})
    b["origin"]["statement_ref"] = st
    assert k.submit(HUMAN, "p1", "open_problem", b) == "ok"
    assert k.state["problems"]["p1"]["deadline"] == {"source": "external", "at": 10**12, "bound_by": notice}
    # 已经绑了：bind_deadline 不再接受
    ev = k.art("p1", "judge", b"brief")
    assert k.submit(JUDGE, "p1", "bind_deadline", {"at": 10**13, "evidence": ev}) == "forbidden_op"


def test_bind_deadline_once():
    k, r = opened(body(deadline={"source": "external"}))
    assert r == "ok"
    inp = k.art("p1", "input", b"x")
    ev = k.art("p1", "judge", b"brief receipt")
    assert k.submit(HUMAN, "p1", "bind_deadline", {"at": 10**12, "evidence": ev}) == "forbidden_op"  # 只有判官令牌
    assert k.submit(JUDGE, "p1", "bind_deadline", {"at": 10**12, "evidence": inp}) == "inadmissible_class"
    assert k.submit(JUDGE, "p1", "bind_deadline", {"at": 0, "evidence": ev}) == "schema_error"
    assert k.submit(JUDGE, "p1", "bind_deadline", {"at": 10**12, "evidence": ev}) == "ok"
    assert k.state["problems"]["p1"]["deadline"] == {"source": "external", "at": 10**12, "bound_by": ev}
    assert k.submit(JUDGE, "p1", "bind_deadline", {"at": 10**13, "evidence": ev}) == "forbidden_op"  # 绑定一次即固定


def test_bind_deadline_needs_external_deadline():
    k, _ = opened()
    ev = k.art("p1", "judge", b"r")
    assert k.submit(JUDGE, "p1", "bind_deadline", {"at": 10**12, "evidence": ev}) == "forbidden_op"
    k2, _ = opened(body(deadline={"source": "local", "at": 10**12}))
    ev2 = k2.art("p1", "judge", b"r")
    assert k2.submit(JUDGE, "p1", "bind_deadline", {"at": 10**12, "evidence": ev2}) == "forbidden_op"


def test_wall_mode_spend_is_stamped():
    k, r = opened(cfg=dataclasses.replace(XCFG, wall_mode="spend", life_s=3600))
    assert r == "ok"
    p = k.state["problems"]["p1"]
    assert (p["wall_mode"], p["life_s"]) == ("spend", 3600)


def test_judge_token_can_only_repeat_existing_request():
    """判官运行器补复判（unstable 或 pending）用的是判官令牌：只能重复已有请求，不能自己挑候选。

    一期之前 _who 不许判官令牌 request_judge，runner 的复判一直被拒（forbidden_op），这条把它补上并收窄。"""
    k, _ = opened()
    cand = k.art("p1", "input", b"F")
    other = k.art("p1", "input", b"G")
    assert (
        k.submit(JUDGE, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": cand})
        == "forbidden_op"
    )
    k.submit(HUMAN, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": cand})
    assert k.submit(JUDGE, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": cand}).startswith(
        "j_"
    )
    assert (
        k.submit(JUDGE, "p1", "request_judge", {"target": "goal", "judge_id": "ext", "candidate": other})
        == "forbidden_op"
    )
