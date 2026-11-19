"""内核增量 8、9、10（规格 v1.5）：Problem.recall、Problem.labels、租约角色 recall、/work 的 recall 项。

另有旧日志回归：增量只加可选字段，v1.5 之前录下的日志重放结果逐字节不变。
"""

import hashlib
import json
from pathlib import Path

import pytest
from conftest import HUMAN, Kernel

from paoding_graph import views
from paoding_graph import work as wk
from paoding_graph.jcs import canonicalize
from paoding_graph.reducer import apply, empty_state
from paoding_graph.replay import replay, state_hash

SINAN = {"kind": "sinan", "id": "sn1"}
R = {"usd_milli": 100, "wall_s": 60}
GOLDEN = Path(__file__).parent / "fixtures" / "m1_log_golden.json"
H = "a" * 64


def body(k, pid="p1", **extra):
    st = k.art(pid, "input", b"statement " + pid.encode())
    return {
        "title": "t",
        "origin": {"statement_ref": st, "materials": []},
        "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
        "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["replay", "exact_match"],
        **extra,
    }


def item(k, pid="p1", mem=H, judge="replay", cls="input"):
    spec = k.art(pid, cls, b"spec " + mem.encode())
    ctl = k.art(pid, "input", b"ctl " + mem.encode())
    check = {"judge_id": judge, "spec_ref": spec, "expect": {"exit_code": 0}, "control": {"inputs": [ctl]}}
    return {"mem": mem, "title": "端口开放", "check": check}


def recall(*items, **kw):
    return {"items": list(items), "match_digest": H, **kw}


# ---------- 开题 ----------


def test_open_with_recall_and_labels(k):
    it = item(k)
    pid = k.submit(
        HUMAN, "p1", "open_problem", body(k, recall=recall(it), labels={"tags": ["b", "a", "b"], "env": "lab"})
    )
    assert pid == "ok"
    p = k.state["problems"]["p1"]
    assert p["labels"] == {"tags": ["a", "b"], "env": "lab"}
    assert p["recall"] == {"items": [it], "excluded_by_human": [], "match_digest": H}


def test_open_without_the_new_fields_is_unchanged(k):
    k.submit(HUMAN, "p1", "open_problem", body(k))
    ev = k.events[-1]["body"]
    assert "recall" not in ev and "labels" not in ev


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda k, it: recall(it, match_digest="x"), "schema_error"),
        (lambda k, it: recall(*[{**it, "mem": f"{n:064x}"} for n in range(9)]), "schema_error"),  # 至多 8 条
        (lambda k, it: recall(it, it), "schema_error"),  # mem 重复
        (lambda k, it: recall({**it, "check": {**it["check"], "judge_id": "costly"}}), "unknown_ref"),
        (
            lambda k, it: recall({**it, "check": {k2: v for k2, v in it["check"].items() if k2 != "spec_ref"}}),
            "schema_error",
        ),
        (lambda k, it: recall(it, mode="noverify"), "schema_error"),  # 不复核时 items 须为空
        (lambda k, it: recall(it, mode="maybe"), "schema_error"),
        (lambda k, it: {**recall(it), "extra": 1}, "schema_error"),
        (lambda k, it: recall({**it, "title": "x" * 120}), "schema_error"),
    ],
)
def test_bad_recall_lists_are_refused(k, mutate, code):
    it = item(k)
    assert k.submit(HUMAN, "p1", "open_problem", body(k, recall=mutate(k, it))) == code


def test_recall_specs_must_be_input_class_of_this_problem(k):
    k.open("p0")
    other = item(k, "p0")  # 别题登记的 input
    assert k.submit(HUMAN, "p1", "open_problem", body(k, recall=recall(other))) == "scope_mismatch"


def test_bad_labels_are_refused(k):
    assert k.submit(HUMAN, "p1", "open_problem", body(k, labels={"tags": [], "env": ""})) == "schema_error"
    assert k.submit(HUMAN, "p1", "open_problem", body(k, labels={"x": 1})) == "schema_error"


# ---------- /work 与租约 ----------


def kinds(k, pid="p1"):
    return [w["kind"] for w in wk.work(k.state, pid)]


def lease(k, kind):
    return k.submit(SINAN, "p1", "lease", {"kind": kind, "holder": "sn1", "reserve": R, "ttl_s": 60})


def test_recall_comes_before_bootstrap_and_only_once(k):
    k.submit(HUMAN, "p1", "open_problem", body(k, recall=recall(item(k))))
    assert kinds(k) == ["recall"]
    assert lease(k, "bootstrap") == "forbidden_op"  # Bootstrap 等召回做完
    lid = lease(k, "recall")
    assert lid.startswith("l_") and kinds(k) == []
    assert lease(k, "recall") == "conflict_leased"
    assert k.submit(SINAN, "p1", "release", {"lease": lid, "outcome": "done"}) == "ok"
    assert kinds(k) == ["bootstrap"] and lease(k, "recall") == "forbidden_op"


def test_no_recall_item_without_a_list(k):
    k.submit(
        HUMAN,
        "p1",
        "open_problem",
        body(k, recall=recall(mode="noverify", notes=[{"mem": H, "kind": "env_fact", "title": "x"}])),
    )
    assert kinds(k) == ["bootstrap"] and lease(k, "recall") == "forbidden_op"


def test_expired_recall_lease_lets_bootstrap_go(k):
    k.submit(HUMAN, "p1", "open_problem", body(k, recall=recall(item(k))))
    lid = lease(k, "recall")
    k.ts += 10**6
    assert k.submit({"kind": "watchdog", "id": "wd"}, "p1", "expire_lease", {"lease": lid}) == "ok"
    assert kinds(k) == ["bootstrap"]


# ---------- 旧日志回归 ----------


def test_m1_log_replays_byte_for_byte():
    """v1.5 之前录下的日志（web 夹具）：状态哈希、/work 与状态视图在任一前缀与链头都与当时相同。"""
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    evs = g["events"]
    s = replay(evs, apply, empty_state())
    assert state_hash(s) == g["state_hash"]
    for n, h in g["prefix_hashes"].items():
        assert state_hash(replay(evs[: int(n)], apply, empty_state())) == h
    digest = lambda x: hashlib.sha256(canonicalize(x)).hexdigest()  # noqa: E731
    for pid, v in g["views"].items():
        assert digest(wk.work(s, pid)) == v["work"] and digest(views.status(s, pid)) == v["status"]


@pytest.fixture
def k():
    return Kernel()
