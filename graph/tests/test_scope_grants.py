"""运行时扩权（设计 docs/design/runtime-grants/ §4、§11；§12 第一步）。

申请不是授权；批准只有人与确定性的练习道白名单两种来源；图服务的身份不是信任来源；风险不信自报；
Problem.scope 只追加，撤销留在原位；画像随扩权重算并写进事件体；重放只读事件体。
"""

import copy
import dataclasses

import pytest
from conftest import CFG, HUMAN, Kernel, explore, reason

from paoding_graph import work as wk
from paoding_graph.cards import seen as seen_card
from paoding_graph.contract import load_policy
from paoding_graph.reducer import apply, empty_state, grants
from paoding_graph.service import GRAPH_ACTOR

NET = {"resource": "net", "pattern": "q7.lab:8443", "actions": ["connect"]}
TABLE = ({"resource": "net", "pattern": "q*.lab:*", "actions": ["connect"], "risk": "r0"},)
POLICY = {
    "version": 3,
    "allow": {"resources": ["net", "workspace"], "net_patterns": ["q*:*", "q*.lab:*"], "max_risk": "r0"},
    "judge": {"ids": ["exact_match"], "require_sealed": True},
    "budget": {"usd_milli_max": 500, "wall_s_max": 1800},
    "goal": {"max_attempts_max": 5},
}
ON = dataclasses.replace(
    CFG, external_resources=frozenset({"net"}), grants_runtime=True, risk_table=TABLE, practice=load_policy(POLICY)
)
R = {"usd_milli": 100, "wall_s": 60}


def settle(k):
    """服务层每批之后做的事：按轮追加图服务自己的扩权事件。"""
    for _ in range(4):
        todo = grants.followups(k.state, "p1")
        if not todo:
            return
        for kind, body in todo:
            k.submit(GRAPH_ACTOR, "p1", kind, body)


def workspace_open(k, lane=None, usd=500):
    st = k.art("p1", "input", b"s")
    origin = {"statement_ref": st, "materials": []}
    if lane:
        origin["draft"] = {"record": k.art("p1", "input", b"r"), "lane": lane}
    body = {
        "title": "t",
        "origin": origin,
        "goal": {
            "statement": "g",
            "check": {"judge_id": "exact_match", "sealed": [{"vault": "v", "digest": "d" * 64}]},
            "max_attempts": 5,
            "accept": "judge",
        },
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": usd, "wall_s": 1800, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "basic@1"},
        "judges": ["exact_match"],
    }
    assert k.submit(HUMAN, "p1", "open_problem", body) == "ok"


def ask(k, rule=None, actor=None, **extra):
    return k.submit(actor or explore(), "p1", "request_scope", {"rules": [rule or NET], "why": "读接口", **extra})


def grant(k, rid, decision="approve", **extra):
    body = {"request": rid, "decision": decision, "seen": seen_card(k.state, "p1", "scope", rid), **extra}
    return k.submit(HUMAN, "p1", "grant_scope", body)


@pytest.fixture
def k():
    return Kernel(ON)


# ---------- 申请 ----------


def test_runtime_off_means_not_enabled():
    k = Kernel(dataclasses.replace(ON, grants_runtime=False))
    workspace_open(k)
    assert ask(k) == "not_enabled"


def test_risk_comes_from_the_table_not_the_request(k):
    workspace_open(k)
    assert ask(k, {**NET, "risk": "r0"}) == "schema_error"  # 自报风险一律不收
    rid = ask(k)
    assert k.state["scope_requests"][rid]["rules"][0]["risk"] == "r0"  # 表命中
    other = ask(k, {**NET, "pattern": "evil.example:443"})
    assert k.state["scope_requests"][other]["rules"][0]["risk"] == "r2"  # 未命中按 r2


