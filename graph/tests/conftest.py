import hashlib

import pytest

from paoding_graph.envelope import GENESIS, seal
from paoding_graph.reducer import Config, Ok, apply, empty_state, result_id, validate

HUMAN = {"kind": "human", "id": "cz"}
EXECUTOR = {"kind": "executor", "id": "ex1"}
JUDGE = {"kind": "judge", "id": "jr1"}
ADAPTER = {"kind": "adapter", "id": "ad1"}


def explore(session="L1"):
    return {"kind": "adapter", "id": "ad1", "session": session, "role": "explore"}


def reason(session="R1"):
    return {"kind": "adapter", "id": "ad1", "session": session, "role": "reason"}


CFG = Config(judges={
    "replay": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.01},
    "exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0},
    "costly": {"version": "1", "grade": "decisive", "kind": "container", "max_cost": 2.0},
    "soft": {"version": "1", "grade": "consistent", "kind": "container", "max_cost": 0.0},
    "advice": {"version": "1", "grade": "advisory", "kind": "builtin", "max_cost": 0.0},
}, external_resources=frozenset({"remote"}))


class Kernel:
    """测试台：validate → 封装事件 → apply，seq 单调，哈希链按题。不做 IO。"""

    def __init__(self, cfg=CFG):
        self.cfg, self.state, self.events, self.heads, self.ts = cfg, empty_state(), [], {}, 1000

    def submit(self, actor, pid, kind, body):
        r = validate(self.state, actor, pid, kind, body, self.cfg)
        if not isinstance(r, Ok):
            return r.code
        self.ts += 1
        ev = seal(seq=len(self.events) + 1, problem_id=pid, ts=self.ts, actor=actor, kind=kind,
                  body=r.body, idem_key=f"k{len(self.events)}", prev_hash=self.heads.get(pid, GENESIS))
        self.heads[pid] = ev["hash"]
        self.events.append(ev)
        self.state = apply(self.state, ev)
        return result_id(ev) or "ok"

    # 便捷操作
    def art(self, pid, cls, content=b"x", actor=None):
        actor = actor or {"exec": EXECUTOR, "judge": JUDGE, "input": HUMAN, "authored": ADAPTER}[cls]
        body = {"hash": hashlib.sha256(content).hexdigest(), "size": len(content),
                "media_type": "text/plain", "class": cls}
        if cls in ("exec", "judge"):
            body["exec"] = {"sandbox_id": "s", "base": "b", "baseline_ref": "r", "tool": "shell",
                            "command": "true", "cwd": "/", "exit_code": 0, "touched": [],
                            "started_at": 1, "ended_at": 2, "truncated": False}
        return self.submit(actor, pid, "register_artifact", body)

    def open(self, pid="p1", scope_risks=("r0",), goal_judge="exact_match", resource="target"):
        st = self.art(pid, "input", b"statement " + pid.encode())
        return self.submit(HUMAN, pid, "open_problem", {
            "title": "t", "origin": {"statement_ref": st, "materials": []},
            "goal": {"statement": "g", "check": {"judge_id": goal_judge}, "max_attempts": 3, "accept": "judge"},
            "scope": [{"resource": resource, "pattern": "*", "actions": ["read"], "risk": r} for r in scope_risks],
            "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
            "env": {"base": "basic", "baseline_ref": "base@1"},
            "judges": ["replay", "exact_match", "soft", "costly", "advice"]})

    def obs(self, pid="p1", title="o", judge="replay", actor=None, grounds=None, expect=None, premises=()):
        g = grounds if grounds is not None else [self.art(pid, "exec", title.encode())]
        return self.submit(actor or explore(), pid, "add_fact", {
            "title": title, "summary": "", "claim_type": "observation",
            "check": {"judge_id": judge, "expect": expect or {"t": title}}, "premises": list(premises), "grounds": g})

    def verdict(self, pid, target, result, judge="replay", candidate=None):
        rid = self.submit(HUMAN, pid, "request_judge", {"target": target, "judge_id": judge,
                                                       **({"candidate": candidate} if candidate else {})})
        assert rid.startswith("j_"), rid
        ev = self.art(pid, "judge", f"{rid}{result}".encode())
        return self.submit(JUDGE, pid, "judge_verdict", {"request": rid, "result": result, "version": "1",
                                                         "evidence": [ev]})


@pytest.fixture
def k():
    return Kernel()
