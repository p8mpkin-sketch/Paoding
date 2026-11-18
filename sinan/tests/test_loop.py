"""司南最小循环（§4.1，D11）。会话是进程内替身：按租约种类往图里写东西，再释放租约。

覆盖：/work 驱动的先后（bootstrap → reason → explore）、估值排序及其开关、判定未决时等待及其开关、
预留的取值、被拒后的停机、I8（司南只提交 lease）、单进程下经 between 驱动判官直到关题。
并发（审计 P1-3）：不同 Intent 的 Explore 并行、同一 Intent 互斥、Reason 每题互斥、并发上限、max_sessions=1 退回串行。
"""

import ast
import hashlib
import threading
import time
from pathlib import Path

import pytest

from paoding_adapter.contract import SessionRecord
from paoding_graph.contract import BlobStore, Config, GraphService, TokenRegistry
from paoding_sinan.contract import Sinan, SinanConfig

CFG = Config(
    judges={
        "replay": {"version": "1", "grade": "decisive", "kind": "programmatic", "max_cost": 0.01},
        "exact_match": {"version": "1", "grade": "decisive", "kind": "deterministic", "max_cost": 0.0},
    },
    external_resources=frozenset(),
)
PROV = {
    "sandbox_id": "s",
    "base": "basic",
    "baseline_ref": "basic@1",
    "tool": "shell",
    "command": "probe",
    "cwd": "/",
    "exit_code": 0,
    "touched": [],
    "started_at": 1,
    "ended_at": 2,
    "truncated": False,
}