@pytest.mark.parametrize(
    "rule",
    [
        {**NET, "pattern": "q7.lab"},  # 端口必须写明
        {**NET, "pattern": "q7.lab:0"},
        {**NET, "pattern": "q7.lab:70000"},
        {**NET, "pattern": "*:443"},  # 不许通配
        {**NET, "actions": ["write"]},
        {**NET, "actions": []},
        {**NET, "resource": "workspace", "pattern": ""},
        {**NET, "resource": "fs"},
        {**NET, "extra": 1},
    ],
)
def test_bad_rule_shapes(k, rule):
    workspace_open(k)
    assert ask(k, rule) == "schema_error"


def test_why_required_and_duplicates_refused(k):
    workspace_open(k)
    assert k.submit(explore(), "p1", "request_scope", {"rules": [NET]}) == "schema_error"
    assert k.submit(explore(), "p1", "request_scope", {"rules": [NET, NET], "why": "x"}) == "schema_error"
    ask(k)
    assert ask(k) == "schema_error"  # 已在申请中


def test_who_may_ask(k):
    workspace_open(k)
    judge = {"kind": "judge", "id": "jr1"}
    idler = {"kind": "adapter", "id": "ad1", "session": "I1", "role": "idler"}
    assert ask(k, actor=judge) == "forbidden_op"
    assert ask(k, actor=idler) == "forbidden_op"
    assert ask(k, actor=reason()).startswith("r_")
    assert ask(k, {**NET, "pattern": "q8.lab:80"}, actor=HUMAN).startswith("r_")


def test_quota_per_session(k):
    workspace_open(k)
    for n in range(ON.scope_request_quota):
        assert ask(k, {**NET, "pattern": f"q{n}.lab:80"}).startswith("r_")
    assert ask(k, {**NET, "pattern": "q9.lab:80"}) == "quota_exceeded"
    assert ask(k, {**NET, "pattern": "q9.lab:80"}, actor=explore("L2")).startswith("r_")


# ---------- 人批 ----------


def test_human_grant_appends_rule_and_reprofiles(k):
    workspace_open(k)
    assert k.state["problems"]["p1"]["profile"]["info"] == "complete"
    rid = ask(k, {**NET, "pattern": "evil.example:443"})
    assert wk.work(k.state, "p1")[-1] == {"kind": "human", "target": rid, "why": "scope_request"}
    assert grant(k, rid) == "ok"
    p = k.state["problems"]["p1"]
    rule = p["scope"][1]
    assert rule["pattern"] == "evil.example:443" and rule["risk"] == "r2"
    assert rule["granted"] == {"seq": k.state["seq"], "by": "cz", "request": rid}
    assert p["profile"] == {"info": "partial", "judge": "hard", "reversibility": "r2"}
    assert k.state["scope_requests"][rid]["status"] == "granted"
    assert {"kind": "human", "target": rid, "why": "scope_request"} not in wk.work(k.state, "p1")


def test_human_may_only_raise_risk(k):
    workspace_open(k)
    rid = ask(k, {**NET, "pattern": "evil.example:443"})  # 表外：r2
    assert grant(k, rid, risk=["r0"]) == "schema_error"
    rid2 = ask(k)  # 表内：r0
    assert grant(k, rid2, risk=["r1"]) == "ok"
    assert k.state["problems"]["p1"]["scope"][-1]["risk"] == "r1"


def test_deny_needs_reason_and_blocks_reasking(k):
    workspace_open(k)
    rid = ask(k)
    assert grant(k, rid, "deny") == "schema_error"
    assert grant(k, rid, "deny", reason="不需要") == "ok"
    assert k.state["scope_requests"][rid]["status"] == "denied"
    assert len(k.state["problems"]["p1"]["scope"]) == 1
    assert ask(k) == "forbidden_op"  # 同题内被拒过的规则不再申请
    assert grant(k, rid, reason="x") == "schema_error"  # 已有结果


