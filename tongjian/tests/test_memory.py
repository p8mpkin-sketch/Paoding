"""能力一最小版：判例封存与记忆投影、开题召回、召回复核（01-memory；规格 v1.5 第 50、51 条，增量 8、9）。

验收（cz 2026-11-19）：
- 召回 → 复核通过 → 成为新题的 E3；复核不通过 → 新题里不是 E3、不作可采信前提，原题等级不变
- 人逐条去掉后清单不变（登记后不可改）
- case_seal=off 时无投影、无召回项
"""

import pytest
from tj_rig import CONTROL, SPEC, TITLE, Rig

from paoding_graph.contract import compute_levels, node_levels
from paoding_tongjian.contract import card_hash, mem_state, with_recall


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def solved_a(rig, pid="pa"):
    rig.open(pid)
    fid = rig.solve_thin(pid)
    assert rig.tj.sweep() == [pid]
    return fid


# ---------- 封存与投影 ----------


def test_closing_seals_a_case_and_projects_the_env_fact(rig):
    fid = solved_a(rig)
    c = rig.tj.state["cases"]["pa"]
    assert c["terminal"] == "solved" and c["path"] == "thin" and fid in c["attribution"]["chain"]["facts"]
    assert c["seal"]["head_hash"] == rig.svc.events("pa")[-1]["hash"]
    items = {m["kind"]: m for m in rig.tj.items()}
    env = items["env_fact"]
    assert env["title"] == TITLE and env["state"] == "active" and env["source"]["node"] == fid
    assert env["check"]["spec"]["hash"] == rig.blobs.put(SPEC) and env["check"]["control"][0]["hash"] == rig.blobs.put(
        CONTROL
    )
    assert items["spend_profile"]["scope"] == {"sig_key": c["sig_key"]}
    assert rig.tj.sweep() == []  # 一题只封存一次


def test_seal_filter_drops_uncontrolled_candidates_and_low_levels(rig):
    """无对照的观察、未判定（E0）的观察、Goal 候选一律不入。"""
    rig.open("pa")
    lid = rig.lease("pa", "bootstrap")
    s = rig.session(lid, "bootstrap")
    ex = rig.art("tok-executor", "pa", b"out", "exec", exec=__import__("tj_rig").PROV)
    spec = rig.art(s, "pa", SPEC, "authored")
    cand = rig.art(s, "pa", b"42", "authored")
    plain = {"judge_id": "replay", "spec_ref": spec, "expect": {"stdout_contains": "ready"}}
    f_plain = rig.one(
        s, "pa", "add_fact", {"title": "无对照", "claim_type": "observation", "check": plain, "grounds": [ex]}
    )
    rid = rig.one(s, "pa", "request_judge", {"target": f_plain, "judge_id": "replay"})
    rig.verdict("pa", rid, "pass")
    on_cand = {**plain, "spec_ref": cand, "control": {"inputs": [spec]}}
    f_cand = rig.one(
        s, "pa", "add_fact", {"title": "引了候选", "claim_type": "observation", "check": on_cand, "grounds": [ex]}
    )
    rid = rig.one(s, "pa", "request_judge", {"target": f_cand, "judge_id": "replay"})
    rig.verdict("pa", rid, "pass", controlled=True)
    e0 = {**plain, "control": {"inputs": [cand]}, "expect": {"stdout_contains": "x"}}
    rig.one(s, "pa", "add_fact", {"title": "没判过", "claim_type": "observation", "check": e0, "grounds": [ex]})
    rid = rig.one(s, "pa", "request_judge", {"target": "goal", "judge_id": "exact_match", "candidate": cand})
    rig.release(s, "pa", lid)
    rig.verdict("pa", rid, "pass")
    rig.tj.sweep()
    assert [m["kind"] for m in rig.tj.items()] == ["spend_profile"]


