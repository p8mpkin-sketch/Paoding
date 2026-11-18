"""对照判据 N1 的内核侧（§3.3.3，从 M1 提前）：Check.control 的形状、引用、内容键、裁决复核与等级桥接。"""

import pytest
from conftest import HUMAN, JUDGE, explore

from paoding_graph import levels as lv
from paoding_graph import refmodel as rm


def controlled(k, ctl=None, title="o", claim_type="observation", pid="p1"):
    spec = k.art(pid, "authored", b"probe")
    inp = k.art(pid, "authored", b"target=bogus") if ctl is None else ctl
    return k.submit(
        explore(),
        pid,
        "add_fact",
        {
            "title": title,
            "summary": "",
            "claim_type": claim_type,
            "check": {"judge_id": "replay", "spec_ref": spec, "expect": {}, "control": {"inputs": [inp]}},
            "premises": [],
            "grounds": [k.art(pid, "exec", title.encode())],
        },
    )


def judge(k, fid, result, **extra):
    rid = k.submit(HUMAN, "p1", "request_judge", {"target": fid, "judge_id": "replay"})
    ev = k.art("p1", "judge", f"{rid}{result}".encode())
    body = {"request": rid, "result": result, "version": "1", "evidence": [ev], **extra}
    return rid, k.submit(JUDGE, "p1", "judge_verdict", body)


def test_observations_accept_a_control(k):
    k.open()
    fid = controlled(k)
    assert fid.startswith("f_")
    assert k.state["facts"][fid]["check"]["control"]["inputs"][0].startswith("a_")


def test_control_is_only_for_observations(k):
    k.open()
    assert controlled(k, claim_type="inference") == "schema_error"


def test_goal_and_done_checks_refuse_a_control(k):
    k.open()
    st = k.art("p2", "input", b"s")
    body = {
        "title": "t",
        "origin": {"statement_ref": st, "materials": []},
        "goal": {
            "statement": "g",
            "check": {"judge_id": "exact_match", "control": {"inputs": [st]}},
            "max_attempts": 3,
            "accept": "judge",
        },
        "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["replay", "exact_match"],
    }
    assert k.submit(HUMAN, "p2", "open_problem", body) == "schema_error"


@pytest.mark.parametrize(
    "control",
    [
        {},
        {"inputs": []},
        {"inputs": ["a_1", "a_1"]},
        {"inputs": ["a_1"], "params": {}},
        {"inputs": [f"a_{i}" for i in range(9)]},
    ],
)
def test_malformed_controls_are_schema_errors(k, control):
    k.open()
    body = {
        "title": "o",
        "summary": "",
        "claim_type": "observation",
        "check": {"judge_id": "replay", "expect": {}, "control": control},
        "premises": [],
        "grounds": [k.art("p1", "exec", b"o")],
    }
    assert k.submit(explore(), "p1", "add_fact", body) == "schema_error"


def test_control_inputs_must_exist_in_this_problem(k):
    k.open()
    k.open("p2")
    other = k.art("p2", "authored", b"elsewhere")
    assert controlled(k, ctl="a_999") == "unknown_ref"
    assert controlled(k, ctl=other) == "scope_mismatch"


def test_content_key_reads_control_inputs_by_hash(k):
    """同一份对照字节换个 id 登记，仍是同一条论断；换了对照字节就是另一条。"""
    k.open()
    a = controlled(k, ctl=k.art("p1", "authored", b"target=bogus"))
    b = controlled(k, ctl=k.art("p1", "authored", b"target=bogus"), title="o")
    c = controlled(k, ctl=k.art("p1", "authored", b"target=other"))
    assert a == b != c


def test_a_controlled_pass_needs_a_failing_control(k):
    k.open()
    fid = controlled(k)
    for extra in ({}, {"control_end": "pass"}, {"control_end": "not_run"}, {"control_end": "weird"}):
        assert judge(k, fid, "pass", **extra)[1] == "schema_error", extra
    rid, out = judge(k, fid, "pass", control_end="fail")
    assert out == "ok"
    [v] = k.state["verdicts"]
    assert v["controlled"] is True and v["control_end"] == "fail"
    assert lv.levels(k.state, "p1")[fid] == "E3"


def test_no_contrast_is_inconclusive_and_leaves_the_level(k):
    k.open()
    fid = controlled(k)
    before = lv.levels(k.state, "p1")[fid]
    rid, out = judge(k, fid, "inconclusive", reason="no_contrast", control_end="pass")
    assert out == "ok" and k.state["verdicts"] == []
    req = k.state["requests"][rid]
    assert (req["inconclusive"], req["control_end"]) == ("no_contrast", "pass")
    assert lv.levels(k.state, "p1")[fid] == before
    assert judge(k, fid, "inconclusive", reason="no_contrast", control_end="fail")[1] == "schema_error"


def test_uncontrolled_targets_refuse_control_fields(k):
    k.open()
    fid = k.obs()
    assert judge(k, fid, "pass", control_end="fail")[1] == "schema_error"
    assert judge(k, fid, "inconclusive", reason="no_contrast")[1] == "schema_error"
    assert judge(k, fid, "pass")[1] == "ok"


def test_only_controlled_observations_count_as_progress(k):
    """续期门的进展（§3.5.2）只认带对照的观察到 E3：桥接把 control 交给参考模型。"""
    k.open()
    plain = k.obs(title="plain")
    assert judge(k, plain, "pass")[1] == "ok"
    ctl = controlled(k, title="ctl")
    assert judge(k, ctl, "pass", control_end="fail")[1] == "ok"
    st, res = lv.compute(k.state, "p1")
    assert st.facts[ctl].control and not st.facts[plain].control
    assert rm.counts_as_progress(st, res, ctl) and not rm.counts_as_progress(st, res, plain)
    assert res.levels[plain] == res.levels[ctl] == "E3"
