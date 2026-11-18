"""人的决定绑定所见（规格 §3.1.9、HMI H2 与 §3.5；3.1.5 的 17；HT-7 的内核一侧）。

人在序号 s 看到卡片，到 s+k 才作决定。决策操作带 seen {seq, card_hash}，内核在链头重算这张卡的投影哈希，
不等即 stale_view 并附上最新的卡。与这张卡无关的事件再多，旧哈希仍然有效。
"""
import pytest
from conftest import HUMAN, reason
from http_rig import Api

from paoding_graph import views
from paoding_graph import work as wk
from paoding_graph.cards import seen as seen_card
from paoding_graph.reducer import Reject, apply, empty_state, validate
from paoding_graph.replay import replay, state_hash

SINAN = {"kind": "sinan", "id": "sn1"}
R = {"usd_milli": 100, "wall_s": 60}


def gated(k, pid="p1"):
    """一条等待审批的 r2 Intent，前提是一条已到 E3 的观察。返回 (Intent, 前提)。"""
    k.open(pid, scope_risks=("r0", "r2"))
    lid = k.submit(SINAN, pid, "lease", {"kind": "bootstrap", "holder": "sn1", "reserve": R, "ttl_s": 600})
    assert k.submit(SINAN, pid, "release", {"lease": lid, "outcome": "nothing"}) == "ok"
    f = k.obs(pid, title="配置可写")
    assert k.verdict(pid, f, "pass") == "ok"
    iid = k.submit(reason(), pid, "add_intent", {"title": "改写后重启", "premises": [f], "risk": "r2", "budget": R})
    assert wk.intent_status(k.state, pid, iid) == "needs_human"
    return iid, f


def approve(k, iid, seen, decision="approve", **extra):
    return k.submit(HUMAN, "p1", "approve", {"intent": iid, "decision": decision, "seen": seen, **extra})


def test_decision_requires_seen(k):
    iid, _ = gated(k)
    good = seen_card(k.state, "p1", "approval", iid)
    for bad in (None, {}, "abc", {"card_hash": good["card_hash"]}, {"seq": 1}, {**good, "card_hash": "xyz"},
                {**good, "seq": "7"}, {**good, "seq": -1}, {**good, "extra": 1}):
        body = {"intent": iid, "decision": "approve", **({"seen": bad} if bad is not None else {})}
        assert k.submit(HUMAN, "p1", "approve", body) == "schema_error", bad
    assert wk.intent_status(k.state, "p1", iid) == "needs_human"
    assert approve(k, iid, good) == "ok"


@pytest.mark.parametrize("decision", ["approve", "deny"])
def test_stale_card_is_rejected(k, decision):
    """3.1.5 的 17：取得审批卡之后，一条前提被证伪；凭旧哈希的批准与拒绝都返回 stale_view。"""
    iid, f = gated(k)
    old = seen_card(k.state, "p1", "approval", iid)
    assert k.verdict("p1", f, "fail") == "ok"                    # 卡片打开期间注入的反证：前提降级
    extra = {"reason": "不放行"} if decision == "deny" else {}
    r = validate(k.state, HUMAN, "p1", "approve", {"intent": iid, "decision": decision, "seen": old, **extra}, k.cfg)
    assert isinstance(r, Reject) and r.code == "stale_view" and r.card == ("approval", iid)
    n = len(k.events)
    assert approve(k, iid, old, decision, **extra) == "stale_view"
    assert len(k.events) == n and iid not in k.state["approvals"] and iid not in k.state["abandoned"]
    fresh = seen_card(k.state, "p1", "approval", iid)
    assert fresh["card_hash"] != old["card_hash"]


def test_unrelated_events_do_not_stale_the_card(k):
    """哈希按卡片范围计算：别的任务的用量、Hint、估值、别的 Intent、别的题，都不让一次批准过期。"""
    iid, f = gated(k)
    old = seen_card(k.state, "p1", "approval", iid)
    assert k.submit(HUMAN, "p1", "hint", {"text": "看看配置", "about": iid}).startswith("h_")
    assert k.submit(reason(), "p1", "add_intent", {"title": "另一条", "premises": [f], "risk": "r0", "budget": R,
                                                   "expected_gain": 0.9}).startswith("i_")
    other = k.obs("p1", title="无关的观察")
    assert k.verdict("p1", other, "fail") == "ok"
    lid = k.submit(SINAN, "p1", "lease", {"kind": "reason", "holder": "sn1", "reserve": R, "ttl_s": 600})
    assert k.submit({"kind": "adapter", "id": "ad1"}, "p1", "cost", {
        "task_id": lid, "source": "proxy", "usd_milli": 30, "price_table": "t"}) == "ok"
    k.open("p2")
    assert seen_card(k.state, "p1", "approval", iid)["card_hash"] == old["card_hash"]
    assert old["seq"] < k.state["seq"]                           # seq 只留作审计，不参与比较
    assert approve(k, iid, old) == "ok"
    assert k.state["approvals"][iid] == [k.state["seq"]]


