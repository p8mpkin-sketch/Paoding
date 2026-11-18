"""哮天犬：过期回收、软线通知、硬顶终止、题预算与墙钟关题、孤儿清扫、健康告警。

验收：3.4.5 的 3（租约到期 → Intent 重开，已提交论断仍在）；3.5.5 的 4（哮天犬侧：软线 → 收尾通知，
硬顶 → 终止）；3.5.4 的“题预算耗尽，题以 unsolved 关闭”。会话侧用记录器代替，端到端见 tests/integration。
"""
import hashlib

import pytest
from paoding_watchdog.contract import DogConfig, Watchdog

from paoding_graph.contract import Config, GraphService, TokenRegistry

CFG = Config(judges={"replay": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.01},
                     "exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0}})
R = {"usd_milli": 100, "wall_s": 600}


class Clock:
    def __init__(self):
        self.t = 1_000_000

    def __call__(self):
        self.t += 1
        return self.t


class Recorder:
    def __init__(self):
        self.soft, self.kills = [], []

    def soft_line(self, lid):
        self.soft.append(lid)

    def kill(self, lid, reason):
        self.kills.append((lid, reason))


@pytest.fixture
def env(tmp_path):
    reg = TokenRegistry()
    for actor, tok in [({"kind": "human", "id": "cz"}, "h"), ({"kind": "sinan", "id": "sn1"}, "s"),
                       ({"kind": "adapter", "id": "ad1"}, "a"), ({"kind": "watchdog", "id": "wd"}, "w"),
                       ({"kind": "executor", "id": "ex1"}, "e")]:
        reg.issue(actor, tok)
    clock = Clock()
    g = GraphService(tmp_path / "g.sqlite", CFG, reg, clock)
    st = b"statement"
    g.submit("h", "p1", "open", [
        {"op": "register_artifact", "body": {"hash": hashlib.sha256(st).hexdigest(), "size": len(st),
                                              "media_type": "text/plain", "class": "input"}},
        {"op": "open_problem", "body": {
            "title": "t", "origin": {"statement_ref": "$0", "materials": []},
            "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
            "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
            "budget": {"usd_milli": 1000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
            "env": {"base": "basic", "baseline_ref": "base@1"}, "judges": ["exact_match", "replay"]}}])
    rec = Recorder()
    swept = []
    dog = Watchdog(DogConfig(token="w"), g, g, rec, sweep=lambda: swept.append(1) or ["pd-orphan"], clock=clock)
    return g, dog, rec, clock


def lease(g, kind="bootstrap", target=None, reserve=R, ttl=120, key="l"):
    out = g.submit("s", "p1", key, [{"op": "lease", "body": {"kind": kind, "holder": "sn1", "reserve": reserve,
                                                             "ttl_s": ttl, **({"target": target} if target else {})}}])
    assert out["ok"], out
    return out["results"][0]["id"]


def cost(g, lid, usd, key):
    out = g.submit("a", "p1", key, [{"op": "cost", "body": {"task_id": lid, "source": "proxy", "tokens_in": 1,
                                                             "tokens_cached": 0, "tokens_out": 1, "usd_milli": usd,
                                                             "wall_s": 0, "price_table": "t@1"}}])
    assert out["ok"], out


def explore(g):
    b = lease(g, key="lb")
    g.submit("s", "p1", "rb", [{"op": "release", "body": {"lease": b, "outcome": "nothing"}}])
    iid = g.submit("h", "p1", "i", [{"op": "add_intent", "body": {
        "title": "x", "premises": [], "risk": "r0", "budget": R}}])["results"][0]["id"]
    return iid, lease(g, "explore", iid, key="le")


def test_nothing_to_do(env):
    g, dog, rec, clock = env
    lease(g)
    r = dog.tick()
    assert (r.expired, r.soft, r.killed, r.closed, r.alerts) == ([], [], [], [], [])
    assert r.swept == ["pd-orphan"]


def test_expired_lease_reopens_intent_facts_survive(env):
    """3.4.5 的 3：Adapter 死掉后租约到期，哮天犬回收，Intent 重开，此前提交的论断仍在。"""
    from paoding_graph.contract import intent_status
    g, dog, rec, clock = env
    iid, lid = explore(g)
    tok = g.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": "explore"})
    prov = {"sandbox_id": "s", "base": "b", "baseline_ref": "r", "tool": "shell", "command": "true", "cwd": "/",
            "exit_code": 0, "touched": [], "started_at": 1, "ended_at": 2, "truncated": False}
    art = g.submit("e", "p1", "x", [{"op": "register_artifact", "body": {
        "hash": "ab" * 32, "size": 1, "media_type": "text/plain", "class": "exec", "exec": prov}}])
    out = g.submit(tok, "p1", "f", [{"op": "add_fact", "body": {
        "title": "观察", "summary": "", "claim_type": "observation", "premises": [],
        "check": {"judge_id": "replay", "expect": {}}, "grounds": [art["results"][0]["id"]]}}])
    assert out["ok"], out
    assert intent_status(g.state, "p1", iid) == "leased"
    assert dog.tick().expired == []
    clock.t += 121_000
    r = dog.tick()
    assert r.expired == [lid] and rec.kills == [(lid, "expired")]
    assert intent_status(g.state, "p1", iid) == "open"
    assert [f["title"] for f in g.state["facts"].values()] == ["观察"]
    assert dog.tick().expired == []                             # 只回收一次


def test_soft_line_once_then_hard_kill(env):
    g, dog, rec, clock = env
    lid = lease(g)
    cost(g, lid, 85, "c1")
    assert dog.tick().soft == []
    cost(g, lid, 5, "c2")                                       # 90 = 软线
    assert dog.tick().soft == [lid] and rec.soft == [lid]
    assert dog.tick().soft == []                                # 每个任务只通知一次
    cost(g, lid, 10, "c3")                                      # 100 = 硬顶
    r = dog.tick()
    assert r.killed == [(lid, "budget")] and rec.kills == [(lid, "budget")]
    dog.tick()
    assert rec.kills == [(lid, "budget")]                       # 不重复终止


def test_problem_budget_exhausted_closes_unsolved(env):
    g, dog, rec, clock = env
    lid = lease(g, reserve={"usd_milli": 300, "wall_s": 600})
    cost(g, lid, 250, "c1")
    g.submit("s", "p1", "r", [{"op": "release", "body": {"lease": lid, "outcome": "done"}}])
    for i in range(3):
        l2 = lease(g, "reason", reserve={"usd_milli": 250, "wall_s": 600}, key=f"l{i}")
        cost(g, l2, 250, f"c{i + 2}")
        if i < 2:
            g.submit("s", "p1", f"r{i}", [{"op": "release", "body": {"lease": l2, "outcome": "done"}}])
            g.submit("h", "p1", f"h{i}", [{"op": "hint", "body": {"text": f"再想想 {i}"}}])
    r = dog.tick()
    assert r.closed == ["p1"] and l2 in [k[0] for k in r.killed]
    p = g.state["problems"]["p1"]
    assert p["closed"] and p["terminal"] == "unsolved"
    [ev] = [e for e in g.log.events() if e["kind"] == "close_problem"]
    assert ev["body"]["reason"] == "problem_budget" and ev["actor"]["kind"] == "watchdog"
    assert dog.tick().closed == []                              # 关过的题不再处理


def test_wall_clock_exhausted_closes(env):
    g, dog, rec, clock = env
    lease(g)
    clock.t += 3600 * 1000
    r = dog.tick()
    assert r.closed == ["p1"] and r.expired                     # 墙钟走过，租约也已到期，先被回收
    assert g.state["problems"]["p1"]["terminal"] == "unsolved"


def test_backend_unhealthy_alert(env):
    g, dog, rec, clock = env
    b = lease(g, key="lb")
    g.submit("s", "p1", "rb", [{"op": "release", "body": {"lease": b, "outcome": "nothing"}}])
    for i in range(4):
        iid = g.submit("h", "p1", f"i{i}", [{"op": "add_intent", "body": {
            "title": f"x{i}", "premises": [], "risk": "r0", "budget": R}}])["results"][0]["id"]
        lid = lease(g, "explore", iid, key=f"le{i}")
        g.submit("s", "p1", f"r{i}", [{"op": "release", "body": {"lease": lid, "outcome": "failed"}}])
    r = dog.tick()
    assert r.alerts and r.alerts[0]["alert"] == "backend_unhealthy" and r.alerts[0]["fail_rate"] > 0.5
    assert dog.tick().alerts == []                              # 同一窗口只告警一次


def test_watchdog_cannot_do_more_than_its_ops(env):
    """令牌只够它的四件事：不能写论断、不能领租约。"""
    g, dog, rec, clock = env
    out = g.submit("w", "p1", "x", [{"op": "add_fact", "body": {"title": "t", "summary": "", "claim_type":
                                                               "inference", "premises": [], "grounds": []}}])
    assert out["results"][0]["code"] == "forbidden_op"
    out = g.submit("w", "p1", "y", [{"op": "lease", "body": {"kind": "bootstrap", "holder": "wd", "reserve": R,
                                                             "ttl_s": 120}}])
    assert out["results"][0]["code"] == "forbidden_op"


def test_wall_clock_kills_live_tasks(env):
    g, dog, rec, clock = env
    lid = lease(g, ttl=7200)
    clock.t += 3600 * 1000
    r = dog.tick()
    assert r.closed == ["p1"] and r.killed == [(lid, "wall_s")] and r.expired == []