class World:
    """真图服务 + 替身会话 + 手写的判官。"""

    def __init__(self, tmp_path, **cfg):
        self.reg = TokenRegistry()
        for kind, ident in (("human", "cz"), ("sinan", "sn1"), ("executor", "ex1"), ("judge", "jr1")):
            self.reg.issue({"kind": kind, "id": ident}, f"tok-{kind}")
        self.svc = GraphService(tmp_path / "g.sqlite", CFG, self.reg)
        self.blobs = BlobStore(tmp_path / "blobs")
        self.sinan = Sinan(SinanConfig(token="tok-sinan", **cfg), self.svc, self.svc, self.blobs, self)
        self.ran, self.n = [], 0
        self.gains = (0.2, 0.9)
        self.intent_budget = {"usd_milli": 100, "wall_s": 60}
        self.candidate = b"42"
        self.lock = threading.Lock()
        self.gate = None  # 给了就在 explore 会话里等它：测试用来让会话停在半路
        self.inside = []  # 当前在会话里的 (kind, target)
        self.peak = 0  # 同时在途会话数的最大值

    def sub(self, tok, pid, ops):
        with self.lock:
            self.n += 1
            n = self.n
        return self.svc.submit(tok, pid, f"w{n}", ops)

    def one(self, tok, pid, op, body):
        out = self.sub(tok, pid, [{"op": op, "body": body}])
        assert out["ok"], out
        return out["results"][0].get("id")

    def art(self, tok, pid, data, cls, **extra):
        return self.one(
            tok,
            pid,
            "register_artifact",
            {"hash": self.blobs.put(data), "size": len(data), "media_type": "text/plain", "class": cls, **extra},
        )

    def open(self, pid="p1", usd_milli=5000, text="找到取值并提交"):
        out = self.sub(
            "tok-human",
            pid,
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": self.blobs.put(text.encode()),
                        "size": len(text.encode()),
                        "media_type": "text/plain",
                        "class": "input",
                    },
                },
                {
                    "op": "open_problem",
                    "body": {
                        "title": "t",
                        "origin": {"statement_ref": "$0", "materials": []},
                        "goal": {
                            "statement": "g",
                            "check": {
                                "judge_id": "exact_match",
                                "expect": {"sha256": hashlib.sha256(b"42").hexdigest()},
                            },
                            "max_attempts": 3,
                            "accept": "judge",
                        },
                        "scope": [
                            {"resource": "net", "pattern": "target-a:8080", "actions": ["connect"], "risk": "r0"}
                        ],
                        "budget": {"usd_milli": usd_milli, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
                        "env": {"base": "basic", "baseline_ref": "basic@1"},
                        "judges": ["exact_match", "replay"],
                    },
                },
            ],
        )
        assert out["ok"], out

    # ---------- SessionPort 的替身 ----------

    def run(self, pid, lease_id, *, statement, kits=None, focus=None, sandbox_id=None):
        lease = self.svc.state["leases"][lease_id]
        key = (lease["kind"], lease.get("target"))
        with self.lock:
            assert key not in self.inside, f"同一目标上有两个会话：{key}"
            self.inside.append(key)
            self.peak = max(self.peak, len(self.inside))
        try:
            return self._session(pid, lease_id, lease, statement)
        finally:
            with self.lock:
                self.inside.remove(key)

    def _session(self, pid, lease_id, lease, statement):
        kind = lease["kind"]
        tok = f"tok-s-{lease_id}"
        self.reg.issue({"kind": "adapter", "id": "ad1", "session": lease_id, "role": kind}, tok)
        with self.lock:
            self.ran.append(
                {"kind": kind, "target": lease.get("target"), "statement": statement, "reserve": lease["reserve"]}
            )
        if kind == "bootstrap":
            ex = self.art("tok-executor", pid, f"out {lease_id}".encode(), "exec", exec=PROV)
            fid = self.one(
                tok,
                pid,
                "add_fact",
                {
                    "title": "端口开放",
                    "summary": "",
                    "claim_type": "observation",
                    "check": {"judge_id": "replay", "expect": {"exit_code": 0}},
                    "premises": [],
                    "grounds": [ex],
                },
            )
            self.one(tok, pid, "request_judge", {"target": fid, "judge_id": "replay"})
        elif kind == "reason":
            for n, gain in enumerate(self.gains):
                self.one(
                    tok,
                    pid,
                    "add_intent",
                    {
                        "title": f"路线 {n} {lease_id}",
                        "summary": "",
                        "premises": [],
                        "risk": "r0",
                        "budget": self.intent_budget,
                        "expected_gain": gain,
                    },
                )
        else:
            if self.gate is not None:
                self.gate.wait(10)  # Barrier：凑齐人数才放行；Event：等测试放行
            # 候选次数用满、或并行的另一个会话已把题解掉之后内核会拒，会话照常收尾
            self.sub(
                tok,
                pid,
                [
                    {
                        "op": "register_artifact",
                        "body": {
                            "hash": self.blobs.put(self.candidate),
                            "class": "authored",
                            "size": len(self.candidate),
                            "media_type": "text/plain",
                        },
                    },
                    {"op": "request_judge", "body": {"target": "goal", "judge_id": "exact_match", "candidate": "$0"}},
                ],
            )
        self.sub("tok-sinan", pid, [{"op": "release", "body": {"lease": lease_id, "outcome": "done"}}])
        return SessionRecord(lease_id, "released", release={"outcome": "done", "ok": True})

    # ---------- 手写的判官：候选等于 42 即通过 ----------

    def judge(self, pid="p1"):
        for w in self.svc.work(pid):
            st = self.svc.state
            if w["kind"] != "judge" or st["problems"][pid].get("closed"):
                continue
            req = st["requests"][w["target"]]
            lid = self.one(
                "tok-judge",
                pid,
                "lease",
                {
                    "kind": "judge",
                    "target": req["id"],
                    "holder": "jr1",
                    "reserve": {"usd_milli": 1, "wall_s": 10},
                    "ttl_s": 60,
                },
            )
            ok = req["candidate"] is None or self.blobs.get(st["artifacts"][req["candidate"]]["hash"]) == b"42"
            ev = self.art("tok-judge", pid, f"v {lid}".encode(), "judge", exec=PROV)
            self.one(
                "tok-judge",
                pid,
                "judge_verdict",
                {"request": req["id"], "result": "pass" if ok else "fail", "version": "1", "evidence": [ev]},
            )
            self.one("tok-judge", pid, "release", {"lease": lid, "outcome": "done"})


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def kinds(w):
    return [r["kind"] for r in w.ran]


