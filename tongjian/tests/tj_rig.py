"""通鉴测试台：真图服务 + 手写的判官（不起容器）+ 通鉴服务 + 召回运行器。

一道"A 题"在薄路径上解出：Bootstrap 写一条带对照的观察（spec、对照输入），判官裁决通过（对照不通过），
同一会话交候选，Goal 通过即关题。于是这条观察在解题链上、是 E3、带对照：封存后投影出一条环境事实。
"""

from __future__ import annotations

import hashlib
import itertools

from paoding_graph.contract import BlobStore, Config, GraphService, TokenRegistry, views
from paoding_tongjian.contract import RecallConfig, RecallRunner, Tongjian, TongjianConfig, with_recall

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
R = {"usd_milli": 100, "wall_s": 60}
SPEC = b"test -e /workspace/inputs/1 && exit 1; echo ready\n"
CONTROL = b"x"
TITLE = "执行环境可用"


class Rig:
    def __init__(self, tmp_path, case_seal: bool = True):
        self.tmp = tmp_path
        self.reg = TokenRegistry()
        for kind, ident in (("human", "cz"), ("sinan", "sn1"), ("executor", "ex1"), ("judge", "jr1")):
            self.reg.issue({"kind": kind, "id": ident}, f"tok-{kind}")
        self.svc = GraphService(tmp_path / "g.sqlite", CFG, self.reg)
        self.blobs = BlobStore(tmp_path / "blobs")
        self.tj = Tongjian(tmp_path / "tj.sqlite", self.svc, TongjianConfig(case_seal=case_seal, model_epoch="m1"))
        self.recaller = RecallRunner(RecallConfig(token="tok-sinan"), self.svc, self.svc, self.reg)
        self.n = itertools.count()

    # ---------- 提交 ----------

    def sub(self, tok, pid, ops):
        return self.svc.submit(tok, pid, f"w{next(self.n)}", ops)

    def one(self, tok, pid, op, body):
        out = self.sub(tok, pid, [{"op": op, "body": body}])
        assert out["ok"], out
        return out["results"][0].get("id")

    def art(self, tok, pid, data, cls, **extra):
        body = {"hash": self.blobs.put(data), "size": len(data), "media_type": "text/plain", "class": cls, **extra}
        return self.one(tok, pid, "register_artifact", body)

    def session(self, lid, role):
        tok = f"tok-s-{lid}"
        self.reg.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": role}, tok)
        return tok

    def lease(self, pid, kind, target=None):
        body = {"kind": kind, "holder": "sn1", "reserve": R, "ttl_s": 120, **({"target": target} if target else {})}
        return self.one("tok-sinan", pid, "lease", body)

    def release(self, tok, pid, lid, outcome="done"):
        self.one(tok, pid, "release", {"lease": lid, "outcome": outcome})

    def verdict(self, pid, rid, result, controlled=False):
        ev = self.art("tok-judge", pid, f"v {rid} {result}".encode(), "judge", exec=PROV)
        end = {"control_end": "fail" if result == "pass" else "not_run"} if controlled else {}
        body = {"request": rid, "result": result, "version": "1", "evidence": [ev], **end}
        self.one("tok-judge", pid, "judge_verdict", body)

    # ---------- 开题 ----------

    def ops(self, pid, title="找到取值并提交"):
        text = f"{title}（{pid}）".encode()
        return [
            {
                "op": "register_artifact",
                "body": {"hash": self.blobs.put(text), "size": len(text), "media_type": "text/plain", "class": "input"},
            },
            {
                "op": "open_problem",
                "body": {
                    "title": title,
                    "origin": {"statement_ref": "$0", "materials": []},
                    "goal": {
                        "statement": "g",
                        "check": {"judge_id": "exact_match", "expect": {"sha256": hashlib.sha256(b"42").hexdigest()}},
                        "max_attempts": 3,
                        "accept": "judge",
                    },
                    "scope": [{"resource": "net", "pattern": "target-a:8080", "actions": ["connect"], "risk": "r0"}],
                    "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
                    "env": {"base": "basic", "baseline_ref": "basic@1"},
                    "judges": ["exact_match", "replay"],
                },
            },
        ]

    def open(self, pid, mode="off", drop=(), title="找到取值并提交"):
        ops = self.ops(pid, title)
        body = ops[-1]["body"]
        problem = {**body, "profile": views.profile_preview(body, CFG)["profile"]}
        m = self.tj.match(problem)
        out = self.sub("tok-human", pid, with_recall(ops, m, mode, drop))
        assert out["ok"], out
        return m

    # ---------- 解题：薄路径 ----------

    def solve_thin(self, pid, observe=True, premises=()):
        """Bootstrap 写观察（带对照）、请求判定、交候选；判官依次放行。返回观察的 id。"""
        lid = self.lease(pid, "bootstrap")
        s = self.session(lid, "bootstrap")
        fid = None
        if observe:
            ex = self.art("tok-executor", pid, f"out {lid}".encode(), "exec", exec=PROV)
            spec = self.art(s, pid, SPEC, "authored")
            ctl = self.art(s, pid, CONTROL, "authored")
            check = {"judge_id": "replay", "spec_ref": spec, "expect": {"stdout_contains": "ready"}}
            fid = self.one(
                s,
                pid,
                "add_fact",
                {
                    "title": TITLE,
                    "summary": "",
                    "claim_type": "observation",
                    "check": {**check, "control": {"inputs": [ctl]}},
                    "premises": list(premises),
                    "grounds": [ex],
                },
            )
            rid = self.one(s, pid, "request_judge", {"target": fid, "judge_id": "replay"})
            self.verdict(pid, rid, "pass", controlled=True)
        cand = self.art(s, pid, b"42", "authored")
        rid = self.one(s, pid, "request_judge", {"target": "goal", "judge_id": "exact_match", "candidate": cand})
        self.release(s, pid, lid)
        self.verdict(pid, rid, "pass")
        assert self.svc.state["problems"][pid]["closed"]
        return fid

    def recalled(self, pid):
        """本题的召回节点（标题带"[忆] "）与它们的判定请求。"""
        st = self.svc.state
        facts = [f for f, x in st["facts"].items() if x["problem_id"] == pid and x["title"].startswith("[忆] ")]
        reqs = {r["target"]: rid for rid, r in st["requests"].items() if r["problem_id"] == pid}
        return [(f, reqs.get(f)) for f in facts]

    def work(self, pid):
        return [w["kind"] for w in self.svc.work(pid)]