def test_case_seal_off_seals_the_case_but_projects_nothing_and_recalls_nothing(tmp_path):
    rig = Rig(tmp_path, case_seal=False)
    solved_a(rig)
    assert "pa" in rig.tj.state["cases"] and rig.tj.items() == []
    m = rig.open("pb", mode="recall")
    assert m["facts"] == []
    assert rig.work("pb") == ["bootstrap"]  # 没有 recall 项
    assert not rig.svc.state["problems"]["pb"]["recall"]["items"]


# ---------- 召回与复核 ----------


def test_recall_then_pass_becomes_the_new_problems_own_e3(rig):
    solved_a(rig)
    m = rig.open("pb", mode="recall")
    assert [x["title"] for x in m["facts"]] == [TITLE]
    rec = rig.svc.state["problems"]["pb"]["recall"]
    assert rec["items"][0]["mem"] == m["facts"][0]["id"] and rec["match_digest"] == m["digest"]
    assert rig.work("pb") == ["recall"]  # 先于 Bootstrap
    [done] = rig.recaller.tick()
    assert done["status"] == "submitted" and done["released"]
    [(fid, rid)] = rig.recalled("pb")
    assert node_levels(rig.svc.state, "pb")[fid] == "E0"  # 判官还没重跑：不是 E3
    rig.verdict("pb", rid, "pass", controlled=True)
    assert node_levels(rig.svc.state, "pb")[fid] == "E3"
    assert "bootstrap" in rig.work("pb") and "recall" not in rig.work("pb")
    rig.solve_thin("pb", observe=False)
    rig.tj.sweep()
    [o] = rig.tj.state["cases"]["pb"]["recall_outcomes"]
    assert o == {"mem": m["facts"][0]["id"], "verdict": "pass", "on_chain": False, "fact": fid}
    assert mem_state(rig.tj.state, o["mem"]) == "active"


def test_recall_then_fail_is_not_e3_not_a_trusted_premise_and_goes_stale(rig):
    solved_a(rig)
    m = rig.open("pb", mode="recall")
    rig.recaller.tick()
    [(fid, rid)] = rig.recalled("pb")
    rig.verdict("pb", rid, "fail", controlled=True)
    lv = node_levels(rig.svc.state, "pb")
    assert lv[fid] != "E3"
    assert node_levels(rig.svc.state, "pa")[m["facts"][0]["source"]["node"]] == "E3"  # 原题等级不变（I7）
    # 以它为前提的 Intent 不被收下：复核没通过的召回不能作可采信前提（I2）
    lid = rig.lease("pb", "bootstrap")
    s = rig.session(lid, "bootstrap")
    rig.release(s, "pb", lid, "nothing")
    rl = rig.lease("pb", "reason")
    sr = rig.session(rl, "reason")
    body = {"title": "照旧事走", "premises": [fid], "risk": "r0", "budget": {"usd_milli": 100}}
    out = rig.sub(sr, "pb", [{"op": "add_intent", "body": body}])
    assert out["results"][0]["code"] == "stale_premise"
    rig.release(sr, "pb", rl)
    rig.one("tok-human", "pb", "close_problem", {"reason": "测完"})
    rig.tj.sweep()
    assert mem_state(rig.tj.state, m["facts"][0]["id"]) == "stale"
    assert rig.tj.match({**rig.tj.state["cases"]["pa"]["sig"], **_problem(rig, "pb")})["facts"] == []  # 过期不再召回


def _problem(rig, pid):
    return dict(rig.svc.state["problems"][pid])