def test_first_step_is_bootstrap_with_the_statement(w):
    w.open(text="题面：取回 /value")
    out = w.sinan.step("p1")
    assert out["did"] == {"kind": "bootstrap"} and out["outcome"] == "done" and out["status"] == "released"
    assert w.ran[0]["statement"] == "题面：取回 /value"


def test_bootstrap_reserve_is_thin(w):
    w.open(usd_milli=1000)  # bootstrap_share 0.3 → 至多 300
    w.sinan.step("p1")
    assert w.ran[0]["reserve"]["usd_milli"] == 300


def test_thick_bootstrap_when_switch_is_off(tmp_path):
    w = World(
        tmp_path,
        thin_bootstrap=False,
        reserve={"bootstrap": {"usd_milli": 200, "wall_s": 60}, "reason": {"usd_milli": 10, "wall_s": 60}},
    )
    w.open(usd_milli=1000)
    w.sinan.step("p1")
    assert w.ran[0]["reserve"]["usd_milli"] == 200


def test_waits_while_a_judgment_is_pending(w):
    w.open()
    w.sinan.step("p1")
    assert w.sinan.step("p1") == {"wait": "judge"} and kinds(w) == ["bootstrap"]
    w.judge()
    assert w.sinan.step("p1")["did"] == {"kind": "reason"}


def test_waits_while_a_judge_holds_the_request(w):
    """判官已领走请求（不在 /work 里了）而裁决未落盘：仍算判定未决，不开 Reason。"""
    w.open()
    w.sinan.step("p1")
    [item] = [x for x in w.svc.work("p1") if x["kind"] == "judge"]
    lid = w.one(
        "tok-judge",
        "p1",
        "lease",
        {
            "kind": "judge",
            "target": item["target"],
            "holder": "jr1",
            "reserve": {"usd_milli": 1, "wall_s": 10},
            "ttl_s": 60,
        },
    )
    assert not [x for x in w.svc.work("p1") if x["kind"] == "judge"]
    assert w.sinan.step("p1") == {"wait": "judge"} and kinds(w) == ["bootstrap"]
    w.one("tok-judge", "p1", "release", {"lease": lid, "outcome": "failed"})
    w.judge()
    assert w.sinan.step("p1")["did"] == {"kind": "reason"}


def test_does_not_wait_when_switch_is_off(tmp_path):
    w = World(tmp_path, wait_for_judges=False)
    w.open()
    w.sinan.step("p1")
    assert w.sinan.step("p1")["did"] == {"kind": "reason"}


def test_explores_highest_gain_first(w):
    w.open()
    w.sinan.step("p1")
    w.judge()
    w.sinan.step("p1")
    hi = next(i for i in w.svc.state["intents"].values() if i["expected_gain"] == 0.9)
    out = w.sinan.step("p1")
    assert out["did"] == {"kind": "explore", "target": hi["id"]}


def test_work_order_when_gain_ordering_is_off(tmp_path):
    w = World(tmp_path, order_by_gain=False)
    w.open()
    w.sinan.step("p1")
    w.judge()
    w.sinan.step("p1")
    first = next(x for x in w.svc.work("p1") if x["kind"] == "explore")
    assert w.sinan.step("p1")["did"] == first
    assert w.svc.state["intents"][first["target"]]["expected_gain"] == 0.2


def test_explore_reserve_follows_the_intent_budget_up_to_a_cap(w):
    w.intent_budget = {"usd_milli": 5000, "wall_s": 30}
    w.open(usd_milli=20000)
    w.sinan.step("p1")
    w.judge()
    w.sinan.step("p1")
    w.sinan.step("p1")
    assert w.ran[-1]["kind"] == "explore" and w.ran[-1]["reserve"] == {"usd_milli": 1000, "wall_s": 30}


