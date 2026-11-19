"""开放道第一步的端到端（docs/design/open-lane/ §11 第一步）：今天被拒的那句话，从开题入口走到一份带证据的答案。

一句话 → 起草服务（POST /v1/drafts 的同一份实现，启发式起草）→ 人的令牌提交批次 → 司南派 solve →
会话运行器起假 CLI（真代理、真工具端点、真图服务）→ deliver → 人看、关题。执行层是进程内替身。

另两条是裁决附加条件 3 点名的用例：正文带凭据（零出站、审批不泄漏），与以“受阻”诚实收尾（部分交付不作假）。
验收十条由 cz 给出后另补（不取自本机题库）。
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "adapter" / "tests"))

from adapter_rig import FakeExec, Rig, graph, upstream  # noqa: E402,F401  fixture

from paoding_graph import views  # noqa: E402
from paoding_graph import work as wk  # noqa: E402
from paoding_graph.cards import seen as seen_card  # noqa: E402
from paoding_pd import render  # noqa: E402
from paoding_qicao.contract import Intake, KaitiService, Settings, heuristic_drafter, placeholder_priors  # noqa: E402
from paoding_sinan.contract import Sinan, SinanConfig  # noqa: E402

EXEC, DELIVER, ACCESS = "mcp__paoding__exec", "mcp__paoding__deliver", "mcp__paoding__request_access"
REFUSED = "帮我调研一下主流的智能体框架，写一份对比。"  # 开放道之前：no_criterion，拒
TOKEN = "ghp_Q7wErTy9UiOp1234aSdF"


class Sandboxes(FakeExec):
    """FakeExec 加上起沙箱：记下每个沙箱编进去的出站白名单（开题零出站就是空的）。"""

    def __init__(self, graph, blobs):
        super().__init__(graph, blobs)
        self.launched: list[dict] = []

    def launch(self, spec, lease_id, mount_workspace=True):
        sid = f"sb-{lease_id}"
        self.launched.append({"sid": sid, "lease": lease_id, "egress": tuple(spec.egress_allow)})
        return sid


def stand_up(tmp_path, graph, upstream, steps):  # noqa: F811
    rig = Rig(tmp_path, graph, upstream)
    rig.executor = rig.runner.executor = Sandboxes(graph, rig.blobs)
    rig.cfg.grants_runtime = lambda: True
    graph.cfg = dataclasses.replace(graph.cfg, grants_runtime=True)
    p = tmp_path / "solve.json"
    p.write_text(json.dumps({"steps": steps, "resume_steps": []}))
    rig.cfg.env_for = lambda lease: {"PD_FAKE_SCRIPT": str(p) if lease["kind"] == "solve" else ""}
    return rig


def kaiti(rig, text):
    """网页 /new 的同一条路：起草服务算批次，人的令牌存题面、提交。开放道不出确认卡：拿到批次直接提交。"""
    settings = Settings.from_doc({"settings": {"caps": {}, "risk": [], "grants": {"runtime": True}}})
    svc = KaitiService(Intake.load(), lambda: settings, placeholder_priors(), heuristic_drafter, "heuristic")
    out = svc.draft_view({"text": text})
    assert out["lane"] == "open", out["notes"]
    for b in out["blobs"]:
        assert rig.blobs.put(b["text"].encode()) == b["hash"]
    res = rig.graph.submit("tok-human", out["pid"], f"k-{out['pid']}", out["ops"])
    assert res["ok"], res
    return out


def close(g, pid, **body):
    out = g.submit("tok-human", pid, f"close-{pid}", [{"op": "close_problem", "body": body}])
    assert out["ok"], out


def test_refused_prompt_now_runs_to_an_answer_with_evidence(tmp_path, graph, upstream):  # noqa: F811
    rig = stand_up(
        tmp_path,
        graph,
        upstream,
        [
            {"tool": "Write", "input": {"file_path": "NOTES.md", "content": "计划：列框架、跑示例、写对比\n"}},
            {"tool": EXEC, "input": {"cmd": "pip index versions langgraph"}},
            {"tool": "Write", "input": {"file_path": "report.md", "content": "# 对比\n……\n"}},
            {
                "tool": DELIVER,
                "input": {
                    "outcome": "answered",
                    "answer_path": "report.md",
                    "claims": [
                        {"text": "langgraph 有可装的发行版", "refs": ["$r1.artifact"]},
                        {"text": "社区活跃度相近（印象，没查）"},
                    ],
                    "self_check": [{"what": "逐句对照原话：调研、对比都有", "result": "pass"}],
                    "unverified": ["活跃度没有数据"],
                },
            },
        ],
    )
    try:
        out = kaiti(rig, REFUSED)
        pid = out["pid"]
        p = graph.state["problems"][pid]
        assert p["goal"] == {"statement": REFUSED, "accept": "open", "authority": "self"}
        sinan = Sinan(SinanConfig(token="tok-sinan"), graph, graph, rig.blobs, rig.runner)
        r = sinan.run(pid)
        assert r["stop"] == "needs_human" and r["items"] == [{"kind": "human", "target": pid, "why": "delivered"}]
        assert [s["did"]["kind"] for s in r["steps"]] == ["solve"] and r["steps"][0]["outcome"] == "done"
        # 开题零出站：沙箱里没有任何出站规则
        assert [b["egress"] for b in rig.executor.launched] == [()]
        (d,) = graph.state["problems"][pid]["deliveries"]
        assert d["outcome"] == "answered" and graph.state["artifacts"][d["answer"]]["class"] == "authored"
        assert [graph.state["artifacts"][a]["class"] for a in d["claims"][0]["refs"]] == ["exec"]
        b = graph.budget(pid)
        assert b["reserved"]["usd_milli"] == 0 and b["spent"]["usd_milli"] > 0
        text = render.status(graph.state, pid, b)
        assert "开放道" in text and "完整回答；未经判定" in text and "主张 2 条，有留档支撑 1 条" in text
        assert "无留档支撑" in text
        close(graph, pid, feedback="adopted")
        p = graph.state["problems"][pid]
        assert p["terminal"] == "delivered" and p["feedback"] == "adopted"
        t = views.problems(graph.state)["totals"]
        assert t["solved"] == 0 and t["cost_per_solve_usd_milli"] is None  # 不进严格道统计
        assert t["by_authority"]["self"]["delivered"] == 1 and t["by_authority"]["local"]["problems"] == 0
    finally:
        rig.close()


def test_blocked_ends_honestly(tmp_path, graph, upstream):  # noqa: F811
    """做不下去就如实交“受阻”：写明需要人提供什么，不编答案。终态是 unsolved，不是 delivered。"""
    rig = stand_up(
        tmp_path,
        graph,
        upstream,
        [
            {"tool": EXEC, "input": {"cmd": "getent hosts report.corp"}},
            {
                "tool": DELIVER,
                "input": {
                    "outcome": "blocked",
                    "claims": [{"text": "工作区里解析不到 report.corp", "refs": ["$r0.artifact"]}],
                    "needs": ["内网报表系统的地址与访问批准"],
                    "unverified": ["上个月的销售额"],
                },
            },
        ],
    )
    try:
        out = kaiti(rig, "登录公司内网的报表系统，告诉我上个月的销售额。")
        pid = out["pid"]
        r = Sinan(SinanConfig(token="tok-sinan"), graph, graph, rig.blobs, rig.runner).run(pid)
        assert r["stop"] == "needs_human" and r["items"][0]["why"] == "blocked"
        (d,) = graph.state["problems"][pid]["deliveries"]
        assert d["outcome"] == "blocked" and "answer" not in d and d["needs"]
        assert "受阻" in render.status(graph.state, pid, graph.budget(pid))
        close(graph, pid, feedback="none")
        assert graph.state["problems"][pid]["terminal"] == "unsolved"
        by = views.problems(graph.state)["totals"]["by_authority"]["self"]
        assert by["delivered"] == 0 and by["unsolved"] == 1
    finally:
        rig.close()


def test_credential_in_the_prompt_stays_off_the_card(tmp_path, graph, upstream):  # noqa: F811
    """正文带凭据：开题零出站（地址只作展示）；会话申请访问时理由里带了凭据，送审前已遮盖；交付里也遮。"""
    rig = stand_up(
        tmp_path,
        graph,
        upstream,
        [
            {"tool": ACCESS, "input": {"target": "api.repo.test:443", "why": f"带上 {TOKEN} 调接口数仓库"}},
            {
                "tool": DELIVER,
                "input": {"outcome": "blocked", "needs": [f"批准 api.repo.test:443（会用 {TOKEN}）"]},
            },
        ],
    )
    try:
        out = kaiti(rig, f"用我的令牌 token: {TOKEN} 查一下 https://api.repo.test 上我有几个仓库。")
        pid = out["pid"]
        assert [r["resource"] for r in out["input"]["scope"]] == ["workspace"]
        assert TOKEN not in json.dumps(out["notes"], ensure_ascii=False)
        r = Sinan(SinanConfig(token="tok-sinan"), graph, graph, rig.blobs, rig.runner).run(pid)
        assert r["stop"] == "needs_human"
        st = graph.state
        assert [b["egress"] for b in rig.executor.launched] == [()]  # 没批之前出不去
        (req,) = st["scope_requests"].values()
        assert req["status"] == "pending" and TOKEN not in req["why"]
        assert TOKEN not in json.dumps(seen_card(st, pid, "scope", req["id"]), ensure_ascii=False)
        assert TOKEN not in json.dumps(st["problems"][pid]["deliveries"], ensure_ascii=False)
        assert any(w["why"] == "scope_request" for w in wk.work(st, pid))
    finally:
        rig.close()
