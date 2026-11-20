"""开放道上人的点位（地图 v0.9 02 §4；04 §3.2 第三步）：追问、叫停、采纳与不采纳带四顾、闲置自动关、按会话花费。

- follow_up（Q31）：只有人、只在开放道、要先有交付；seen 不是最新交付即 stale_view；剩余低于收尾保留（题预算的
  10%）要附追加预算，追加后受单题硬顶；之后开始新的一轮：/work 再派 solve，接力上限按轮计。
- halt（Q20）：只有人、只在开放道；之后不再派 solve，叫停后没交付即转人；追问解除叫停。
- close_problem（Q32）：开放道的题扩过权时，人关题要带所见的收尾卡和逐条确认的名单。
- idle_close_at（Q33）：交付之后等人才有；从最后一次交付算起，缺省 7 天，开题时抄入的值优先。
- by_lease（Q15）：每条租约一行，各行之和等于 spent。
"""

from __future__ import annotations

import dataclasses

from conftest import CFG, HUMAN, Kernel
from test_open_lane import answered, lease_solve, open_lane, release, solver

from paoding_graph import views, wire_schema
from paoding_graph import work as wk
from paoding_graph.cards import seen as seen_card


def delivered_once(k: Kernel) -> str:
    assert open_lane(k) == "ok"
    lid = lease_solve(k)
    assert answered(k, lid).startswith("d_")
    assert release(k, lid, outcome="done") == "ok"
    return lid


def spend(k: Kernel, lid: str, usd_milli: int) -> None:
    body = {"task_id": lid, "source": "proxy", "usd_milli": usd_milli, "wall_s": 0, "price_table": "t", "model": "m1"}
    assert k.submit({**solver(lid), "kind": "adapter"}, "p1", "cost", body) == "ok"


def follow(k: Kernel, text: str = "再看看第二个来源", **extra) -> str:
    return k.submit(HUMAN, "p1", "follow_up", {"text": text, "seen": {"seq": k.state["seq"]}, **extra})


# ---------------------------------------------------------------- 追问


def test_follow_up_needs_a_delivery_and_a_human():
    k = Kernel()
    assert open_lane(k) == "ok"
    assert follow(k) == "conflict"  # 还没交付：在做的时候用 hint
    k = Kernel()
    delivered_once(k)
    assert k.submit(solver("x"), "p1", "follow_up", {"text": "t", "seen": {"seq": 0}}) == "forbidden_op"
    assert k.submit(HUMAN, "p1", "follow_up", {"text": "  ", "seen": {"seq": k.state["seq"]}}) == "schema_error"
    assert k.submit(HUMAN, "p1", "follow_up", {"text": "x" * 2001, "seen": {"seq": k.state["seq"]}}) == "schema_error"
    assert k.submit(HUMAN, "p1", "follow_up", {"text": "t"}) == "schema_error"
    assert follow(k) == "ok"
    assert follow(k) == "conflict"  # 上一次追问还没交付


def test_follow_up_must_have_seen_the_latest_delivery():
    k = Kernel()
    delivered_once(k)
    first = k.state["seq"]
    assert follow(k) == "ok"
    lid = lease_solve(k)
    assert answered(k, lid).startswith("d_")
    assert k.submit(HUMAN, "p1", "follow_up", {"text": "t", "seen": {"seq": first}}) == "stale_view"
    assert follow(k) == "ok"


def test_follow_up_on_the_strict_lane_is_refused():
    k = Kernel()
    k.open("p1")
    assert k.submit(HUMAN, "p1", "follow_up", {"text": "t", "seen": {"seq": 1}}) == "forbidden_op"
    assert k.submit(HUMAN, "p1", "halt", {}) == "forbidden_op"


def test_follow_up_starts_a_new_round():
    k = Kernel()
    delivered_once(k)
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]
    assert follow(k) == "ok"
    assert wk.work(k.state, "p1") == [{"kind": "solve"}]
    # 新的一轮重新计接力：五个会话都没交付才转人
    for _ in range(wk.OPEN_RELAYS):
        lid = lease_solve(k)
        assert release(k, lid) == "ok"
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "stalled"}]
    p = k.state["problems"]["p1"]
    assert p["follow_ups"][0]["after_delivery"] == p["deliveries"][0]["id"]
    assert wk.terminal(k.state, "p1") == "delivered"  # 上一轮的交付仍在：追问不会抹掉它


def test_follow_up_below_the_closing_reserve_needs_more_budget():
    k = Kernel(dataclasses.replace(CFG, open_cap_usd_milli=6000))
    lid = delivered_once(k)
    spend(k, lid, 4600)  # 题预算 5000，剩 400，低于收尾保留 500
    assert follow(k) == "over_budget"
    assert follow(k, budget_add_usd_milli=0) == "schema_error"
    assert follow(k, budget_add_usd_milli=2000) == "over_budget"  # 7000 超过单题硬顶 6000
    assert follow(k, budget_add_usd_milli=1000) == "ok"
    assert k.state["problems"]["p1"]["budget"]["usd_milli"] == 6000
    assert wk.budget_view(k.state, "p1")["cap"]["usd_milli"] == 6000


# ---------------------------------------------------------------- 叫停


def test_halt_stops_dispatch_and_lets_the_live_session_deliver():
    k = Kernel()
    assert open_lane(k) == "ok"
    lid = lease_solve(k)
    assert k.submit(solver(lid), "p1", "halt", {}) == "forbidden_op"  # 智能体不能替人叫停
    assert k.submit(HUMAN, "p1", "halt", {"reason": "够了"}) == "ok"
    assert k.submit(HUMAN, "p1", "halt", {}) == "conflict"
    assert wk.halted(k.state, "p1")
    assert answered(k, lid).startswith("d_")  # 在途的会话照常交出已有结果
    assert release(k, lid, outcome="done") == "ok"
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "delivered"}]


