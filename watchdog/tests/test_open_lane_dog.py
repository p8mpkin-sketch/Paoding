"""哮天犬在开放道（docs/design/open-lane/ §3.3）：墙钟到 90% 叫求解会话收尾交付，每个租约只叫一次；
到点关题时终态按交付算（有回答即 delivered），不是一律 unsolved。"""

import hashlib

from paoding_watchdog.contract import DogConfig, Watchdog

from paoding_graph.contract import Config, GraphService, TokenRegistry


class Clock:
    def __init__(self):
        self.t = 1_000_000

    def __call__(self):
        return self.t


class Recorder:
    def __init__(self):
        self.soft, self.kills = [], []

    def soft_line(self, lid):
        self.soft.append(lid)

    def kill(self, lid, reason):
        self.kills.append((lid, reason))


def stand_up(tmp_path):
    reg = TokenRegistry()
    for actor, tok in [
        ({"kind": "human", "id": "cz"}, "h"),
        ({"kind": "sinan", "id": "sn1"}, "s"),
        ({"kind": "watchdog", "id": "wd"}, "w"),
    ]:
        reg.issue(actor, tok)
    clock = Clock()
    g = GraphService(tmp_path / "g.sqlite", Config(judges={}), reg, clock)
    st = b"statement"
    out = g.submit(
        "h",
        "p1",
        "open",
        [
            {
                "op": "register_artifact",
                "body": {
                    "hash": hashlib.sha256(st).hexdigest(),
                    "size": 9,
                    "media_type": "text/plain",
                    "class": "input",
                },
            },
            {
                "op": "open_problem",
                "body": {
                    "title": "t",
                    "origin": {"statement_ref": "$0", "materials": []},
                    "goal": {"statement": "查清楚 X", "accept": "open"},
                    "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
                    "budget": {"usd_milli": 1000, "wall_s": 100, "verify_share": 0.2, "bootstrap_share": 0.3},
                    "env": {"base": "basic", "baseline_ref": "base@1"},
                    "judges": [],
                },
            },
        ],
    )
    assert out["ok"], out
    lease = {"kind": "solve", "holder": "sn1", "reserve": {"usd_milli": 900, "wall_s": 100}, "ttl_s": 600}
    lid = g.submit("s", "p1", "l", [{"op": "lease", "body": lease}])["results"][0]["id"]
    rec = Recorder()
    return g, Watchdog(DogConfig(token="w"), g, g, rec, clock=clock), rec, clock, lid


def test_wall_soft_line_asks_the_solver_to_deliver_once(tmp_path):
    g, dog, rec, clock, lid = stand_up(tmp_path)
    opened = g.state["problems"]["p1"]["opened_ts"]
    clock.t = opened + 80_000  # 80%
    assert dog.tick().soft == [] and rec.soft == []
    clock.t = opened + 90_000  # 90%：收尾保留线
    assert dog.tick().soft == [lid] and rec.soft == [lid]
    clock.t = opened + 95_000
    assert dog.tick().soft == [] and rec.soft == [lid]  # 只叫一次
    assert not g.state["problems"]["p1"].get("closed")


def test_time_up_closes_with_the_delivery_counted(tmp_path):
    g, dog, rec, clock, lid = stand_up(tmp_path)
    g.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": "solve"}, "a")
    data = b"X is 42"
    ans = {"hash": hashlib.sha256(data).hexdigest(), "size": len(data), "media_type": "text/plain", "class": "authored"}
    out = g.submit(
        "a",
        "p1",
        "d",
        [{"op": "register_artifact", "body": ans}, {"op": "deliver", "body": {"outcome": "partial", "answer": "$0"}}],
    )
    assert out["ok"], out
    clock.t = g.state["problems"]["p1"]["opened_ts"] + 101_000  # 墙钟用完
    dog.tick()
    p = g.state["problems"]["p1"]
    assert p["closed"] and p["terminal"] == "delivered"