def test_run_drives_to_solved_with_a_judge_between_steps(w):
    w.open()
    out = w.sinan.run("p1", between=w.judge)
    assert out["stop"] == "closed" and kinds(w)[:3] == ["bootstrap", "reason", "explore"]
    assert len(kinds(w)) in (3, 4)  # 两条路线可以并行：第二个 Explore 赶得上就也开
    p = w.svc.state["problems"]["p1"]
    assert p["closed"] and p["terminal"] == "solved"
    w.sinan.collect(None)
    assert sorted(s["did"]["kind"] for s in w.sinan.history) == sorted(kinds(w))


def test_serial_when_max_sessions_is_one(tmp_path):
    w = World(tmp_path, max_sessions=1)
    w.open()
    out = w.sinan.run("p1", between=w.judge)
    assert out["stop"] == "closed" and kinds(w) == ["bootstrap", "reason", "explore"] and w.peak == 1
    assert [s["did"]["kind"] for s in out["steps"]] == kinds(w)


def test_run_without_a_judge_hands_back(w):
    w.open()
    out = w.sinan.run("p1")
    assert out["stop"] == "waiting_judge" and kinds(w) == ["bootstrap"]


def test_wrong_candidates_lead_back_to_reason(w):
    w.candidate = b"41"
    w.gains = (0.5,)
    w.open()
    out = w.sinan.run("p1", between=w.judge, max_steps=14)
    assert out["stop"] == "max_steps"  # 循环有界：步数上限由调用方给
    goal_reqs = [r for r in w.svc.state["requests"].values() if r["target"] == "goal"]
    assert len(goal_reqs) == 3  # 候选次数上限由内核守住
    assert not w.svc.state["problems"]["p1"].get("closed")
    assert kinds(w)[:4] == ["bootstrap", "reason", "explore", "reason"]  # Goal 判定失败触发下一轮 Reason


def test_stops_when_the_lease_is_refused(tmp_path):
    w = World(
        tmp_path, reserve={"bootstrap": {"usd_milli": 10, "wall_s": 60}, "reason": {"usd_milli": 999999, "wall_s": 60}}
    )
    w.open()
    w.sinan.step("p1")
    w.judge()
    out = w.sinan.step("p1")
    assert out["stop"] == "over_budget" and out["item"] == {"kind": "reason"} and kinds(w) == ["bootstrap"]


def test_closed_and_unknown_problems(w):
    assert w.sinan.step("nope") == {"stop": "unknown_problem"}
    w.open()
    w.sinan.run("p1", between=w.judge)
    n = w.svc.state["seq"]
    assert w.sinan.step("p1") == {"stop": "closed"} and w.svc.state["seq"] == n


def test_pick_is_read_only(w):
    w.open()
    n = w.svc.state["seq"]
    assert w.sinan.pick("p1") == {"do": {"kind": "bootstrap"}} and w.svc.state["seq"] == n


def test_sinan_only_ever_submits_leases(w):  # I8：调度不写等级相关的东西
    w.open()
    w.sinan.run("p1", between=w.judge)
    mine = [e for e in w.svc.events("p1", 0, 1000) if e["actor"]["kind"] == "sinan"]
    by_loop = [e for e in mine if e["kind"] != "release"]  # release 是替身会话借司南令牌提交的
    assert by_loop and {e["kind"] for e in by_loop} == {"lease"}


def test_two_problems_do_not_interfere(w):
    w.open("p1")
    w.open("p2")
    w.sinan.step("p1")
    assert w.sinan.pick("p2") == {"do": {"kind": "bootstrap"}}
    assert w.sinan.run("p2", between=lambda: w.judge("p2"))["stop"] == "closed"
    assert not w.svc.state["problems"]["p1"].get("closed")


