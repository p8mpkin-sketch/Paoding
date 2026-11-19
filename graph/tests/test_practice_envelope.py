"""练习道信封（一句话开题设计 §4.4、§10 第 2 条；内核增量 13、15）。

变异测试：对一份合法的练习道开题逐字段变异，每一个都被 validate 拒绝（forbidden_op）；
同一提交体换成 lane = confirm 不受影响（人确认过）。信封的版本与摘要抄进事件体，重放不读策略。
"""

import copy
import dataclasses

import pytest
from conftest import CFG, HUMAN, Kernel

from paoding_graph.contract import PolicyError, load_policy
from paoding_graph.reducer import apply, empty_state

POLICY = {
    "version": 3,
    "allow": {"resources": ["net", "workspace"], "net_patterns": ["q*:*", "127.0.0.1:*"], "max_risk": "r0"},
    "judge": {"ids": ["exact_match"], "require_sealed": True},
    "budget": {"usd_milli_max": 500, "wall_s_max": 1800},
    "goal": {"max_attempts_max": 5},
}
PCFG = dataclasses.replace(CFG, practice=load_policy(POLICY))
SEALED = [{"vault": "kt-1", "digest": "d" * 64}]


def legal() -> dict:
    return {
        "title": "t",
        "origin": {"statement_ref": "$st", "materials": [], "draft": {"record": "$rec", "lane": "practice"}},
        "goal": {
            "statement": "g",
            "check": {"judge_id": "exact_match", "sealed": copy.deepcopy(SEALED)},
            "max_attempts": 5,
            "accept": "judge",
        },
        "scope": [{"resource": "net", "pattern": "q1:8080", "actions": ["connect"], "risk": "r0"}],
        "budget": {"usd_milli": 500, "wall_s": 1800, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "basic@1"},
        "judges": ["exact_match"],
    }


def submit(body: dict, cfg=PCFG, pid="p1"):
    k = Kernel(cfg)
    st = k.art(pid, "input", b"statement")
    rec = k.art(pid, "input", b"derivation")
    b = copy.deepcopy(body)
    b["origin"]["statement_ref"] = st
    if "draft" in b["origin"]:
        b["origin"]["draft"]["record"] = rec
    return k, k.submit(HUMAN, pid, "open_problem", b)


def _set(path: str, value):
    def f(b: dict) -> None:
        *head, last = path.split(".")
        x = b
        for p in head:
            x = x[int(p)] if p.isdigit() else x[p]
        if value is DELETE:
            del x[last]
        else:
            x[int(last) if last.isdigit() else last] = value

    return f


DELETE = object()
MUTATIONS = {
    "风险 r1": _set("scope.0.risk", "r1"),
    "风险 r2": _set("scope.0.risk", "r2"),
    "白名单外地址": _set("scope.0.pattern", "evil.example:443"),
    "信封外资源": _set("scope.0.resource", "fs"),
    "金额超练习上限": _set("budget.usd_milli", 501),
    "时长超练习上限": _set("budget.wall_s", 1801),
    "换判官": lambda b: (_set("goal.check.judge_id", "replay")(b), b.__setitem__("judges", ["replay"])),
    "去掉 sealed": _set("goal.check.sealed", DELETE),
    "sealed 为空": _set("goal.check.sealed", []),
    "尝试次数超上限": _set("goal.max_attempts", 6),
    "多一条白名单外规则": lambda b: b["scope"].append(
        {"resource": "net", "pattern": "10.0.0.1:22", "actions": ["connect"], "risk": "r0"}
    ),
}


def test_legal_practice_open_stamps_policy_and_replays():
    k, out = submit(legal())
    assert out == "ok"
    ev = k.events[-1]
    draft = ev["body"]["origin"]["draft"]
    assert draft["lane"] == "practice" and draft["policy"] == {"version": 3, "digest": PCFG.practice.digest}
    assert k.state["problems"]["p1"]["origin"]["draft"] == draft
    # 重放只读事件体：换掉策略（甚至卸掉）得到同一个状态
    st = empty_state()
    for e in k.events:
        st = apply(st, e)
    assert st == k.state


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_mutation_is_rejected_and_confirm_lane_is_not(name):
    body = legal()
    MUTATIONS[name](body)
    k, out = submit(body)
    assert out == "forbidden_op", name
    assert "p1" not in k.state["problems"]
    # 同一提交体走确认道：不受信封限制
    body["origin"]["draft"]["lane"] = "confirm"
    k, out = submit(body)
    assert out == "ok", name
    assert "policy" not in k.events[-1]["body"]["origin"]["draft"]


def test_reject_detail_names_every_violation():
    from paoding_graph.reducer import validate

    k = Kernel(PCFG)
    st = k.art("p1", "input", b"s")
    rec = k.art("p1", "input", b"r")
    body = legal()
    body["origin"].update(statement_ref=st, draft={"record": rec, "lane": "practice"})
    body["scope"][0]["risk"] = "r1"
    body["budget"]["usd_milli"] = 900
    r = validate(k.state, HUMAN, "p1", "open_problem", body, PCFG, k.ts + 1)
    assert r.code == "forbidden_op" and "练习道信封不许" in r.detail
    assert "r1" in r.detail and "900" in r.detail


def test_no_policy_loaded_means_no_practice_lane():
    _, out = submit(legal(), cfg=CFG)
    assert out == "forbidden_op"
    body = legal()
    body["origin"]["draft"]["lane"] = "confirm"
    assert submit(body, cfg=CFG)[1] == "ok"


def test_without_draft_is_unchanged():
    body = legal()
    del body["origin"]["draft"]
    body["scope"][0]["risk"] = "r2"
    k, out = submit(body)
    assert out == "ok" and "draft" not in k.events[-1]["body"]["origin"]


@pytest.mark.parametrize(
    "draft",
    [
        {"record": "$rec", "lane": "auto"},
        {"record": "$rec"},
        {"record": "$rec", "lane": "practice", "policy": {"version": 3, "digest": "0" * 64}},
    ],
)
def test_bad_draft_shapes(draft):
    body = legal()
    body["origin"]["draft"] = draft
    assert submit(body)[1] == "schema_error"


def test_record_must_exist_in_this_problem():
    k = Kernel(PCFG)
    st = k.art("p1", "input", b"s")
    body = legal()
    body["origin"].update(statement_ref=st, draft={"record": "a_999", "lane": "practice"})
    assert k.submit(HUMAN, "p1", "open_problem", body) == "unknown_ref"


def test_origin_extra_field_rejected():
    body = legal()
    body["origin"]["note"] = "x"
    assert submit(body)[1] == "schema_error"


@pytest.mark.parametrize(
    "bad",
    [
        {**POLICY, "extra": 1},
        {**POLICY, "version": 0},
        {**POLICY, "allow": {**POLICY["allow"], "max_risk": "r9"}},
        {**POLICY, "judge": {"ids": [], "require_sealed": True}},
        {**POLICY, "budget": {"usd_milli_max": -1, "wall_s_max": 1}},
        {**POLICY, "judge": {"ids": ["exact_match"], "require_sealed": "yes"}},
    ],
)
def test_policy_shape_checked_at_load(bad):
    with pytest.raises(PolicyError):
        load_policy(bad)


def test_digest_tracks_content():
    other = copy.deepcopy(POLICY)
    other["allow"]["net_patterns"].append("10.*:*")
    assert load_policy(other).digest != load_policy(POLICY).digest
    assert load_policy(copy.deepcopy(POLICY)).digest == load_policy(POLICY).digest
