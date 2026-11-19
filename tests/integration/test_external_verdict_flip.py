"""外部裁决一期的验收门：复现翻转表（docs/design/external-verdict/ §9）里落在内核这一期的各行，在全栈上翻过来。

同一个平台模拟（test_external_verdict_repro.Platform）。连接器运行器是二期的事，这里用一个**测试替身**判官函数
扮演它：按候选交付一次（幂等键是候选的哈希）、读回执、按映射表给裁决、pending 时带 recheck_at。替身只用于验证
内核与判官运行器的接线；二期的 connector 运行器上线后，本文件改用它，断言不变。

| 行 | 翻过来的是什么 |
| 1  | 已登记的平台：结构化开题被接受，goal.authority=external，快照带连接器摘要（入口一侧的翻转在三期） |
| 4  | 平台时限进 deadline，wall_s 守在单题硬顶以内：不裁、不拒 |
| 4b | wall_mode 两种取值：elapsed 照旧关（缺省没变），spend 不关 |
| 5  | 回执两次 pending 后 accepted：Goal 到 E3，终态 solved，authority=external；平台只收到一次提交 |
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "e2e"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive import call  # noqa: E402
from paoding_judgebox.contract import Outcome, kernel_judges  # noqa: E402
from stack import Stack, StackConfig  # noqa: E402
from test_external_verdict_repro import Platform  # noqa: E402

EXT_SPEC: dict[str, Any] = {
    "id": "ext_receipt",
    "version": "1",
    "kind": "deferred",
    "grade": "decisive",
    "authority": "external",
    "applies_to": ["goal"],
    "runner": {"type": "connector", "base": "builtin"},
    "params": {"connector": "mock-platform"},
    "timeout_s": 30,
    "max_cost": {"usd_milli": 0, "wall_s": 30},
    "auto": True,
    "flake": {"reruns": 0, "require": "all"},
}
VERDICT = {"accepted": "pass", "rejected": "fail", "pending": "pending"}  # 档案里的映射表


def stand_in(plat: Platform, poll_ms: int = 1000):
    """连接器判官的测试替身：交付候选（只一次）→ 读回执 → 映射。"""
    sids: dict[str, str] = {}

    def fn(ctx) -> Outcome:
        task = ctx.check["binding"]["task"]
        key = hashlib.sha256(ctx.candidate or b"").hexdigest()
        if key not in sids:
            sids[key] = plat.post(f"/api/tasks/{task}/submissions", {"answer": (ctx.candidate or b"").decode()})[
                "submission_id"
            ]
        rec = plat.get(f"/api/submissions/{sids[key]}")
        v = VERDICT.get(rec["status"])
        out = json.dumps(rec, ensure_ascii=False).encode()
        if v == "pending":
            return Outcome("inconclusive", "pending", out, recheck_at=ctx.now_ms + poll_ms)
        if v is None:
            return Outcome("inconclusive", "unsupported", out)
        return Outcome(v, "ok", out)

    return fn


@pytest.fixture
def plat():
    p = Platform()
    yield p
    p.close()


def _stack(tmp_path: Path, plat: Platform, wall_mode: str = "elapsed") -> tuple[Stack, str]:
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none"))
    s.registry["ext_receipt"] = EXT_SPEC
    conns = {"mock-platform": {"version": "1", "digest": "d" * 64, "doc": {}}}
    s.judges = kernel_judges(s.registry, conns)
    s.graph.cfg = dataclasses.replace(s.graph.cfg, judges=s.judges)
    s.judge.cfg.judges["ext_receipt"] = stand_in(plat)
    store = s.settings.store
    store.settings = {**store.settings, "budget": {"wall_mode": wall_mode, "life_s": 7 * 86400}}
    s.settings.apply()
    return s, s.http.serve()


def _blob(url: str, tok: str, data: bytes) -> dict[str, Any]:
    h = call(url, "/v1/blobs", token=tok, raw=data)["hash"]
    return {
        "op": "register_artifact",
        "body": {"hash": h, "size": len(data), "media_type": "text/plain; charset=utf-8", "class": "input"},
    }


def _open(s: Stack, url: str, plat: Platform, pid: str = "ext1") -> dict[str, Any]:
    """ "从平台导入"会生成的那份结构化开题（三期的入口照这个形状生成）。"""
    tok = s.human_token
    t = plat.get("/api/tasks")[0]
    brief = plat.get(f"/api/tasks/{t['id']}")  # 开题时领题：平台此刻开始计时
    notice = json.dumps(brief, ensure_ascii=False).encode()
    ops = [_blob(url, tok, brief["statement"].encode()), _blob(url, tok, notice)]
    opened_at = int(time.time() * 1000)  # 领题时刻（图服务用墙钟）
    ops.append(
        {
            "op": "open_problem",
            "body": {
                "title": t["title"],
                "origin": {"statement_ref": "$0", "materials": ["$1"]},
                "goal": {
                    "statement": "平台回执为通过",
                    "check": {
                        "judge_id": "ext_receipt",
                        "binding": {
                            "connector": "mock-platform",
                            "task": t["id"],
                            "max_submissions": t["max_submissions"],
                        },
                    },
                    "max_attempts": t["max_submissions"],
                    "accept": "judge",
                },
                "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
                "budget": {"usd_milli": 5000, "wall_s": 14_400, "verify_share": 0.2, "bootstrap_share": 0.3},
                "env": {"base": "basic", "baseline_ref": "basic@1"},
                "judges": ["ext_receipt"],
                "deadline": {
                    "source": "external",
                    "at": opened_at + t["time_limit_s"] * 1000,
                    "bound_by": "$1",
                },
            },
        }
    )
    return call(url, "/v1/problems", {"id": pid, "idem_key": f"open-{pid}", "ops": ops}, token=tok)


def test_row1_structured_open_is_accepted(tmp_path, plat):
    s, url = _stack(tmp_path, plat)
    try:
        res = _open(s, url, plat)
        assert res["ok"], res
        p = s.graph.state["problems"]["ext1"]
        assert p["goal"]["authority"] == "external" and p["profile"]["judge"] == "deferred"
        assert p["judge_snapshot"]["ext_receipt"]["connector"] == {
            "id": "mock-platform",
            "version": "1",
            "digest": "d" * 64,
        }
        assert p["scope"] == [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}]
    finally:
        s.http.close()


def test_row4_platform_limit_goes_to_deadline_not_budget(tmp_path, plat):
    s, url = _stack(tmp_path, plat)
    try:
        res = _open(s, url, plat)
        assert res["ok"], res  # 不裁、不拒
        p = s.graph.state["problems"]["ext1"]
        cap = s.graph.cfg.open_cap_wall_s
        assert p["budget"]["wall_s"] <= cap < Platform.TIME_LIMIT_S
        assert p["deadline"]["source"] == "external"
        assert p["deadline"]["at"] - p["opened_ts"] >= (Platform.TIME_LIMIT_S - 60) * 1000
    finally:
        s.http.close()


@pytest.mark.parametrize("mode,closed", [("elapsed", True), ("spend", False)])
def test_row4b_both_wall_modes(tmp_path, plat, mode, closed):
    s, url = _stack(tmp_path, plat, wall_mode=mode)
    try:
        assert _open(s, url, plat)["ok"]
        p = s.graph.state["problems"]["ext1"]
        assert p.get("wall_mode", "elapsed") == mode
        s.dog.clock = lambda: p["opened_ts"] + p["budget"]["wall_s"] * 1000  # 花费 0，开题墙钟走满 wall_s
        rep = s.dog.tick()
        assert ("ext1" in rep.closed) is closed
    finally:
        s.http.close()


def test_row5_pending_twice_then_accepted_solves(tmp_path, plat):
    s, url = _stack(tmp_path, plat)
    try:
        assert _open(s, url, plat)["ok"]
        tok = s.human_token
        cand = _blob(url, tok, plat.flag.encode())
        aid = s.graph.submit(tok, "ext1", "cand", [cand])["results"][0]["id"]
        rq = {"op": "request_judge", "body": {"target": "goal", "judge_id": "ext_receipt", "candidate": aid}}
        assert s.graph.submit(tok, "ext1", "rq", [rq])["ok"]
        t = {"now": 10**12}
        s.judge.clock = lambda: t["now"]
        results = []
        for _ in range(6):
            results += [d["reason"] for d in s.judge.tick("ext1")]
            if s.graph.state["problems"]["ext1"].get("closed"):
                break
            assert results == [] or results[-1] == "pending" or results[-1] == "ok"
            assert s.judge.tick("ext1") == []  # recheck_at 未到：不复判
            t["now"] += 2000
        assert results == ["pending", "pending", "ok"]
        p = s.graph.state["problems"]["ext1"]
        assert p["closed"] and p["terminal"] == "solved" and p["goal"]["authority"] == "external"
        assert sum(1 for line in plat.log if line.startswith("POST")) == 1  # 复判只读回执，不重交
    finally:
        s.http.close()