def test_halt_without_a_delivery_goes_to_a_human_and_follow_up_lifts_it():
    k = Kernel()
    assert open_lane(k) == "ok"
    lid = lease_solve(k)
    assert k.submit(HUMAN, "p1", "halt", {}) == "ok"
    assert release(k, lid) == "ok"
    assert wk.work(k.state, "p1") == [{"kind": "human", "target": "p1", "why": "stalled"}]
    k2 = Kernel()
    delivered_once(k2)
    assert k2.submit(HUMAN, "p1", "halt", {}) == "ok"
    assert follow(k2) == "ok"
    assert not wk.halted(k2.state, "p1")
    assert wk.work(k2.state, "p1") == [{"kind": "solve"}]


# ---------------------------------------------------------------- 采纳与不采纳带四顾


def test_closing_after_runtime_grants_needs_the_closeout_confirmed():
    k = Kernel()
    delivered_once(k)
    assert wk.closeout_items(k.state, "p1") == []  # 只在工作区里干活：四顾清单是空的
    p = k.state["problems"]["p1"]
    rule = {"resource": "net", "pattern": "a.lab:443", "actions": ["connect"], "risk": "r1", "granted": {}}
    k.state["problems"]["p1"] = {**p, "scope": [*p["scope"], rule]}  # 运行时扩过一条权（扩权流程另有测试）
    assert [i["item"] for i in wk.closeout_items(k.state, "p1")] == ["scope_granted"]
    assert k.submit(HUMAN, "p1", "close_problem", {"feedback": "adopted"}) == "schema_error"
    seen = seen_card(k.state, "p1", "closeout", "p1")
    body = {"feedback": "adopted", "seen": seen}
    assert k.submit(HUMAN, "p1", "close_problem", {**body, "closeout": []}) == "schema_error"
    assert k.submit(HUMAN, "p1", "close_problem", {**body, "closeout": ["scope_granted", "x"]}) == "schema_error"
    assert k.submit(HUMAN, "p1", "close_problem", {**body, "closeout": ["scope_granted"]}) == "ok"
    ev = k.events[-1]
    assert ev["body"]["closeout"] == ["scope_granted"] and ev["body"]["terminal"] == "delivered"


def test_closeout_field_is_only_for_the_open_lane():
    k = Kernel()
    k.open("p1")
    assert k.submit(HUMAN, "p1", "close_problem", {"closeout": []}) == "schema_error"
    k = Kernel()
    delivered_once(k)
    assert k.submit(HUMAN, "p1", "close_problem", {"feedback": "rejected", "closeout": ["x"]}) == "schema_error"


# ---------------------------------------------------------------- 闲置自动关与读端


def test_idle_close_at_counts_from_the_last_delivery():
    k = Kernel()
    assert open_lane(k) == "ok"
    assert wk.idle_close_at(k.state, "p1") is None
    lid = lease_solve(k)
    assert answered(k, lid).startswith("d_")
    assert wk.idle_close_at(k.state, "p1") is None  # 会话还在：不算等人
    assert release(k, lid, outcome="done") == "ok"
    ts = k.state["problems"]["p1"]["deliveries"][-1]["ts"]
    assert wk.idle_close_at(k.state, "p1") == ts + wk.IDLE_CLOSE_S * 1000
    assert follow(k) == "ok"
    assert wk.idle_close_at(k.state, "p1") is None  # 追问之后又在做了


def test_idle_close_seconds_are_copied_at_open():
    k = Kernel(dataclasses.replace(CFG, idle_close_s=3600))
    delivered_once(k)
    p = k.state["problems"]["p1"]
    assert p["idle_close_s"] == 3600
    assert wk.idle_close_at(k.state, "p1") == p["deliveries"][-1]["ts"] + 3600 * 1000
    k2 = Kernel(dataclasses.replace(CFG, idle_close_s=3600))
    k2.open("p1")
    assert "idle_close_s" not in k2.state["problems"]["p1"]  # 只抄进开放道的题


def test_status_view_carries_follow_ups_halt_and_idle_close():
    k = Kernel()
    delivered_once(k)
    assert follow(k) == "ok"
    assert k.submit(HUMAN, "p1", "halt", {}) == "ok"
    g = views.status(k.state, "p1")["goal"]
    assert [u["text"]["value"] for u in g["follow_ups"]] == ["再看看第二个来源"]
    assert g["follow_ups"][0]["text"]["register"] == "人"
    assert g["halted"] == {"seq": k.state["seq"]}
    assert g["idle_close_at"] is None
    env = {"as_of": k.state["seq"], "head": k.state["seq"], "view_hash": "0" * 64}
    assert wire_schema.validate("StatusView", {**env, **views.status(k.state, "p1")}) == []


def test_budget_by_lease_adds_up_to_spent():
    k = Kernel()
    assert open_lane(k) == "ok"
    a = lease_solve(k)
    spend(k, a, 300)
    spend(k, a, 200)
    assert release(k, a) == "ok"
    b = lease_solve(k)
    spend(k, b, 150)
    view = views.budget(k.state, "p1")
    rows = view["by_lease"]
    assert [(r["lease"], r["usd_milli"], r["active"], r["role"], r["model"]) for r in rows] == [
        (a, 500, False, "solve", "m1"),
        (b, 150, True, "solve", "m1"),
    ]
    assert sum(r["usd_milli"] for r in rows) == view["spent"]["usd_milli"]
    assert (
        wire_schema.validate(
            "BudgetResponse", {"as_of": k.state["seq"], "head": k.state["seq"], "view_hash": "0" * 64, **view}
        )
        == []
    )
