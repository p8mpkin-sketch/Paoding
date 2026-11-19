"""司南照 /work 做资源占用的排队（规格 v1.5 §4.1、增量 11）。司南自己不判冲突，只照做。

两个会话同时要写同一条规则：第一个开出来，第二个排队，不同规则的第三个照常并行；第一个结束后第二个才回到 /work。
"""

import threading

from test_loop import World, active, to_explore

R1 = {"resource": "net", "pattern": "target-b:22", "actions": ["connect"], "risk": "r1"}


def test_two_sessions_writing_the_same_rule_second_queues(tmp_path):
    w = World(tmp_path)
    w.scope = [w.scope[0], R1, {**R1, "pattern": "target-c:22"}]
    w.gains = (0.9, 0.5, 0.1)
    w.intent_extra = (
        {"risk": "r1", "touches": [{"rule": 1, "mode": "write"}]},
        {"risk": "r1", "touches": [{"rule": 1, "mode": "write"}]},
        {"risk": "r1", "touches": [{"rule": 2, "mode": "write"}]},
    )
    first, second, third = sorted(to_explore(w), key=lambda i: -w.svc.state["intents"][i]["expected_gain"])
    w.gate = threading.Event()
    a = w.sinan.dispatch("p1")
    assert a["started"] == {"kind": "explore", "target": first}
    # 估值上 second 排在 third 前，但它要写的规则 1 正被占着：司南跳过它，开 third
    b = w.sinan.dispatch("p1")
    assert b["started"] == {"kind": "explore", "target": third}
    assert w.sinan.dispatch("p1") == {"wait": "in_flight"}
    assert sorted(l["target"] for l in active(w, "explore")) == sorted([first, third])
    work = [(x["kind"], x.get("target")) for x in w.svc.work("p1")]
    assert ("explore", second) not in work
    out = w.sub(
        "tok-sinan",
        "p1",
        [
            {
                "op": "lease",
                "body": {
                    "kind": "explore",
                    "target": second,
                    "holder": "sn1",
                    "reserve": {"usd_milli": 1, "wall_s": 1},
                    "ttl_s": 60,
                },
            }
        ],
    )
    assert not out["ok"] and out["results"][0]["code"] == "conflict_leased"
    w.gate.set()
    while w.sinan.in_flight():
        w.sinan.collect(5)
    # 第一个结束：第二个回到 /work，可以开了
    assert ("explore", second) in [(x["kind"], x.get("target")) for x in w.svc.work("p1")]
    assert [r["target"] for r in w.ran if r["kind"] == "explore"].count(second) == 0