def test_seen_must_be_this_intents_card(k):
    """拿别的 Intent 的卡哈希来批准这一条：不等，stale_view。"""
    iid, f = gated(k)
    other = k.submit(reason(), "p1", "add_intent", {"title": "不带前提", "premises": [], "risk": "r2", "budget": R})
    assert approve(k, iid, seen_card(k.state, "p1", "approval", other)) == "stale_view"
    assert approve(k, iid, seen_card(k.state, "p1", "approval", iid)) == "ok"


def test_seen_is_recorded_and_replays(k):
    iid, _ = gated(k)
    s = seen_card(k.state, "p1", "approval", iid)
    assert approve(k, iid, s) == "ok"
    assert k.events[-1]["body"]["seen"] == s                     # 事件里留下人当时所见，供审计
    assert state_hash(replay(k.events, apply, empty_state())) == state_hash(k.state)


def test_human_close_binds_the_closeout_card(k):
    """人关题时带上所见的四顾清单：与链头不符即 stale_view；相符则哈希记进事件。裸的 card_hash 不再被照单收下。"""
    k.open(scope_risks=("r0", "r2"))
    old = seen_card(k.state, "p1", "closeout", "p1")
    assert k.submit(HUMAN, "p1", "close_problem", {"reason": "r", "card_hash": "0" * 64}) == "schema_error"
    assert k.verdict("p1", "goal", "pass", judge="exact_match", candidate=k.art("p1", "authored", b"c")) == "ok"
    assert k.verdict("p1", "goal", "pass", judge="exact_match", candidate=k.art("p1", "authored", b"c")) == "ok"
    assert not k.state["problems"]["p1"]["closed"]               # r2 题：四顾清单非空，不自动关题
    assert k.submit(HUMAN, "p1", "close_problem", {"reason": "r", "seen": old}) == "stale_view"   # Goal 的等级变了
    fresh = seen_card(k.state, "p1", "closeout", "p1")
    assert k.submit(HUMAN, "p1", "close_problem", {"reason": "r", "seen": fresh}) == "ok"
    assert k.events[-1]["body"]["card_hash"] == fresh["card_hash"]
    assert k.state["problems"]["p1"]["terminal"] == "solved"


def test_human_close_without_seen_still_allowed(k):
    """M0 没有 accept 操作；人中止一道题（close_problem 带理由）不要求 seen（异议 006 第 2 条）。"""
    k.open()
    assert k.submit(HUMAN, "p1", "close_problem", {"reason": "不做了"}) == "ok"
    assert k.events[-1]["body"]["card_hash"] is None


# ---------- 服务层与 HTTP：stale_view 附上链头的最新卡片 ----------

def test_stale_view_carries_the_latest_card_over_http(tmp_path):
    """HT-7 的服务端一侧：凭旧哈希批准被拒为 stale_view，结果里附的卡与 /cards 端点此刻给出的相同。"""
    api = Api(tmp_path)
    try:
        api.open("p1", risks=("r0", "r2"))
        _, b = api.lease("p1", "bootstrap")
        api.release(b["lease"]["id"], "nothing")
        _, b = api.lease("p1", "reason")
        rs = api.session(b["lease"]["id"], "reason")
        iid = api.propose_with(rs, "p1", [{"op": "add_intent", "body": {
            "title": "改写后重启", "premises": [], "risk": "r2", "budget": R}}])["results"][0]["id"]
        card = api.get(f"/v1/problems/p1/cards/approval/{iid}")
        seen = {"seq": card["as_of"], "card_hash": card["card_hash"]}
        stale = {"seq": card["as_of"], "card_hash": "0" * 64}
        out = api.propose("p1", [{"op": "approve", "body": {"intent": iid, "decision": "approve", "seen": stale}}])
        [r] = out["results"]
        assert not out["ok"] and r["code"] == "stale_view"
        latest = api.get(f"/v1/problems/p1/cards/approval/{iid}")
        assert r["card"]["card_hash"] == latest["card_hash"] == card["card_hash"]
        assert r["card"]["card"] == latest["card"] and r["card"]["display"] == latest["display"]
        assert r["card"]["as_of"] == latest["as_of"]
        assert api.svc.state["approvals"] == {}
        out = api.propose("p1", [{"op": "approve", "body": {"intent": iid, "decision": "approve", "seen": seen}}])
        assert out["ok"], out
        assert views.status(api.svc.state, "p1")["intents"][0]["status"] == "open"
    finally:
        api.close()
