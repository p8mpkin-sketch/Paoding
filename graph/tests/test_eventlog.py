"""D1：事件信封、哈希链、SQLite 日志、重放测试台。3.1.5 的 1。"""

import random
import sqlite3

import pytest

from paoding_graph.envelope import GENESIS, ChainError, EnvelopeError, verify_chain
from paoding_graph.eventlog import EventLog
from paoding_graph.replay import replay, state_hash

HUMAN = {"kind": "human", "id": "cz"}


def _log(tmp_path):
    return EventLog(tmp_path / "log.sqlite")


def _toy_apply(state, ev):
    """测试用的纯函数 reducer：只依赖事件内容，不读时钟。D2 换成真正的 reducer。"""
    s = dict(state)
    s["n"] = s.get("n", 0) + 1
    s.setdefault("by_kind", {})
    s["by_kind"] = {**s["by_kind"], ev["kind"]: s["by_kind"].get(ev["kind"], 0) + 1}
    s["last_ts"] = ev["ts"]
    s["sum"] = s.get("sum", 0) + sum(v for v in ev["body"].values() if isinstance(v, (int, float)))
    return s


def _random_log(log, rng, n=200):
    for i in range(n):
        pid = rng.choice(["p1", "p2", "p3"])
        log.append(
            problem_id=pid,
            actor=HUMAN,
            kind=rng.choice(["a", "b", "c"]),
            body={"x": rng.randint(-5, 5), "f": rng.random()},
            idem_key=f"k{i}",
            ts=1000 + i,
        )


def test_chain_per_problem(tmp_path):
    log = _log(tmp_path)
    e1, _ = log.append(problem_id="p1", actor=HUMAN, kind="open_problem", body={}, idem_key="a", ts=1)
    e2, _ = log.append(problem_id="p2", actor=HUMAN, kind="open_problem", body={}, idem_key="a", ts=2)
    e3, _ = log.append(problem_id="p1", actor=HUMAN, kind="hint", body={"t": "x"}, idem_key="b", ts=3)
    assert e1["prev_hash"] == GENESIS and e2["prev_hash"] == GENESIS
    assert e3["prev_hash"] == e1["hash"]
    assert [e["seq"] for e in (e1, e2, e3)] == [1, 2, 3]
    log.verify("p1")
    log.verify("p2")


def test_idempotent_append(tmp_path):
    log = _log(tmp_path)
    first, new1 = log.append(problem_id="p", actor=HUMAN, kind="hint", body={"t": 1}, idem_key="k", ts=1)
    again, new2 = log.append(problem_id="p", actor=HUMAN, kind="hint", body={"t": 2}, idem_key="k", ts=9)
    assert new1 and not new2 and again == first
    assert len(list(log.events("p"))) == 1


def test_append_only(tmp_path):
    log = _log(tmp_path)
    log.append(problem_id="p", actor=HUMAN, kind="hint", body={}, idem_key="k", ts=1)
    db = sqlite3.connect(tmp_path / "log.sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE events SET doc='{}'")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM events")


@pytest.mark.parametrize("field,value", [("body", {"t": "tampered"}), ("ts", 99), ("prev_hash", "1" * 64)])
def test_tamper_detected(tmp_path, field, value):
    log = _log(tmp_path)
    for i in range(3):
        log.append(problem_id="p", actor=HUMAN, kind="hint", body={"t": i}, idem_key=f"k{i}", ts=i)
    evs = list(log.events("p"))
    evs[1] = {**evs[1], field: value}
    with pytest.raises(ChainError):
        verify_chain(evs)


def test_dropped_event_detected(tmp_path):
    log = _log(tmp_path)
    for i in range(3):
        log.append(problem_id="p", actor=HUMAN, kind="hint", body={"t": i}, idem_key=f"k{i}", ts=i)
    evs = list(log.events("p"))
    with pytest.raises(ChainError):
        verify_chain([evs[0], evs[2]])


@pytest.mark.parametrize(
    "actor",
    [
        {"kind": "model", "id": "x"},
        {"kind": "human"},
        {"kind": "adapter", "id": "a", "role": "boss"},
        {"kind": "adapter", "id": "a", "class": "exec"},
    ],
)
def test_bad_actor_rejected(tmp_path, actor):
    with pytest.raises(EnvelopeError):
        _log(tmp_path).append(problem_id="p", actor=actor, kind="hint", body={}, idem_key="k", ts=1)


def test_replay_deterministic(tmp_path):
    """3.1.5 的 1：同一日志重放两次，状态哈希相同；冷启动（重新打开文件）亦同。"""
    log = _log(tmp_path)
    _random_log(log, random.Random(7))
    h1 = state_hash(replay(log.events(), _toy_apply, {}))
    h2 = state_hash(replay(log.events(), _toy_apply, {}))
    log.close()
    cold = EventLog(tmp_path / "log.sqlite")
    h3 = state_hash(replay(cold.events(), _toy_apply, {}))
    assert h1 == h2 == h3


def test_replay_detects_tamper_in_db(tmp_path):
    log = _log(tmp_path)
    _random_log(log, random.Random(1), n=20)
    log.close()
    db = sqlite3.connect(tmp_path / "log.sqlite")
    db.execute("DROP TRIGGER events_no_update")  # 模拟绕过应用层直接改库
    db.execute("UPDATE events SET doc=replace(doc, '\"ts\": 1005', '\"ts\": 1') WHERE seq=6")
    db.commit()
    with pytest.raises(ChainError):
        replay(EventLog(tmp_path / "log.sqlite").events(), _toy_apply, {})