def test_stale_scope_card(k):
    workspace_open(k)
    rid = ask(k)
    old = seen_card(k.state, "p1", "scope", rid)
    other = ask(k, {**NET, "pattern": "q8.lab:80"})
    assert grant(k, other) == "ok"  # 现有范围变了，旧卡过期
    body = {"request": rid, "decision": "approve", "seen": old}
    assert k.submit(HUMAN, "p1", "grant_scope", body) == "stale_view"


def test_already_held_rule_is_not_requested_again(k):
    workspace_open(k)
    assert grant(k, ask(k)) == "ok"
    assert ask(k) == "schema_error"


# ---------- 图服务的批准：判定在 validate 里重算 ----------


def test_graph_cannot_grant_by_identity_alone(k):
    """伪造一条 actor = graph 的批准：判定不成立就 forbidden_op（§11 第 2 条）。"""
    workspace_open(k)  # 不是练习道
    rid = ask(k)
    assert not k.state["scope_requests"][rid]["auto"]
    for via in ("auto", "approval"):
        assert k.submit(GRAPH_ACTOR, "p1", "grant_scope", {"request": rid, "via": via}) == "forbidden_op"
    body = {"request": rid, "via": "auto", "decision": "approve"}
    assert k.submit(GRAPH_ACTOR, "p1", "grant_scope", body) == "schema_error"


def test_practice_whitelist_grants_automatically(k):
    workspace_open(k, lane="practice")
    rid = ask(k)
    req = k.state["scope_requests"][rid]
    assert req["auto"] and k.events[-1]["body"]["policy"]["digest"] == ON.practice.digest
    assert rid not in wk.pending_for_human(k.state, "p1")
    settle(k)
    ev = k.events[-1]
    assert ev["kind"] == "grant_scope" and ev["actor"]["kind"] == "graph" and ev["body"]["via"] == "auto"
    assert ev["body"]["policy"] == {"version": 3, "digest": ON.practice.digest}
    assert k.state["problems"]["p1"]["scope"][-1]["granted"]["by"] == "graph"


AUTO_MUTATIONS = {
    "白名单外地址": ({"pattern": "evil.example:443"}, ON, "practice", 500),
    "风险表给 r1": ({}, dataclasses.replace(ON, risk_table=({**TABLE[0], "risk": "r1"},)), "practice", 500),
    "确认道": ({}, ON, "confirm", 500),
    "不带出处账": ({}, ON, None, 500),
    "设置关了自动批准": ({}, dataclasses.replace(ON, grants_auto_practice=False), "practice", 500),
}


@pytest.mark.parametrize("name", sorted(AUTO_MUTATIONS))
def test_every_auto_mutation_falls_to_a_human(name):
    """§11 第 1 条：对一条合法的自动批准申请逐项变异，每一种都必须落到人。"""
    change, cfg, lane, usd = AUTO_MUTATIONS[name]
    k = Kernel(cfg)
    workspace_open(k, lane=lane, usd=usd)
    rid = ask(k, {**NET, **change})
    assert not k.state["scope_requests"][rid]["auto"], name
    assert rid in wk.pending_for_human(k.state, "p1")
    settle(k)
    assert k.state["scope_requests"][rid]["status"] == "pending"


def test_envelope_changed_since_open_falls_to_a_human():
    k = Kernel(ON)
    workspace_open(k, lane="practice")
    newer = copy.deepcopy(POLICY)
    newer["version"] = 4
    k.cfg = dataclasses.replace(ON, practice=load_policy(newer))
    rid = ask(k)
    assert not k.state["scope_requests"][rid]["auto"]
    assert "信封已不是开题时签的那一份" in k.events[-1]["body"]["blockers"]


def test_auto_judgement_is_rechecked_at_grant_time():
    """申请时判为自动，批准前信封换了：图服务的批准被拒，申请留给人。"""
    k = Kernel(ON)
    workspace_open(k, lane="practice")
    rid = ask(k)
    k.cfg = dataclasses.replace(ON, practice=None)
    assert k.submit(GRAPH_ACTOR, "p1", "grant_scope", {"request": rid, "via": "auto"}) == "forbidden_op"


