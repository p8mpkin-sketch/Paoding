"""开放道只读白名单（地图 v0.10 Q36；开放道 §12 第 5 条；05 AC8.8）。

人在设置层维护、缺省空；开放道的扩权申请命中且动作只读时，图服务确定性自动批，事件体戳白名单版本。
自动批准的判定逐字段变异（地址不在单内、动作非只读、风险表给 r2、白名单换了、不是开放道），每种都落到人。
白名单空着时，申请的事件体与之前逐字节相同。
"""

from __future__ import annotations

import dataclasses

from conftest import CFG, HUMAN, Kernel
from test_open_lane import lease_solve, open_lane, solver
from test_scope_grants import settle, workspace_open

from paoding_graph import views
from paoding_graph import work as wk
from paoding_graph.reducer import ReadonlyAllow, grants
from paoding_graph.service import GRAPH_ACTOR

NET = {"resource": "net", "pattern": "docs.python.org:443", "actions": ["connect"]}
ALLOW = ReadonlyAllow(rows=(("net", "docs.python.org:443"), ("net", "*.wikipedia.org:443")), version=7, digest="a" * 64)
ON = dataclasses.replace(CFG, external_resources=frozenset({"net"}), grants_runtime=True, readonly_allow=ALLOW)


def asked(k: Kernel, rule: dict | None = None) -> str:
    lid = lease_solve(k)
    return k.submit(solver(lid), "p1", "request_scope", {"rules": [rule or NET], "why": "查文档"})


def granted(k: Kernel) -> list[dict]:
    return [r for r in k.state["problems"]["p1"]["scope"] if r["resource"] == "net"]


def test_a_hit_is_approved_by_the_graph_and_stamped():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    rid = asked(k)
    ev = k.events[-1]["body"]
    assert ev["readonly"] == {"version": 7, "digest": "a" * 64} and ev["auto"] is False and "blockers" not in ev
    assert ev["rules"][0]["risk"] == "r1"  # 风险表未命中：登记进只读白名单即标注为 r1，不按缺省 r2
    assert grants.followups(k.state, "p1") == [("grant_scope", {"request": rid, "via": "readonly"})]
    settle(k)
    g = k.events[-1]
    assert g["kind"] == "grant_scope" and g["actor"] == GRAPH_ACTOR
    assert g["body"]["via"] == "readonly" and g["body"]["readonly"] == ALLOW.stamp()
    assert [r["pattern"] for r in granted(k)] == ["docs.python.org:443"]
    assert "scope_granted" in [i["item"] for i in wk.closeout_items(k.state, "p1")]  # 自动批的也进四顾
    card = views.card(k.state, "p1", "scope", rid, ON)
    assert card["display"]["readonly"] == ALLOW.stamp() and card["display"]["decision"]["via"] == "readonly"


def test_wildcard_rows_match_by_fnmatch():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    asked(k, {**NET, "pattern": "en.wikipedia.org:443"})
    settle(k)
    assert [r["pattern"] for r in granted(k)] == ["en.wikipedia.org:443"]


def _falls_to_a_human(k: Kernel, rid: str, why: str) -> None:
    body = k.events[-1]["body"]
    assert "readonly" not in body and any(why in b for b in body["blockers"]), body
    settle(k)
    assert granted(k) == [] and k.state["scope_requests"][rid]["status"] == "pending"
    assert k.submit(GRAPH_ACTOR, "p1", "grant_scope", {"request": rid, "via": "readonly"}) == "forbidden_op"


def test_an_address_outside_the_list_goes_to_a_human():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    _falls_to_a_human(k, asked(k, {**NET, "pattern": "evil.example:443"}), "不在只读白名单里")


def test_the_port_is_part_of_the_match():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    _falls_to_a_human(k, asked(k, {**NET, "pattern": "docs.python.org:22"}), "不在只读白名单里")


def test_a_risk_table_r2_beats_the_list():
    table = ({"resource": "net", "pattern": "docs.*:*", "actions": ["connect"], "risk": "r2"},)
    k = Kernel(dataclasses.replace(ON, risk_table=table))
    assert open_lane(k) == "ok"
    _falls_to_a_human(k, asked(k), "风险表给 r2")


def test_a_risk_table_hit_below_r2_keeps_its_own_risk():
    table = ({"resource": "net", "pattern": "docs.*:*", "actions": ["connect"], "risk": "r0"},)
    k = Kernel(dataclasses.replace(ON, risk_table=table))
    assert open_lane(k) == "ok"
    asked(k)
    assert k.events[-1]["body"]["rules"][0]["risk"] == "r0"
    settle(k)
    assert granted(k)[0]["risk"] == "r0"


def test_non_readonly_actions_go_to_a_human(monkeypatch):
    # 今天 net 只有 connect；登记一个会写的动作（如以后的提交端点），命中白名单也照样出卡
    from paoding_graph import resources

    monkeypatch.setitem(
        resources.RESOURCE_REQUESTABLE,
        "net",
        (resources.RESOURCE_REQUESTABLE["net"][0], frozenset({"connect", "post"})),
    )
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    _falls_to_a_human(k, asked(k, {**NET, "actions": ["connect", "post"]}), "不是只读")


def test_a_changed_list_between_request_and_grant_goes_to_a_human():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    rid = asked(k)
    k.cfg = dataclasses.replace(ON, readonly_allow=dataclasses.replace(ALLOW, version=8, digest="b" * 64))
    assert k.submit(GRAPH_ACTOR, "p1", "grant_scope", {"request": rid, "via": "readonly"}) == "forbidden_op"
    k.cfg = dataclasses.replace(ON, readonly_allow=None)
    assert k.submit(GRAPH_ACTOR, "p1", "grant_scope", {"request": rid, "via": "readonly"}) == "forbidden_op"
    assert k.state["scope_requests"][rid]["status"] == "pending"


def test_the_strict_lane_does_not_use_the_list():
    k = Kernel(ON)
    workspace_open(k)
    rid = k.submit(
        {"kind": "adapter", "id": "a", "role": "explore", "session": "s1"},
        "p1",
        "request_scope",
        {"rules": [NET], "why": "x"},
    )
    body = k.events[-1]["body"]
    assert "readonly" not in body and "不是开放道的任务" in body["blockers"]
    assert k.submit(GRAPH_ACTOR, "p1", "grant_scope", {"request": rid, "via": "readonly"}) == "forbidden_op"


def test_an_empty_list_leaves_the_request_body_unchanged():
    bodies = []
    for allow in (None, dataclasses.replace(ALLOW, rows=())):
        k = Kernel(dataclasses.replace(ON, readonly_allow=allow))
        assert open_lane(k) == "ok"
        asked(k)
        bodies.append(k.events[-1]["body"])
    assert bodies[0] == bodies[1]
    assert "readonly" not in bodies[0] and bodies[0]["rules"][0]["risk"] == "r2"
    assert not any("只读" in b for b in bodies[0]["blockers"])


def test_a_human_can_still_deny_or_revoke_what_the_list_would_allow():
    k = Kernel(ON)
    assert open_lane(k) == "ok"
    asked(k)
    settle(k)
    assert k.submit(HUMAN, "p1", "revoke_scope", {"rule": 1, "reason": "不要了"}) == "ok"
    assert not wk.active([r for r in k.state["problems"]["p1"]["scope"] if r["resource"] == "net"])