def test_loop_is_deterministic_code():
    """司南不调用模型、不读时钟、不起进程：循环里只有读 /work 与提交 lease。"""
    src = Path(__file__).resolve().parents[1] / "src/paoding_sinan/loop.py"
    banned = {"time", "datetime", "random", "subprocess", "socket", "urllib", "http", "requests", "anthropic", "openai"}
    for node in ast.walk(ast.parse(src.read_text())):
        mods = (
            [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module]
            if isinstance(node, ast.ImportFrom) and node.level == 0
            else []
        )
        for m in mods:
            assert m.split(".")[0] not in banned, m


# ---------- 并发（审计 P1-3） ----------


def to_explore(w, pid="p1"):
    """走到两条路线都待探索：bootstrap → 判定 → reason（写下两个 Intent）。"""
    w.open(pid)
    w.sinan.step(pid)
    w.judge(pid)
    w.sinan.step(pid)
    return sorted(i["id"] for i in w.svc.state["intents"].values() if i["problem_id"] == pid)


def active(w, kind):
    return [l for l in w.svc.state["leases"].values() if l["active"] and l["kind"] == kind]


def test_two_explores_on_different_intents_run_in_parallel(w):
    """两个会话都得进到会话里才凑得齐 Barrier；串行的话第一个会在门口等到超时。"""
    intents = to_explore(w)
    w.gate = threading.Barrier(2)
    a, b = w.sinan.dispatch("p1"), w.sinan.dispatch("p1")
    assert {a["started"]["target"], b["started"]["target"]} == set(intents) and a["lease"] != b["lease"]
    done = []
    while len(done) < 2:
        done += w.sinan.collect(5)
    assert not w.gate.broken and w.peak == 2
    assert {d["status"] for d in done} == {"released"} and {d["did"]["target"] for d in done} == set(intents)
    evs = [
        e
        for e in w.svc.events("p1", 0, 1000)
        if e["kind"] in ("lease", "release") and e["body"].get("lease", f"l_{e['seq']}") in (a["lease"], b["lease"])
    ]
    assert [e["kind"] for e in evs] == ["lease", "lease", "release", "release"]  # 两个租约同时在途


def test_same_intent_never_gets_two_sessions(w):
    intents = to_explore(w)
    w.gate = threading.Event()
    assert "started" in w.sinan.dispatch("p1") and "started" in w.sinan.dispatch("p1")
    # 两个 Intent 都在途：没有第三项可开；内核也拒绝同一目标上的第二个租约
    assert w.sinan.dispatch("p1") == {"wait": "in_flight"}
    out = w.sub(
        "tok-sinan",
        "p1",
        [
            {
                "op": "lease",
                "body": {
                    "kind": "explore",
                    "target": intents[0],
                    "holder": "sn1",
                    "reserve": {"usd_milli": 1, "wall_s": 1},
                    "ttl_s": 60,
                },
            }
        ],
    )
    assert not out["ok"] and out["results"][0]["code"] == "conflict_leased"
    assert sorted(l["target"] for l in active(w, "explore")) == intents
    w.gate.set()
    while w.sinan.in_flight():
        w.sinan.collect(5)
    assert sorted(r["target"] for r in w.ran if r["kind"] == "explore") == intents  # 每个 Intent 恰好一个会话


def test_finished_but_uncollected_session_still_blocks_its_intent(w):
    """会话已释放租约、线程还没收回时，这个 Intent 不再开第二个会话（司南自己的在途表）。"""
    w.candidate = b"41"  # 判定失败 → Intent 回到 open，/work 会再给出它
    w.gains = (0.5,)
    [iid] = to_explore(w)
    assert w.sinan.dispatch("p1")["started"] == {"kind": "explore", "target": iid}
    deadline = time.monotonic() + 5
    while active(w, "explore") and time.monotonic() < deadline:
        time.sleep(0.01)
    w.judge()
    assert w.sinan.in_flight("p1")  # 还没 collect
    r = w.sinan.dispatch("p1")
    assert r.get("started", {}).get("target") != iid