# ---------- needs_scope 接上扩权（§4.6，修 §1.3 的缺陷） ----------


def needs_scope_intent(k, risk="r0"):
    need = {**NET, "risk": risk}
    iid = k.submit(reason(), "p1", "add_intent", {"title": "读接口", "risk": risk, "budget": R, "needs_scope": [need]})
    settle(k)
    return iid


def test_needs_scope_files_a_request_and_follows_the_approval(k):
    workspace_open(k)
    iid = needs_scope_intent(k)
    (rid,) = [x["id"] for x in k.state["scope_requests"].values() if x.get("intent") == iid]
    assert k.events[-1]["actor"]["kind"] == "graph"
    assert rid not in wk.pending_for_human(k.state, "p1")  # 在审批卡上一起批，不另起一张卡
    assert wk.intent_status(k.state, "p1", iid) == "needs_human"
    assert k.decide("p1", iid) == "ok"
    settle(k)
    assert k.state["scope_requests"][rid]["status"] == "granted"
    assert k.events[-1]["body"]["via"] == "approval"
    assert k.state["problems"]["p1"]["scope"][-1]["pattern"] == "q7.lab:8443"


def test_needs_scope_denied_with_the_intent(k):
    workspace_open(k)
    iid = needs_scope_intent(k)
    assert k.decide("p1", iid, "deny", reason="不做") == "ok"
    settle(k)
    (req,) = [x for x in k.state["scope_requests"].values() if x.get("intent") == iid]
    assert req["status"] == "denied" and len(k.state["problems"]["p1"]["scope"]) == 1


def test_graph_request_must_copy_needs_scope(k):
    workspace_open(k)
    iid = k.submit(reason(), "p1", "add_intent", {"title": "x", "risk": "r0", "budget": R})
    body = {"rules": [NET], "intent": iid}
    assert k.submit(GRAPH_ACTOR, "p1", "request_scope", body) == "forbidden_op"


def test_approval_records_the_risk_the_human_saw():
    """风险表未命中时以人在审批卡上批的申报风险为准；命中时取两者较高者。"""
    for table, want in (((), "r0"), (({**TABLE[0], "risk": "r1"},), "r1")):
        k = Kernel(dataclasses.replace(ON, risk_table=table))
        workspace_open(k)
        iid = needs_scope_intent(k, risk="r0")
        assert k.decide("p1", iid) == "ok"
        settle(k)
        assert k.state["problems"]["p1"]["scope"][-1]["risk"] == want


# ---------- 撤销 ----------


def test_revoke_keeps_index_and_reprofiles(k):
    workspace_open(k)
    assert grant(k, ask(k, {**NET, "pattern": "evil.example:443"})) == "ok"
    assert k.submit(HUMAN, "p1", "revoke_scope", {"rule": 1}) == "schema_error"  # 理由必填
    assert k.submit(HUMAN, "p1", "revoke_scope", {"rule": 1, "reason": "用完了"}) == "ok"
    p = k.state["problems"]["p1"]
    assert len(p["scope"]) == 2 and p["scope"][1]["revoked"] == k.state["seq"]
    assert p["profile"]["reversibility"] == "r0" and p["profile"]["info"] == "complete"
    assert k.submit(HUMAN, "p1", "revoke_scope", {"rule": 1, "reason": "x"}) == "schema_error"
    assert k.submit(HUMAN, "p1", "revoke_scope", {"rule": 0, "reason": "x"}) == "schema_error"  # 至少留一条
    assert k.submit(explore(), "p1", "revoke_scope", {"rule": 0, "reason": "x"}) == "forbidden_op"
    assert ask(k, {**NET, "pattern": "evil.example:443"}).startswith("r_")  # 撤销后可以再申请


