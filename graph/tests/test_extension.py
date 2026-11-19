"""续期门（规格 3.5.2，T-1；验收 3.5.5 的 6、地图 Q18、AC8.1）。

越过 80% 标记而 50% 以来没有带判据的对象新到 E3：/work 不再给新的 explore，题目进入 human 项（why=extension）；
人用 extend 放行，或 budget_add 追加预算并放行，两者都绑定所见的续期卡。只有带对照的观察到 E3、或带判据的
Intent 达成才算进展。开关在设置层（budget.extension），开题时抄进事件体；always 即消融臂与旧题的行为。
"""

import dataclasses

from conftest import CFG, HUMAN, JUDGE, Kernel
from test_control_kernel import controlled
from test_leases import add_intent, boot, cost, follow, kinds, lease, release

from paoding_graph import cards
from paoding_graph import work as wk
from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

GATE = dataclasses.replace(CFG, extension="gate")


def reflect(k):
    """越过标记之后的复盘期：一个 reason 租约释放之后，复盘期结束。"""
    rl = lease(k, "reason")
    assert rl.startswith("l_"), rl
    assert release(k, rl) == "ok"


def to_80(k, between=None):
    """开题 → 花过 50% → 复盘 → （between：50% 与 80% 之间做的事）→ 花过 80%。返回 Intent id。"""
    k.open()
    boot(k)
    lid = lease(k, "explore", add_intent(k, title="a"))
    cost(k, lid, 2600)
    follow(k)
    assert release(k, lid, "nothing") == "ok"
    reflect(k)
    if between:
        between(k)
    lid = lease(k, "explore", add_intent(k, title="b"))
    assert lid.startswith("l_"), lid
    cost(k, lid, 1500)
    follow(k)
    assert k.state["problems"]["p1"]["marks"] == [50, 80]
    assert release(k, lid, "nothing") == "ok"
    reflect(k)
    return add_intent(k, title="c")  # 80% 之后新提的尝试：门关着时它也领不到


def seen(k):
    return cards.seen(k.state, "p1", "extension", "p1")


def test_gate_closes_without_progress_and_extend_reopens():
    k = Kernel(GATE)
    i = to_80(k)
    assert k.state["problems"]["p1"]["extension"] == "gate"
    assert wk.extension_pending(k.state, "p1")
    assert ("explore", i) not in kinds(k)
    assert ("human", "p1") in kinds(k)
    assert {"kind": "human", "target": "p1", "why": "extension"} in wk.work(k.state, "p1")
    assert lease(k, "explore", i) == "forbidden_op"  # 门关着：司南领不到新的 explore
    card = cards.card_object(k.state, "p1", "extension", "p1")
    assert card["fields"] == {"progress_since_50": [], "spent_usd_milli": 4100, "cap_usd_milli": 5000, "pending": True}
    bad = {"seq": 1, "card_hash": "0" * 64}
    assert k.submit(HUMAN, "p1", "extend", {"seen": bad}) == "stale_view"
    assert k.submit(HUMAN, "p1", "extend", {}) == "schema_error"
    assert k.submit({"kind": "adapter", "id": "ad1", "role": "reason"}, "p1", "extend", {"seen": seen(k)}) == (
        "forbidden_op"
    )
    assert k.submit(HUMAN, "p1", "extend", {"seen": seen(k)}) == "ok"
    assert not wk.extension_pending(k.state, "p1")
    assert ("explore", i) in kinds(k)
    assert not any(w.get("why") == "extension" for w in wk.work(k.state, "p1"))
    assert k.submit(HUMAN, "p1", "extend", {"seen": seen(k)}) == "schema_error"  # 已经放行
    assert cards.card_object(k.state, "p1", "extension", "p1")["fields"]["pending"] is False
    assert state_hash(replay(k.events, apply, empty_state())) == state_hash(k.state)


def test_controlled_observation_since_50_counts_as_progress():
    def observe(k):
        fid = controlled(k, title="ctl")
        rid = k.submit(HUMAN, "p1", "request_judge", {"target": fid, "judge_id": "replay"})
        ev = k.art("p1", "judge", b"ctl-pass")
        body = {"request": rid, "result": "pass", "version": "1", "evidence": [ev], "control_end": "fail"}
        assert k.submit(JUDGE, "p1", "judge_verdict", body) == "ok"

    k = Kernel(GATE)
    i = to_80(k, observe)
    assert not wk.extension_pending(k.state, "p1")
    assert ("explore", i) in kinds(k)
    fields = cards.card_object(k.state, "p1", "extension", "p1")["fields"]
    assert fields["pending"] is False and len(fields["progress_since_50"]) == 1


def test_uncontrolled_observation_is_not_progress():
    """恒真的谓词也能到 E3：不带对照的观察不算进展（3.5.5 的 6 后半）。"""

    def observe(k):
        fid = k.obs(title="plain")
        k.verdict("p1", fid, "pass")

    k = Kernel(GATE)
    to_80(k, observe)
    assert wk.extension_pending(k.state, "p1")


def test_progress_before_50_does_not_count():
    k = Kernel(GATE)
    k.open()
    fid = controlled(k, title="early")
    rid = k.submit(HUMAN, "p1", "request_judge", {"target": fid, "judge_id": "replay"})
    ev = k.art("p1", "judge", b"early-pass")
    body = {"request": rid, "result": "pass", "version": "1", "evidence": [ev], "control_end": "fail"}
    assert k.submit(JUDGE, "p1", "judge_verdict", body) == "ok"
    assert wk.progress_since(k.state, "p1", 0) == [fid]
    assert wk.progress_since(k.state, "p1", k.state["seq"]) == []


def test_budget_add_raises_cap_and_reopens():
    k = Kernel(dataclasses.replace(GATE, open_cap_usd_milli=8000))
    i = to_80(k)
    assert k.submit(HUMAN, "p1", "budget_add", {"usd_milli": 1000}) == "schema_error"  # 门关着：须带所见的续期卡
    assert k.submit(HUMAN, "p1", "budget_add", {"usd_milli": 0, "seen": seen(k)}) == "schema_error"
    assert k.submit(HUMAN, "p1", "budget_add", {"usd_milli": 4000, "seen": seen(k)}) == "over_budget"  # 单题硬顶
    assert k.submit(HUMAN, "p1", "budget_add", {"usd_milli": 2000, "seen": seen(k)}) == "ok"
    assert k.state["problems"]["p1"]["budget"]["usd_milli"] == 7000
    assert wk.budget_view(k.state, "p1")["cap"]["usd_milli"] == 7000
    assert not wk.extension_pending(k.state, "p1")
    assert ("explore", i) in kinds(k)


def test_always_mode_has_no_gate():
    """消融臂 extension=always（也是旧题与缺省配置）：越过 80% 照常探索，没有续期卡。"""
    k = Kernel()
    i = to_80(k)
    assert "extension" not in k.state["problems"]["p1"]
    assert ("explore", i) in kinds(k)
    assert cards.card_object(k.state, "p1", "extension", "p1") is None
    assert k.submit(HUMAN, "p1", "extend", {"seen": {"seq": 1, "card_hash": "0" * 64}}) == "unknown_ref"
    assert k.submit(HUMAN, "p1", "budget_add", {"usd_milli": 1000}) == "ok"  # 追加预算不依赖续期门


def test_before_80_there_is_no_card():
    k = Kernel(GATE)
    k.open()
    assert cards.card_object(k.state, "p1", "extension", "p1") is None
    assert not wk.extension_pending(k.state, "p1")