def test_reason_is_exclusive_per_problem_and_holds_back_new_explores(w):
    intents = to_explore(w)
    w.gate = threading.Event()
    a = w.sinan.dispatch("p1")  # 一个 Explore 在途
    w.one("tok-human", "p1", "hint", {"text": "换个角度"})  # Hint 触发下一轮 Reason
    assert {"kind": "reason"} in w.svc.work("p1")
    hold = threading.Event()
    real = w._session

    def slow(pid, lease_id, lease, statement):
        if lease["kind"] == "reason":
            hold.wait(10)
        return real(pid, lease_id, lease, statement)

    w._session = slow
    r = w.sinan.dispatch("p1")
    assert r["started"] == {"kind": "reason"}  # Reason 先于另一个待探索的 Intent
    assert w.sinan.dispatch("p1") == {"wait": "reason"}  # Reason 在途：不开第二个 Reason，也不开新 Explore
    assert len(active(w, "reason")) == 1 and len(active(w, "explore")) == 1
    w.one("tok-human", "p1", "hint", {"text": "再换一个"})
    assert {"kind": "reason"} not in w.svc.work("p1")  # 内核同样不再给出 Reason
    out = w.sub(
        "tok-sinan",
        "p1",
        [
            {
                "op": "lease",
                "body": {"kind": "reason", "holder": "sn1", "reserve": {"usd_milli": 1, "wall_s": 1}, "ttl_s": 60},
            }
        ],
    )
    assert not out["ok"] and out["results"][0]["code"] == "conflict_leased"
    hold.set()
    w.gate.set()
    while w.sinan.in_flight():
        w.sinan.collect(5)
    assert a["started"]["target"] in intents and kinds(w).count("reason") == 2


def test_capacity_caps_sessions_in_flight(tmp_path):
    w = World(tmp_path, max_sessions=2)
    w.gains = (0.1, 0.2, 0.3)
    w.intent_budget = {"usd_milli": 10, "wall_s": 60}
    to_explore(w)
    w.gate = threading.Event()
    assert "started" in w.sinan.dispatch("p1") and "started" in w.sinan.dispatch("p1")
    assert w.sinan.dispatch("p1") == {"wait": "capacity"} and len(active(w, "explore")) == 2
    w.gate.set()
    assert w.sinan.collect(5)
    while w.sinan.in_flight():
        w.sinan.collect(5)
    assert w.peak == 2


def test_budget_refusal_waits_while_others_hold_reserves(tmp_path):
    """别的会话占着预留时，新租约被 over_budget 拒是“等”，不是停机；没有在途会话时才停。"""
    w = World(
        tmp_path, reserve={"bootstrap": {"usd_milli": 10, "wall_s": 60}, "reason": {"usd_milli": 10, "wall_s": 60}}
    )
    w.intent_budget = {"usd_milli": 600, "wall_s": 60}
    w.open(usd_milli=1000)
    w.sinan.step("p1")
    w.judge()
    w.sinan.step("p1")
    w.gate = threading.Event()
    assert "started" in w.sinan.dispatch("p1")
    r = w.sinan.dispatch("p1")
    assert r["wait"] == "over_budget" and r["item"]["kind"] == "explore"
    w.gate.set()
    while w.sinan.in_flight():
        w.sinan.collect(5)


def test_crashed_session_is_reported_not_raised(w):
    w.open()

    def boom(pid, lease_id, lease, statement):
        raise RuntimeError("会话线程炸了")

    w._session = boom
    out = w.sinan.step("p1")
    assert out["status"] == "crashed" and out["outcome"] is None and "会话线程炸了" in out["detail"]
    assert w.sinan.in_flight() == []


def test_lease_idem_keys_differ_at_the_same_seq(w):
    """同一 seq 上接连领两个租约：幂等键带着项本身，后一个不会被当成前一个的重放。"""
    to_explore(w)
    w.gate = threading.Event()
    a, b = w.sinan.dispatch("p1"), w.sinan.dispatch("p1")
    assert a["lease"] != b["lease"]
    w.gate.set()
    while w.sinan.in_flight():
        w.sinan.collect(5)