def test_profile_override_survives_reprofile(k):
    workspace_open(k)
    assert k.submit(HUMAN, "p1", "profile_override", {"axis": "info", "value": "partial", "reason": "外部依赖"}) == "ok"
    assert grant(k, ask(k)) == "ok"
    p = k.state["problems"]["p1"]
    assert p["profile"]["info"] == "partial" and p["derived_profile"]["info"] == "partial"


# ---------- 重放 ----------


def test_replay_reads_only_event_bodies(k):
    workspace_open(k, lane="practice")
    ask(k)
    settle(k)
    assert grant(k, ask(k, {**NET, "pattern": "evil.example:443"})) == "ok"
    assert k.submit(HUMAN, "p1", "revoke_scope", {"rule": 1, "reason": "x"}) == "ok"
    st = empty_state()
    for e in k.events:
        st = apply(st, e)
    assert st == k.state


def test_old_logs_keep_their_state_shape():
    k = Kernel(ON)
    workspace_open(k)
    assert "scope_requests" not in k.state


# ---------- 扩权卡（§7.1，第三步）：网页与 pd 同一张卡 ----------


def test_card_names_where_the_risk_came_from_and_the_profile_change(k):
    from paoding_graph import views

    workspace_open(k)
    rid = ask(k, {**NET, "pattern": "evil.example:443"})
    hit = ask(k)
    assert k.state["scope_requests"][rid]["risk_from"] == [None]
    assert k.state["scope_requests"][hit]["risk_from"] == [0]
    assert k.state["scope_requests"][rid]["role"] == "explore"
    c = views.card(k.state, "p1", "scope", rid, ON)
    d = c["display"]
    assert d["risk_rows"] == [None] and views.card(k.state, "p1", "scope", hit, ON)["display"]["risk_rows"] == [1]
    assert d["profile"]["before"] == {"info": "complete", "judge": "hard", "reversibility": "r0"}
    assert d["profile"]["after"] == {"info": "partial", "judge": "hard", "reversibility": "r2"}
    assert d["risk_choices"] == ["r2"] and d["approve_enabled"] and d["decision"] is None
    assert views.card(k.state, "p1", "scope", hit, ON)["display"]["risk_choices"] == ["r0", "r1", "r2"]
    assert views.card(k.state, "p1", "scope", rid)["display"]["profile"] is None  # 没给 cfg 就不算
    # 画像与风险来源只排版，不进哈希：卡片对象与 pd 取 seen 的一致
    assert c["card_hash"] == seen_card(k.state, "p1", "scope", rid)["card_hash"]
    assert grant(k, rid, decision="deny", reason="不需要") == "ok"
    d = views.card(k.state, "p1", "scope", rid, ON)["display"]
    assert d["decision"]["decision"] == "deny" and d["decision"]["by"] == "cz" and d["decision"]["via"] is None
    assert d["decision"]["reason"]["value"] == "不需要" and not d["approve_enabled"] and d["profile"] is None


def test_card_records_auto_grants_with_the_envelope_version(k):
    from paoding_graph import views

    workspace_open(k, lane="practice")
    rid = ask(k)
    settle(k)
    d = views.card(k.state, "p1", "scope", rid, ON)["display"]["decision"]
    assert d["decision"] == "approve" and d["via"] == "auto" and d["by"] == "graph" and d["policy_version"] == 3


def test_intent_requests_are_decided_on_the_approval_card(k):
    from paoding_graph import views

    workspace_open(k)
    iid = k.submit(
        HUMAN,
        "p1",
        "add_intent",
        {"title": "t", "premises": [], "risk": "r0", "budget": R, "needs_scope": [{**NET, "risk": "r0"}]},
    )
    settle(k)
    [rid] = [x["id"] for x in k.state["scope_requests"].values() if x.get("intent") == iid]
    assert not views.card(k.state, "p1", "scope", rid, ON)["display"]["approve_enabled"]
