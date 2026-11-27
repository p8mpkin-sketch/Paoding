"""题次记录：从引擎的导出整理，折算，存取。"""

import argparse
import json

import pytest
from lj_rig import attempt

from liangju import tici
from liangju.common import Refused, read_json, write_json

PRICES = {"version": "t1", "models": {"m1": {"input": 2.0, "output": 10.0, "cache_read": 0.1, "cache_write": 2.5}}}


def export(tmp, *, stop="没有可追的了", answer_stops=(), gave_up=0):
    ws = tmp / "analyses" / "p1"
    (ws / "artifacts").mkdir(parents=True)
    ans = {"items": [{"text": "甲", "verdict": "supported", "kind": "fact"}], "stops": list(answer_stops)}
    write_json(ws / "artifacts" / "aa.json", ans)
    write_json(ws / "run.json", {"artifacts": {"ql:answer": "aa"}})
    write_json(
        ws / "ql.json", {"route": "question_led", "read": {"stop": stop}, "stats": {"on_defs": {"q1": 2, "q2": 0}}}
    )
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
    a = tici.from_export(export(tmp_path), events(), BUDGET, "回答", arm="B", question="q1", rep=1, prices=PRICES)
    assert a.status == "finished" and a.models_seen == ["m1"] and (a.gongfa, a.settings) == ("gg", "ss")
    assert a.usage == {"input": 3000, "cached_input": 1500, "output": 600, "calls": 3}
    # 3000×2.0 + 1500×0.1 + 600×10.0 = 12150 百万分之一美元 → 13 毫美元（向上取整）
    assert a.cost_usd_milli == 13 and a.booked_usd_milli == 15 and a.cap_usd_milli == 1000
    assert a.elapsed_s == 60.0 and a.price_table == "t1"
    assert a.own["timeline_stop"] is False and a.own["on_defs"] == [0, 2]
    assert a.own["engine_items"] == [{"text": "甲", "verdict": "supported"}] and a.own["checks_first_pass"] is None


@pytest.mark.parametrize(
    ("kw", "ev", "budget", "answer", "status", "timeline"),
    [
        ({"stop": "到了阅读的时间线"}, events(), BUDGET, "回答", "finished", True),
        ({"answer_stops": ["到了核对的时间线"]}, events(), BUDGET, "回答", "finished", True),
        ({}, events(), {"spent": {"usd_milli": 1000}, "cap": {"usd_milli": 1000}}, "回答", "over_budget", False),
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
        tici.from_export(export(tmp_path), ev, BUDGET, "回答", arm="B", question="q1", rep=1, prices=PRICES)


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
    (dump / "p1.answer.md").write_text("回答", encoding="utf-8")
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
    assert rc == 0 and tici.load_all(tmp_path / "batch")[0].answer == "回答"
