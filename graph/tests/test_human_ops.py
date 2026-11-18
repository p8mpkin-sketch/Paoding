"""异议 003：内核补齐 M0 的两项人的操作——画像事后覆盖（profile_override）与带理由的拒绝。"""
from conftest import HUMAN, Kernel, reason

from paoding_graph import work as wk
from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

R = {"usd_milli": 100, "wall_s": 60}


def test_profile_override_keeps_trace(k):
    k.open(resource="remote")          # conftest 的 CFG 把 remote 登记为外部资源
    assert k.state["problems"]["p1"]["profile"]["info"] == "partial"
    assert k.submit(HUMAN, "p1", "profile_override", {"axis": "info", "value": "complete",
                                                      "reason": "题目环境在本机，内容不会变"}) == "ok"
    p = k.state["problems"]["p1"]
    assert p["profile"]["info"] == "complete" and p["derived_profile"]["info"] == "partial"
    [o] = p["profile_overrides"]
    assert (o["axis"], o["value"], o["derived"], o["by"]) == ("info", "complete", "partial", "cz")


def test_profile_override_rejects(k):
    k.open()
    sub = lambda b: k.submit(HUMAN, "p1", "profile_override", b)       # noqa: E731
    assert sub({"axis": "info", "value": "complete"}) == "schema_error"                     # 无理由
    assert sub({"axis": "mood", "value": "x", "reason": "r"}) == "schema_error"
    assert sub({"axis": "judge", "value": "easy", "reason": "r"}) == "schema_error"
    assert k.submit(reason(), "p1", "profile_override", {"axis": "info", "value": "complete",
                                                         "reason": "r"}) == "forbidden_op"  # 只许人
    assert "profile_overrides" not in k.state["problems"]["p1"]


def _needs_human(k):
    k.open(scope_risks=("r0", "r2"))
    lid = k.submit({"kind": "sinan", "id": "sn1"}, "p1", "lease", {"kind": "bootstrap", "holder": "sn1",
                                                                    "reserve": R, "ttl_s": 600})
    k.submit({"kind": "sinan", "id": "sn1"}, "p1", "release", {"lease": lid, "outcome": "nothing"})
    iid = k.submit(reason(), "p1", "add_intent", {"title": "改写后重启", "premises": [], "risk": "r2", "budget": R})
    assert wk.intent_status(k.state, "p1", iid) == "needs_human"
    return iid


def test_deny_requires_reason_and_keeps_it(k):
    iid = _needs_human(k)
    assert k.decide("p1", iid, "deny") == "schema_error"
    assert k.decide("p1", iid, "deny", reason="  ") == "schema_error"
    assert k.decide("p1", iid, "deny", reason="回退不清楚") == "ok"
    assert wk.intent_status(k.state, "p1", iid) == "abandoned"
    assert k.state["decision_reasons"][iid]["reason"] == "回退不清楚"


def test_approve_reason_optional(k):
    iid = _needs_human(k)
    assert k.decide("p1", iid) == "ok"
    assert iid not in k.state.get("decision_reasons", {})


def test_replay_stable(k):
    iid = _needs_human(k)
    k.submit(HUMAN, "p1", "profile_override", {"axis": "judge", "value": "costly", "reason": "判官要起容器"})
    assert k.decide("p1", iid, "deny", reason="r") == "ok"
    assert state_hash(replay(k.events, apply, empty_state())) == state_hash(k.state)