def test_recall_role_may_only_submit_the_listed_checks(rig):
    solved_a(rig)
    rig.open("pb", mode="recall")
    lid = rig.lease("pb", "recall")
    tok = rig.reg.issue({"kind": "adapter", "id": "rc1", "session": lid, "role": "recall"})
    item = rig.svc.state["problems"]["pb"]["recall"]["items"][0]
    good = {
        "title": "[忆] " + item["title"],
        "summary": "",
        "claim_type": "observation",
        "check": item["check"],
        "premises": [],
        "grounds": [item["check"]["spec_ref"]],
    }
    bad = [
        {**good, "title": "随便写一条"},
        {**good, "check": {**item["check"], "expect": {"stdout_contains": "anything"}}},
        {**good, "claim_type": "inference"},
    ]
    for body in bad:
        out = rig.sub(tok, "pb", [{"op": "add_fact", "body": body}])
        assert out["results"][0]["code"] == "forbidden_op", body
    for op, body in [
        ("add_intent", {"title": "x", "premises": [], "risk": "r0", "budget": {"usd_milli": 1}}),
        ("hint", {"text": "x"}),
    ]:
        assert rig.sub(tok, "pb", [{"op": op, "body": body}])["results"][0]["code"] == "forbidden_op"
    assert rig.sub(tok, "pb", [{"op": "add_fact", "body": good}])["ok"]


# ---------- 人去掉条目、清单不可改 ----------


def test_dropped_items_stay_dropped_and_the_list_is_fixed_at_open(rig):
    solved_a(rig)
    env = next(x for x in rig.tj.items() if x["kind"] == "env_fact")
    m = rig.open("pb", mode="recall", drop=[env["id"]])
    rec = rig.svc.state["problems"]["pb"]["recall"]
    assert rec["items"] == [] and rec["excluded_by_human"] == [env["id"]] and m["facts"][0]["id"] == env["id"]
    assert rig.work("pb") == ["bootstrap"]
    opened = rig.svc.events("pb")[-1]["body"]["recall"]
    assert opened == rec  # 只有开题事件写它；没有任何操作能改清单
    again = rig.sub("tok-human", "pb", with_recall(rig.ops("pb"), m, "recall"))
    assert not again["ok"]


def test_noverify_puts_facts_into_notes_only(rig):
    solved_a(rig)
    rig.open("pb", mode="noverify")
    rec = rig.svc.state["problems"]["pb"]["recall"]
    assert rec["mode"] == "noverify" and rec["items"] == []
    assert [(n["kind"], n["title"]) for n in rec["notes"]] == [("env_fact", TITLE)]
    assert rig.work("pb") == ["bootstrap"] and rig.recalled("pb") == []


def test_off_opens_exactly_as_before(rig):
    solved_a(rig)
    rig.open("pb", mode="off")
    assert "recall" not in rig.svc.events("pb")[-1]["body"]
    assert rig.work("pb") == ["bootstrap"]


# ---------- 人的钉住与遗忘 ----------


def test_forget_retires_and_pin_needs_a_fresh_card(rig):
    solved_a(rig)
    env = next(x for x in rig.tj.items() if x["kind"] == "env_fact")
    stale = {"seq": 0, "card_hash": "0" * 64}
    assert rig.tj.decide("mem_pin", env["id"], "常用", stale, "cz")["code"] == "stale_view"
    card = rig.tj.card(env["id"])
    assert rig.tj.decide("mem_pin", env["id"], "常用", card["seen"], "cz")["ok"]
    assert rig.tj.decide("mem_forget", env["id"], "", rig.tj.card(env["id"])["seen"], "cz")["code"] == "schema_error"
    assert rig.tj.decide("mem_forget", env["id"], "环境换了", rig.tj.card(env["id"])["seen"], "cz")["ok"]
    assert mem_state(rig.tj.state, env["id"]) == "retired"
    assert rig.open("pb", mode="recall")["facts"] == []
    assert card_hash(rig.tj.state, env["id"]) != card["seen"]["card_hash"]


def test_tongjian_state_replays_from_its_log(rig, tmp_path):
    solved_a(rig)
    rig.open("pb", mode="recall")
    rig.recaller.tick()
    [(fid, rid)] = rig.recalled("pb")
    rig.verdict("pb", rid, "pass", controlled=True)
    rig.solve_thin("pb", observe=False)
    rig.tj.sweep()
    from paoding_tongjian.contract import Tongjian, TongjianConfig

    again = Tongjian(tmp_path / "tj.sqlite", rig.svc, TongjianConfig(model_epoch="m1"))
    assert again.state == rig.tj.state and again.items() == rig.tj.items()
