"""题次记录：从引擎的导出整理，折算，存取。"""

import argparse
import json

import pytest
from lj_rig import attempt

from liangju import tici
from liangju.common import Refused, read_json, write_json

PRICES = {"version": "t1", "models": {"m1": {"input": 2.0, "output": 10.0, "cache_read": 0.1, "cache_write": 2.5}}}


# 引擎交付的报告的样子：读法说明、它自己拆的子问、核对标注、「没读到的」「核对记录」两节、后面整段预评估。
DELIVERED = """> 读法：按题面点名的 2 个问题读仓库作答（引擎拆的子问一；引擎拆的子问二）。

# 回答

## q1：引擎拆的子问一

- 重试上限写死为三次 〔确认〕 `relay/retry.py:10-12`（`send`）
- 退避间隔按次数翻倍 〔推断，改写过〕（原文只支持一部分：没看到上限） `relay/retry.py:20`

## 值得集成的做法

- **批量合并**：发送前把同一目标的消息合并 〔确认〕 `relay/batch.py:5-9`

## 不建议集成的

- 全局单例的配置对象

## 拿不准的

- 断线后是否重放
- 重试带抖动（核对不支持：原文没有抖动）

## 没读到的

- relay/legacy/ 没读

## 核对记录

- 4 条结论核对了 4 条

---

# 预评估

候选一：评分 7，建议采纳。
"""

ANSWER = {
    "items": [
        {"text": "重试上限写死为三次", "verdict": "supported", "kind": "fact", "q": "q1", "facts": ["f1"], "ours": []},
        {"text": "退避间隔按次数翻倍", "verdict": "partial", "kind": "fact", "q": "q1", "facts": ["f2"], "ours": [],
         "note": "没看到上限", "rewritten": True},
        {"text": "发送前把同一目标的消息合并", "verdict": "supported", "kind": "rec", "title": "批量合并",
         "facts": ["f3"], "ours": []},
        {"text": "重试带抖动", "verdict": "unsupported", "kind": "fact", "q": "q1", "facts": [], "ours": []},
    ],
    "not_recommended": [{"text": "全局单例的配置对象"}],
    "unsure": [{"text": "断线后是否重放"}],
}  # fmt: skip
FACTS = [
    {"id": "f1", "path": "relay/retry.py", "lines": [10, 12], "symbol": "send", "side": "theirs"},
    {"id": "f2", "path": "relay/retry.py", "lines": [20, 20], "side": "theirs"},
    {"id": "f3", "path": "relay/batch.py", "lines": [5, 9], "side": "theirs"},
]


def export(tmp, *, stop="没有可追的了", answer_stops=(), gave_up=0, answer=None, route="question_led"):
    ws = tmp / "analyses" / "p1"
    (ws / "artifacts").mkdir(parents=True)
    ans = {**(answer or ANSWER), "stops": list(answer_stops)}
    if route == "question_led":
        write_json(ws / "artifacts" / "aa.json", ans)
        (ws / "facts.jsonl").write_text("".join(json.dumps(f) + "\n" for f in FACTS), encoding="utf-8")
    write_json(ws / "run.json", {"artifacts": {"ql:answer": "aa"} if route == "question_led" else {}})
    write_json(ws / "ql.json", {"route": route, "read": {"stop": stop}, "stats": {"on_defs": {"q1": 2, "q2": 0}}})
    write_json(ws / "model_stats.json", {"truncated": 1, "upstream_timeouts": 0, "gave_up": gave_up})
    return ws


def events(outcome="partial", n=3):
    cost = {"model": "m1", "tokens_in": 1000, "tokens_cached": 500, "tokens_out": 200, "usd_milli": 5}
    evs = [
        {
            "seq": 1,
            "kind": "open_problem",
            "ts": 1_000,
            "body": {"gongfa": {"jie": 2, "digest": "gg"}, "settings": {"version": 3, "digest": "ss"}},
        }
    ]
    evs += [{"seq": 2 + i, "kind": "cost", "ts": 2_000 + i, "body": cost} for i in range(n)]
    if outcome:
        evs.append({"seq": 99, "kind": "deliver", "ts": 61_000, "body": {"outcome": outcome, "answer": "art1"}})
    return evs


BUDGET = {"spent": {"usd_milli": 15}, "cap": {"usd_milli": 1000}}


def test_from_export_reads_usage_cost_time_and_own_fields(tmp_path):
    a = tici.from_export(export(tmp_path), events(), BUDGET, DELIVERED, arm="B", question="q1", rep=1, prices=PRICES)
    assert a.status == "finished" and a.models_seen == ["m1"] and (a.gongfa, a.settings) == ("gg", "ss")
    assert a.usage == {"input": 3000, "cached_input": 1500, "output": 600, "calls": 3}
    # 3000×2.0 + 1500×0.1 + 600×10.0 = 12150 百万分之一美元 → 13 毫美元（向上取整）
    assert a.cost_usd_milli == 13 and a.booked_usd_milli == 15 and a.cap_usd_milli == 1000
    assert a.elapsed_s == 60.0 and a.price_table == "t1"
    assert a.own["timeline_stop"] is False and a.own["on_defs"] == [0, 2]
    assert a.own["engine_items"][0] == {"text": "重试上限写死为三次", "verdict": "supported"}
    assert len(a.own["engine_items"]) == 4 and a.own["checks_first_pass"] is None


