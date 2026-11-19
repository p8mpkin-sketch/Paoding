"""时限与花费分开（docs/design/external-verdict/ §5.6，往返意见 b）：哮天犬的三件事在 wall_mode 两种取值下各测一遍。

- elapsed（缺省）：旧行为逐字不变，开题墙钟走满 wall_s 就关题，花费为 0 也关（复现用例 4b 的今天）。
- spend：wall_s 只管花费墙钟；开题墙钟走满 wall_s 不关；花费墙钟用尽、最长存活 life_s 到、deadline 到，各自关题；
  deadline 到了而延迟判官的回执还在路上，settle_s 之内不关，之后关。
"""

import dataclasses
import hashlib

import pytest
from paoding_watchdog.contract import DogConfig, Watchdog

from paoding_graph.contract import Config, GraphService, TokenRegistry

EXT = {
    "version": "1",
    "grade": "decisive",
    "kind": "deferred",
    "max_cost": 0.0,
    "authority": "external",
    "connector": {"id": "plat", "version": "1", "digest": "c" * 64},
}
CFG = Config(
    judges={
        "exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0},
        "ext": EXT,
    }
)
R = {"usd_milli": 100, "wall_s": 600}
WALL = 3600
LIFE = 7 * 86400


class Clock:
    def __init__(self):
        self.t = 1_000_000

    def __call__(self):
        self.t += 1
        return self.t


class Recorder:
    def __init__(self):
        self.kills = []

    def soft_line(self, lid):
        pass

    def kill(self, lid, reason):
        self.kills.append((lid, reason))


def _art(content: bytes, cls: str = "input") -> dict:
    return {
        "op": "register_artifact",
        "body": {
            "hash": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "media_type": "text/plain",
            "class": cls,
        },
    }


