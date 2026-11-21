"""司南派复核（地图 Q34，h2.sinan@2）：开了复核的开放道题，交付之后先派复核会话，再停下等人看；
复核的预留从验证份额里出；求解会话的余额预留让出验证份额；验证份额花完了就不复核。"""

import dataclasses

from paoding_adapter.contract import SessionRecord
from paoding_graph.contract import BlobStore, Config, GraphService, TokenRegistry
from paoding_sinan.contract import Sinan, SinanConfig

CFG = Config(judges={}, external_resources=frozenset(), review_open=True)


class OpenWorld:
    """真图服务 + 替身会话：solve 会话交付、verify 会话交回读数。"""

    def __init__(self, tmp_path, cfg=CFG, verify_cost=100):
        self.reg = TokenRegistry()
        for kind, ident in (("human", "cz"), ("sinan", "sn1")):
            self.reg.issue({"kind": kind, "id": ident}, f"tok-{kind}")
        self.svc = GraphService(tmp_path / "g.sqlite", cfg, self.reg)
        self.blobs = BlobStore(tmp_path / "blobs")
        self.sinan = Sinan(SinanConfig(token="tok-sinan"), self.svc, self.svc, self.blobs, self)
        self.ran: list[dict] = []
        self.n = 0
        self.verify_cost = verify_cost

    def sub(self, tok, pid, ops):
        self.n += 1
        out = self.svc.submit(tok, pid, f"w{self.n}", ops)
        assert out["ok"], out
        return out["results"]

    def open(self, pid="p1", usd_milli=5000):
        text = b"what is 6*7"
        self.sub(
            "tok-human",
            pid,
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": self.blobs.put(text),
                        "size": len(text),
                        "media_type": "text/plain",
                        "class": "input",
                    },
                },
                {
                    "op": "open_problem",
                    "body": {
                        "title": "t",
                        "origin": {"statement_ref": "$0", "materials": []},
                        "goal": {"statement": "g", "accept": "open"},
                        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
                        "budget": {"usd_milli": usd_milli, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
                        "env": {"base": "basic", "baseline_ref": "basic@1"},
                        "judges": [],
                    },
                },
            ],
        )

    def run(self, pid, lease_id, *, statement, kits=None, focus=None, sandbox_id=None):
        lease = self.svc.state["leases"][lease_id]
        kind = lease["kind"]
        tok = f"tok-s-{lease_id}"
        self.reg.issue({"kind": "adapter", "id": "ad1", "session": lease_id, "role": kind}, tok)
        self.ran.append({"kind": kind, "target": lease.get("target"), "reserve": lease["reserve"]})
        if kind == "solve":
            ans = {"hash": self.blobs.put(b"42"), "size": 2, "media_type": "text/plain", "class": "authored"}
            body = {
                "outcome": "answered",
                "answer": "$0",
                "claims": [{"text": "42"}],
                "self_check": [],
                "unverified": [],
            }
            self.sub(tok, pid, [{"op": "register_artifact", "body": ans}, {"op": "deliver", "body": body}])
            cost = 1000
        else:
            assert kind == "verify"
            body = {
                "delivery": lease["target"],
                "claims": [{"claim": 0, "verdict": "unclear", "note": "没有引用"}],
                "summary": "一条主张，没有依据可核",
            }
            self.sub(tok, pid, [{"op": "review", "body": body}])
            cost = self.verify_cost
        c = {"task_id": lease_id, "source": "proxy", "usd_milli": cost, "wall_s": 1, "price_table": "t"}
        self.sub(tok, pid, [{"op": "cost", "body": c}])
        self.sub(tok, pid, [{"op": "release", "body": {"lease": lease_id, "outcome": "done"}}])
        return SessionRecord(lease_id, "released", release={"outcome": "done"})


def test_a_delivery_is_reviewed_before_sinan_stops_for_the_human(tmp_path):
    w = OpenWorld(tmp_path)
    w.open()
    out = w.sinan.run("p1")
    assert out["stop"] == "needs_human"
    assert [r["kind"] for r in w.ran] == ["solve", "verify"]
    did = w.svc.state["problems"]["p1"]["deliveries"][0]["id"]
    assert w.ran[1]["target"] == did
    assert w.svc.state["problems"]["p1"]["reviews"][0]["delivery"] == did


def test_solve_leaves_the_verify_share_and_verify_draws_on_it(tmp_path):
    w = OpenWorld(tmp_path)
    w.open(usd_milli=5000)  # 验证份额 0.2 × 5000 = 1000
    w.sinan.run("p1")
    assert w.ran[0]["reserve"]["usd_milli"] == 4000  # 余额 5000 让出 1000
    assert w.ran[1]["reserve"]["usd_milli"] == 500  # 复核上限 500，份额里剩 1000
    b = w.svc.budget("p1")
    assert b["verify_spent"]["usd_milli"] == 100


def test_a_tiny_verify_share_caps_the_review_reserve(tmp_path):
    w = OpenWorld(tmp_path)
    w.open(usd_milli=1500)  # 份额 300
    w.sinan.run("p1")
    assert w.ran[1]["reserve"]["usd_milli"] == 300


def test_without_the_switch_nothing_is_reviewed(tmp_path):
    w = OpenWorld(tmp_path, cfg=dataclasses.replace(CFG, review_open=False))
    w.open()
    assert w.sinan.run("p1")["stop"] == "needs_human"
    assert [r["kind"] for r in w.ran] == ["solve"]
    assert w.ran[0]["reserve"]["usd_milli"] == 5000  # 没开复核：余额不让


def test_a_spent_verify_share_means_no_review(tmp_path):
    w = OpenWorld(tmp_path, verify_cost=1200)  # 追加 1000 之后份额 0.2 × 6000 = 1200，正好花完
    w.open()
    w.sinan.run("p1")
    w.sub(
        "tok-human",
        "p1",
        [
            {
                "op": "follow_up",
                "body": {"text": "再看看", "budget_add_usd_milli": 1000, "seen": {"seq": w.svc.state["seq"]}},
            }
        ],
    )
    out = w.sinan.run("p1")
    assert out["stop"] == "needs_human"
    assert [r["kind"] for r in w.ran] == ["solve", "verify", "solve"]  # 第二次交付时份额已花完，不复核