def test_blind_text_from_the_engine_arm_is_the_answer_alone(tmp_path):
    """交给盲判的文本只有回答本身：结论的原文与出处。引擎自己的过程产物一样都不进。"""
    a = tici.from_export(export(tmp_path), events(), BUDGET, DELIVERED, arm="B", question="q1", rep=1, prices=PRICES)
    assert a.answer == (
        "- 重试上限写死为三次（出处：relay/retry.py:10-12（send））\n"
        "- 退避间隔按次数翻倍（出处：relay/retry.py:20）\n"
        "- 批量合并：发送前把同一目标的消息合并（出处：relay/batch.py:5-9）\n"
        "\n不建议采用的：\n- 全局单例的配置对象\n"
        "\n拿不准的：\n- 断线后是否重放\n- 重试带抖动\n"
    )
    assert a.own["undelivered_items"] == 0
    for process_product in (
        "读法", "引擎拆的子问", "〔", "确认", "推断", "改写过", "原文只支持一部分", "没看到上限", "核对不支持",
        "原文没有抖动", "没读到的", "legacy", "核对记录", "4 条结论", "---", "预评估", "候选", "评分",
    ):  # fmt: skip
        assert process_product not in a.answer
    for it in ANSWER["items"]:  # 每条结论的原文逐字都在，也都在交付的报告里
        assert it["text"] in a.answer and it["text"] in DELIVERED


def test_a_conclusion_absent_from_the_delivery_is_not_handed_to_the_judge(tmp_path):
    """导出里有、交付的报告里没有的结论，不算交出去了：不进盲判的文本，只记个数。"""
    extra = {
        **ANSWER,
        "items": [*ANSWER["items"], {"text": "交付里没有的一条", "verdict": "supported", "kind": "fact"}],
    }
    ws = export(tmp_path, answer=extra)
    a = tici.from_export(ws, events(), BUDGET, DELIVERED, arm="B", question="q1", rep=1, prices=PRICES)
    assert "交付里没有的一条" not in a.answer and a.own["undelivered_items"] == 1


def test_a_run_that_did_not_read_by_question_hands_over_no_answer(tmp_path):
    """没有按题读的运行，交付的只有候选评估，没有回答：盲判那边就是没有交出回答，运行本身仍算正常结束。"""
    ws = export(tmp_path, route="general")
    report = "> 读法：题面没有点名具体的问题，走通用勘察。\n\n# 预评估\n\n候选一"
    a = tici.from_export(ws, events(), BUDGET, report, arm="B", question="q1", rep=1, prices=PRICES)
    assert a.answer is None and a.status == "finished" and a.own["undelivered_items"] == 0


@pytest.mark.parametrize(
    ("kw", "ev", "budget", "answer", "status", "timeline"),
    [
        ({"stop": "到了阅读的时间线"}, events(), BUDGET, DELIVERED, "finished", True),
        ({"answer_stops": ["到了核对的时间线"]}, events(), BUDGET, DELIVERED, "finished", True),
        ({}, events(), {"spent": {"usd_milli": 1000}, "cap": {"usd_milli": 1000}}, DELIVERED, "over_budget", False),
        ({"gave_up": 2}, events(outcome=None), BUDGET, None, "model_failure", False),
        ({}, events(outcome="blocked"), BUDGET, None, "other", False),
    ],
)
def test_status_and_timeline_stop(tmp_path, kw, ev, budget, answer, status, timeline):
    a = tici.from_export(export(tmp_path, **kw), ev, budget, answer, arm="B", question="q1", rep=1, prices=PRICES)
    assert (a.status, a.own["timeline_stop"]) == (status, timeline)


def test_conversion_refuses_a_model_missing_from_the_price_table(tmp_path):
    ev = events()
    ev[1]["body"] = {**ev[1]["body"], "model": "没有价的模型"}
    with pytest.raises(Refused):
        tici.from_export(export(tmp_path), ev, BUDGET, DELIVERED, arm="B", question="q1", rep=1, prices=PRICES)


def test_same_usage_converts_the_same_from_either_shape():
    """同一份用量，按计量事件逐条折算再合计，与按导出的合计一次折算，相差不到取整的一毫美元。"""
    one = {"input": 1000, "cached_input": 500, "output": 200}
    total = {k: v * 7 for k, v in one.items()}
    assert abs(tici.convert(PRICES, "m1", total) - 7 * tici.convert_micro(PRICES, "m1", one) / 1000) < 1


def test_save_load_roundtrip_and_bad_status(tmp_path):
    a = attempt("B", "q1", 2, "回答\n第二行")
    tici.save(tmp_path, a)
    tici.save(tmp_path, attempt("B", "q2", 1, None))
    back = tici.load_all(tmp_path)
    assert (
        back[0] == a
        and back[1].answer is None
        and "answer" not in read_json(tmp_path / "attempts" / "B" / "q1" / "2" / "attempt.json")
    )
    with pytest.raises(Refused):
        tici.save(tmp_path, attempt("B", "q3", 1, "x", status="挺好"))


def test_collect_from_a_dump_directory(tmp_path):
    export(tmp_path)
    dump = tmp_path / "dump"
    write_json(dump / "p1.events.json", {"events": events()})
    write_json(dump / "p1.budget.json", BUDGET)
    (dump / "p1.answer.md").write_text(DELIVERED, encoding="utf-8")
    write_json(tmp_path / "runs.json", [{"pid": "p1", "arm": "B", "question": "q1", "rep": 1}])
    prices = tmp_path / "prices.yaml"
    prices.write_text(json.dumps(PRICES), encoding="utf-8")
    rc = tici.main(
        [
            "collect",
            "--runs",
            str(tmp_path / "runs.json"),
            "--home",
            str(tmp_path),
            "--dump",
            str(dump),
            "--out",
            str(tmp_path / "batch"),
            "--prices",
            str(prices),
        ]
    )
    assert rc == 0 and tici.load_all(tmp_path / "batch")[0].answer.startswith("- 重试上限写死为三次（出处：")
