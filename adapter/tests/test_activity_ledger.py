"""可回放的实时性（焚决首炼，炼档 001：docs/design/fenjue/dossiers/001-replayable-live.md）。

三条新生维与本火维，各一组：
- 实时所见可回放率：每到一个锚点记下实时面板当时已入账的条目，事后按那一段的 seq 回放，逐字节相同；
- 活动链校验：改一个字节、换一段次序、丢一段，校验都报错，不给部分结果；
- 执行行可追率：exec 的结果条目带 ArtifactId，且那份留档是 exec 类；
- 本火维：入账段里没有原话里的凭据；入账只用 authored 类；关掉入账（异火臂 A′，即 #115 原样）时不登记任何段。

台子沿用 test_solve：假 CLI 走真的代理、真的工具端点、真的图服务。
"""

import json

import pytest
from adapter_rig import graph, upstream  # noqa: F401  fixture
from test_solve import DELIVER, EXEC, TOKEN, lease_solve, make

from paoding_adapter import activity as act
from paoding_graph.contract import canonicalize


def call(tid, name, inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, text):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def say(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


# ---------------------------------------------------------------- 成链与入账段（纯函数）


def test_items_are_chained_and_segments_replay(tmp_path):
    log = act.ActivityLog(tmp_path, lease="l_7")
    log.feed(say("先看看"), 1)
    log.feed(call("t1", EXEC, {"cmd": "ls"}), 1)
    log.feed(result("t1", json.dumps({"artifact": "a_12", "exit_code": 0})), 1)
    seg1, last1 = log.segment()
    log.mark(last1, "a_20")
    log.feed(say("再看一个"), 1)
    seg2, last2 = log.segment()
    log.mark(last2, "a_25")
    assert log.segment() is None  # 没有新条目就没有新段
    items = act.replay_segments([seg1, seg2])
    assert items == [act.chained(x) for x in log.snapshot()]  # 本机墙钟 t 不入账
    assert [x["n"] for x in items] == [1, 2, 3, 4] and log.anchored == 4 and log.segments == ["a_20", "a_25"]
    assert items[0]["h"] == act.item_hash(act.GENESIS, items[0])
    assert all(items[i]["h"] == act.item_hash(items[i - 1]["h"], items[i]) for i in range(1, 4))
    assert json.loads(seg2)["prev"] == items[2]["h"]  # 下一段接在上一段的链头上


def test_tampering_is_always_caught(tmp_path):
    log = act.ActivityLog(tmp_path, lease="l_7")
    log.feed(say("甲"), 1)
    seg1, last = log.segment()
    log.mark(last, "a_1")
    log.feed(say("乙"), 1)
    seg2, _ = log.segment()
    doc = json.loads(seg1)
    doc["items"][0]["text"] = "丙"  # 改一个字
    forged = canonicalize(doc)
    for bad in ([forged, seg2], [seg2, seg1], [seg2], [seg1, b"not json"]):
        with pytest.raises(act.ChainBroken):
            act.replay_segments(bad)
    assert act.replay_segments([]) == []


def test_only_exec_results_carry_an_artifact(tmp_path):
    log = act.ActivityLog(tmp_path)
    log.feed(call("t1", EXEC, {"cmd": "ls"}), 1)
    log.feed(call("t2", "mcp__paoding__show", {"artifact": "a_3"}), 1)
    log.feed(result("t1", json.dumps({"artifact": "a_12", "exit_code": 0})), 1)
    log.feed(result("t2", json.dumps({"artifact": "a_3", "text": "..."})), 1)
    log.feed(result("t9", "not json"), 1)
    res = {x["id"]: x for x in log.snapshot() if x["kind"] == "result"}
    assert res["t1"]["artifact"] == "a_12" and "artifact" not in res["t2"] and "artifact" not in res["t9"]


# ---------------------------------------------------------------- 真会话


SCRIPT = [
    {"tool": EXEC, "input": {"cmd": "python -c 'print(6*7)'"}, "say": f"先算一下，令牌 {TOKEN} 先不用。"},
    {"tool": EXEC, "input": {"cmd": "python -c 'print(7*6)'"}, "say": "再核一次。"},
    {
        "tool": DELIVER,
        "input": {"outcome": "answered", "answer": "42", "claims": [{"text": "6×7=42", "refs": ["$r1.artifact"]}]},
        "say": "交付。",
    },
]


def run_watched(rig, lid):
    """跑完一个会话，同时在每个锚点记下实时面板当时已入账的条目。"""
    seen: list[tuple[str, list]] = []
    orig = act.ActivityLog.mark

    def spy(self, last, aid):
        seen.append((aid, [dict(x) for x in self.snapshot()[:last]]))
        orig(self, last, aid)

    act.ActivityLog.mark = spy
    try:
        rec = rig.run(lid)
    finally:
        act.ActivityLog.mark = orig
    return rec, seen


def segments(graph, lid):  # noqa: F811
    return sorted(
        (a for a in graph.state["artifacts"].values() if a.get("media_type") == act.SEGMENT_MEDIA),
        key=lambda a: int(a["id"][2:]),
    )


def test_what_was_seen_live_replays_byte_for_byte(tmp_path, graph, upstream):  # noqa: F811
    rig = make(tmp_path, graph, upstream)
    try:
        lid = lease_solve(graph)
        rig.script(SCRIPT)
        rec, seen = run_watched(rig, lid)
        assert rec.release["outcome"] == "done", rec.release
        segs = segments(graph, lid)
        assert len(segs) == len(seen) >= 3  # 两次 exec 返回、一轮结束（收尾那次若没有新条目就不登记）
        assert all(a["class"] == "authored" and a["producer"]["session"] == lid for a in segs)
        assert [a["parents"] for a in segs] == [[], *[[s["id"]] for s in segs[:-1]]]  # 段与段用 parents 连起来
        # 新生维一：实时所见可回放率 = 100%
        for aid, live in seen:
            back = rig.runner.activity(lid, as_of=int(aid[2:]))
            assert canonicalize(back["items"]) == canonicalize([act.chained(x) for x in live]), aid
            assert back["anchored_through"] == len(live) and back["status"] == "replay" and back["now"] is None
        # 回放到第一段之前：那一刻还没有入账的活动
        assert rig.runner.activity(lid, as_of=int(segs[0]["id"][2:]) - 1) is None
        # 新生维三：执行行可追率 = 100%
        end = rig.runner.activity(lid)
        assert end["anchored_through"] == end["total"]  # 收尾后全部入账
        execs = [x for x in end["items"] if x["kind"] == "result" and x.get("artifact")]
        calls = [x for x in end["items"] if x["kind"] == "call" and x["tool"] == "exec"]
        assert len(execs) == len(calls) == 2
        assert all(graph.state["artifacts"][x["artifact"]]["class"] == "exec" for x in execs)
        # 本火维：入账段里没有原话里的凭据
        for a in segs:
            assert TOKEN.encode() not in rig.blobs.get(a["hash"])
    finally:
        rig.close()


def test_the_ledger_outlives_the_session_directory(tmp_path, graph, upstream):  # noqa: F811
    import shutil

    rig = make(tmp_path, graph, upstream)
    try:
        lid = lease_solve(graph)
        rig.script(SCRIPT)
        rig.run(lid)
        before = rig.runner.activity(lid)
        shutil.rmtree(tmp_path / "sessions" / lid)  # 工作区按期清掉之后
        after = rig.runner.activity(lid)
        assert after is not None and canonicalize(after["items"]) == canonicalize(
            [act.chained(x) for x in before["items"]]
        )
    finally:
        rig.close()


def test_without_the_ledger_nothing_is_registered(tmp_path, graph, upstream):  # noqa: F811
    """异火臂 A′（#115 原样）：不入账，事件账里没有活动段，面板照旧能读，只是不标已入账。"""
    rig = make(tmp_path, graph, upstream)
    rig.cfg.ledger_roles = ()
    try:
        lid = lease_solve(graph)
        rig.script(SCRIPT)
        rec = rig.run(lid)
        assert rec.release["outcome"] == "done"
        assert segments(graph, lid) == []
        end = rig.runner.activity(lid)
        assert end["anchored_through"] is None and end["calls"] == 3
        assert rig.runner.activity(lid, as_of=graph.head()) is None
    finally:
        rig.close()


def test_cap_leaves_only_round_ends_and_the_closing_anchor(tmp_path, graph, upstream):  # noqa: F811
    rig = make(tmp_path, graph, upstream)
    rig.cfg.anchor_cap = 0
    try:
        lid = lease_solve(graph)
        rig.script(SCRIPT)
        rig.run(lid)
        segs = segments(graph, lid)
        assert 1 <= len(segs) <= 2  # 一轮结束一次；收尾时若还有没入账的再一次
        assert rig.runner.activity(lid)["anchored_through"] == rig.runner.activity(lid)["total"]
    finally:
        rig.close()


def test_a_problem_in_the_standing_holdout_runs_the_previous_fire(tmp_path, graph, upstream, monkeypatch):  # noqa: F811
    """常设留出（焚决 F5，04 §5）：分到留出的题在 H6 上用上一团火 h6.activity（#115 原样），不入账；
    部署的开关照旧开着。分到哪边由题号的确定性哈希定（fenjue/tests/test_holdout.py），这里把比例拉满。"""
    import json

    from paoding_fenjue.contract import GONGFA_ENV, gongfa

    g = {k: v for k, v in gongfa().items() if k != "digest"}
    (tmp_path / "gongfa.json").write_text(json.dumps({**g, "holdout_permille": 1000}), encoding="utf-8")
    monkeypatch.setenv(GONGFA_ENV, str(tmp_path / "gongfa.json"))
    gongfa.cache_clear()
    rig = make(tmp_path, graph, upstream)
    assert "solve" in rig.cfg.ledger_roles
    try:
        lid = lease_solve(graph)
        rig.script(SCRIPT)
        assert rig.run(lid).release["outcome"] == "done"
        assert segments(graph, lid) == []
        assert rig.runner.activity(lid)["anchored_through"] is None
    finally:
        rig.close()
        monkeypatch.delenv(GONGFA_ENV)
        gongfa.cache_clear()