def make(tmp_path, mode: str, *, external: bool = False, deadline_in: int | None = None):
    reg = TokenRegistry()
    for actor, tok in [
        ({"kind": "human", "id": "cz"}, "h"),
        ({"kind": "sinan", "id": "sn1"}, "s"),
        ({"kind": "adapter", "id": "ad1"}, "a"),
        ({"kind": "watchdog", "id": "wd"}, "w"),
        ({"kind": "judge", "id": "jr1"}, "j"),
    ]:
        reg.issue(actor, tok)
    clock = Clock()
    g = GraphService(tmp_path / "g.sqlite", dataclasses.replace(CFG, wall_mode=mode, life_s=LIFE), reg, clock)
    ops = [_art(b"statement")]
    goal = {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"}
    if external:
        goal = {
            "statement": "平台回执为通过",
            "check": {"judge_id": "ext", "binding": {"connector": "plat", "task": "T-17", "max_submissions": 3}},
            "max_attempts": 3,
            "accept": "judge",
        }
    body = {
        "title": "t",
        "origin": {"statement_ref": "$0", "materials": []},
        "goal": goal,
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": 100_000, "wall_s": WALL, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["exact_match", "ext"],
    }
    if deadline_in is not None:
        ops.append(_art(b"resource notice"))
        body["origin"]["materials"] = ["$1"]
        body["deadline"] = {"source": "external", "at": clock.t + deadline_in * 1000, "bound_by": "$1"}
    ops.append({"op": "open_problem", "body": body})
    out = g.submit("h", "p1", "open", ops)
    assert out["ok"], out
    rec = Recorder()
    dog = Watchdog(DogConfig(token="w", settle_s=600), g, g, rec, clock=clock)
    return g, dog, rec, clock


def lease(g, kind="bootstrap", ttl=10**6, key="l"):
    out = g.submit(
        "s", "p1", key, [{"op": "lease", "body": {"kind": kind, "holder": "sn1", "reserve": R, "ttl_s": ttl}}]
    )
    assert out["ok"], out
    return out["results"][0]["id"]


def spend_wall(g, lid, wall_s, key):
    body = {
        "task_id": lid,
        "source": "proxy",
        "tokens_in": 0,
        "tokens_cached": 0,
        "tokens_out": 0,
        "usd_milli": 0,
        "wall_s": wall_s,
        "price_table": "t@1",
    }
    assert g.submit("a", "p1", key, [{"op": "cost", "body": body}])["ok"]


def test_open_stamps_mode(tmp_path):
    g, *_ = make(tmp_path, "spend")
    p = g.state["problems"]["p1"]
    assert p["wall_mode"] == "spend" and p["life_s"] == LIFE
    (tmp_path / "b").mkdir()
    g2, *_ = make(tmp_path / "b", "elapsed")
    assert (
        "wall_mode" not in g2.state["problems"]["p1"] and "life_s" not in g2.state["problems"]["p1"]
    )  # 事件体与旧版相同


@pytest.mark.parametrize("mode,closed", [("elapsed", True), ("spend", False)])
def test_4b_elapsed_wall_with_zero_spend(tmp_path, mode, closed):
    """复现用例 4b 在两种取值下：花费 0，开题墙钟走满 wall_s。elapsed 照旧关（缺省行为没变），spend 不关。"""
    g, dog, rec, clock = make(tmp_path, mode)
    lid = lease(g)
    clock.t += WALL * 1000
    r = dog.tick()
    assert (r.closed == ["p1"]) is closed
    assert g.state["problems"]["p1"]["closed"] is closed
    assert (rec.kills == [(lid, "wall_s")]) is closed


def test_spend_wall_exhausted_closes(tmp_path):
    g, dog, rec, clock = make(tmp_path, "spend")
    lid = lease(g)
    spend_wall(g, lid, WALL - 1, "c1")
    assert dog.tick().closed == []
    spend_wall(g, lid, 1, "c2")
    r = dog.tick()
    assert r.closed == ["p1"] and rec.kills == [(lid, "wall_s")]
    assert g.state["problems"]["p1"]["terminal"] == "unsolved"


def test_spend_life_closes(tmp_path):
    g, dog, rec, clock = make(tmp_path, "spend")
    lid = lease(g)
    clock.t += (LIFE - 10) * 1000
    assert dog.tick().closed == []
    clock.t += 10 * 1000
    r = dog.tick()
    assert r.closed == ["p1"] and rec.kills == [(lid, "life_s")]


@pytest.mark.parametrize("mode", ["elapsed", "spend"])
def test_deadline_closes(tmp_path, mode):
    """deadline 在两种取值下都执行；早于 wall_s 到点时以 deadline 关题。"""
    g, dog, rec, clock = make(tmp_path, mode, deadline_in=WALL // 2)
    lid = lease(g)
    clock.t += (WALL // 2 - 5) * 1000
    assert dog.tick().closed == []
    clock.t += 10 * 1000
    r = dog.tick()
    assert r.closed == ["p1"] and rec.kills == [(lid, "deadline")]


def _pending_verdict(g, clock):
    cand = g.submit("h", "p1", "cand", [_art(b"FLAG-x")])["results"][0]["id"]
    rid = g.submit(
        "h", "p1", "rq", [{"op": "request_judge", "body": {"target": "goal", "judge_id": "ext", "candidate": cand}}]
    )["results"][0]["id"]
    jl = g.submit(
        "j",
        "p1",
        "jl",
        [{"op": "lease", "body": {"kind": "judge", "target": rid, "holder": "jr1", "reserve": R, "ttl_s": 60}}],
    )["results"][0]["id"]
    body = _art(b"receipt: pending", "judge")["body"]
    body["exec"] = {
        "sandbox_id": "builtin",
        "base": "builtin",
        "baseline_ref": "builtin",
        "tool": "judge",
        "command": "ext",
        "cwd": "/",
        "exit_code": 0,
        "touched": [],
        "started_at": clock.t,
        "ended_at": clock.t,
        "truncated": False,
    }
    aid = g.submit("j", "p1", "ev2", [{"op": "register_artifact", "body": body}])["results"][0]["id"]
    v = g.submit(
        "j",
        "p1",
        "v",
        [
            {
                "op": "judge_verdict",
                "body": {
                    "request": rid,
                    "result": "inconclusive",
                    "reason": "pending",
                    "recheck_at": clock.t + 60_000,
                    "version": "1",
                    "evidence": [aid],
                },
            }
        ],
    )
    assert v["ok"], v
    g.submit("j", "p1", "jr", [{"op": "release", "body": {"lease": jl, "outcome": "done"}}])
    return rid


@pytest.mark.parametrize("mode", ["elapsed", "spend"])
def test_deadline_waits_for_pending_receipt_within_settle(tmp_path, mode):
    """deadline 到了：工作租约停掉；延迟判官的回执还在路上，settle_s（600 秒）之内不关题，之后关。"""
    g, dog, rec, clock = make(tmp_path, mode, external=True, deadline_in=WALL // 2)
    lid = lease(g)
    _pending_verdict(g, clock)
    assert any(i["kind"] == "rejudge" and i["why"] == "pending" for i in g.work("p1"))
    clock.t += (WALL // 2 + 1) * 1000
    r = dog.tick()
    assert r.closed == [] and rec.kills == [(lid, "deadline")]
    assert not g.state["problems"]["p1"]["closed"]
    clock.t += 600 * 1000
    r = dog.tick()
    assert r.closed == ["p1"]
