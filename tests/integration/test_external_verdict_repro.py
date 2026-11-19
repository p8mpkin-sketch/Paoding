"""复现：外部裁决类任务开不了题（设计 docs/design/external-verdict/ §1）。不需要 Docker，不调模型。

最小外部平台模拟只有四类端点：任务清单、说明、提交、回执。它在本机起一个 HTTP 服务，说明里的服务地址
每次领题时现分配（运行时才知道），时限由平台规定（6 小时，超过本地单题硬顶 4 小时），"怎么算做完"由平台
回执给出（本地没有答案，也没有可跑的检查）。

每条用例断言的都是**设计稿写成时的行为**，作为设计的证据，不是期望的行为。翻转后的版本是验收门，
在 test_external_verdict_flip.py：一期（内核）翻转了行 1（结构化开题一侧）、4、4b、5，二期（connector 运行器）
翻转了行 2（开题时领题，资源公告进材料）并把行 5 换成真运行器。这里留下的断言对应的是入口一侧
（行 1、1b 的起草与校验，三期）与 accept=human（行 3，D3），到期再翻；行 2 这里留的是"起草时没有地址"这条证据，
翻转后仍然成立。
行 4 的"wall_s=21600 被单题硬顶拒"在新设计下仍然成立且正确：平台时限进 deadline，不进花费预算。

    uv run pytest -q tests/integration/test_external_verdict_repro.py
    uv run python tests/integration/test_external_verdict_repro.py      # 打印一份复现记录（设计文档 §1.2 的原始材料）
"""

from __future__ import annotations

import itertools
import json
import secrets
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "e2e"))

from drive import call  # noqa: E402
from stack import Stack, StackConfig  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_mock import Platform  # noqa: E402

# ---------------------------------------------------------------- 夹具


@pytest.fixture
def plat():
    p = Platform()
    yield p
    p.close()


@pytest.fixture
def stack(tmp_path):
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none"))
    url = s.http.serve()
    yield s, url
    s.http.close()


def _codes(out: dict[str, Any]) -> list[str]:
    return [n["code"] for n in out["notes"]]


def _submit(s: Stack, url: str, out: dict[str, Any], mutate, key: str) -> dict[str, Any]:
    """把起草服务给的提交批（确认道）按网页同一条路提交，提交前对开题体做一处改动。"""
    tok = s.human_token
    for b in out["blobs"]:
        call(url, "/v1/blobs", token=tok, raw=b["text"].encode())
    ops = json.loads(json.dumps(out["ops"]))
    body = ops[-1]["body"]
    if out.get("secret"):
        body["goal"]["check"]["sealed"] = [call(url, "/v1/vault", token=tok, raw=out["secret"].encode())]
    mutate(body)
    return call(url, "/v1/problems", {"id": out["pid"], "idem_key": key, "ops": ops}, token=tok)


def _rejects(res: dict[str, Any]) -> list[tuple[str, str]]:
    return [(r.get("code", ""), r.get("detail", "")) for r in res["results"] if r.get("code")]


# ---------------------------------------------------------------- 表现一：平台裁决型


def case_platform_refused(s: Stack, url: str, plat: Platform) -> dict[str, Any]:
    out = call(url, "/v1/drafts", {"text": plat.pasted()}, token=s.human_token)
    return {"lane": out["lane"], "notes": _codes(out), "input": out.get("input")}


def test_1_platform_verdict_is_refused(stack, plat):
    """判定权在平台：本地没有答案键可密封，也没有检查命令可登记。判据形态只有 answer / command 两种，拒绝。"""
    s, url = stack
    r = case_platform_refused(s, url, plat)
    assert r["lane"] == "refuse"
    assert "no_criterion" in r["notes"]
    assert r["input"] is None


def case_platform_misbound(s: Stack, url: str, plat: Platform) -> dict[str, Any]:
    out = call(url, "/v1/drafts", {"text": plat.pasted(with_example=True)}, token=s.human_token)
    body = out["ops"][-1]["body"] if out.get("ops") else {}
    spec = next((b["text"] for b in out.get("blobs", []) if b["text"].startswith("curl ")), None)
    return {
        "lane": out["lane"],
        "notes": _codes(out),
        "judge": body.get("goal", {}).get("check", {}).get("judge_id"),
        "spec": spec,
        "wall_s": body.get("budget", {}).get("wall_s"),
        "scope": [(r["pattern"], r["risk"]) for r in body.get("scope", [])],
        "out": out,
    }


def test_1b_only_non_refusal_is_a_misbinding(stack, plat):
    """说明里带一段提交示例时，唯一不被拒的路是把**提交命令**当成**检查命令**登记成 replay 判据。

    判官会在洁净容器里重放一次提交（占用平台提交次数），而 replay 判的是退出码，不是平台回执。
    vet 无法区分"检查命令"和"提交命令"，因为它不知道判定权在外部。
    """
    s, url = stack
    r = case_platform_misbound(s, url, plat)
    assert r["lane"] == "confirm"
    assert r["judge"] == "replay" and r["spec"] is not None and "/submissions" in r["spec"]
    assert r["spec"].startswith("curl -X POST")  # 判据就是那条提交命令，逐字
    assert "command_criterion" in r["notes"]


# ---------------------------------------------------------------- 表现二：资源运行时发现型（#91 已裁决，这里只留证据）


def test_2_instance_address_only_exists_at_runtime(stack, plat):
    s, url = stack
    a = plat.get("/api/tasks/T-17")["instance"]
    b = plat.get("/api/tasks/T-17")["instance"]
    assert a != b  # 每次领题现分配
    out = call(url, "/v1/drafts", {"text": plat.pasted()}, token=s.human_token)
    assert a not in json.dumps(out, ensure_ascii=False) and b not in json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------- 表现三：人工裁决型（D3 已裁决未实现）


def case_human_accept(s: Stack, url: str, plat: Platform) -> list[tuple[str, str]]:
    out = case_platform_misbound(s, url, plat)["out"]

    def human(b: dict[str, Any]) -> None:
        b["goal"]["accept"] = "human"
        b["budget"]["wall_s"] = 3600

    return _rejects(_submit(s, url, out, human, "k-human"))


def test_3_accept_human_is_rejected_by_kernel(stack, plat):
    s, url = stack
    rej = case_human_accept(s, url, plat)
    assert ("schema_error", "M0 只实现 accept=judge") in rej


# ---------------------------------------------------------------- 表现四：时限外部规定型


def case_time(s: Stack, url: str, plat: Platform) -> dict[str, Any]:
    r = case_platform_misbound(s, url, plat)

    def platform_limit(b: dict[str, Any]) -> None:
        b["budget"]["wall_s"] = Platform.TIME_LIMIT_S

    rej = _rejects(_submit(s, url, r["out"], platform_limit, "k-time"))
    return {"vet_wall_s": r["wall_s"], "vet_notes": r["notes"], "kernel": rej}


def test_4_external_time_limit_is_clipped_then_rejected(stack, plat):
    """平台给 6 小时；起草服务把它悄悄裁到单题硬顶 4 小时（照平台规则，第 4 小时之后的工作全被丢掉），
    原样提交则内核按 over_budget 拒绝。"""
    s, url = stack
    r = case_time(s, url, plat)
    cap = s.graph.cfg.open_cap_wall_s
    assert cap is not None and cap < Platform.TIME_LIMIT_S
    assert r["vet_wall_s"] == cap and "clipped_wall_s" in r["vet_notes"]
    assert any(code == "over_budget" for code, _ in r["kernel"])


def case_wall_is_elapsed(s: Stack, url: str, plat: Platform) -> dict[str, Any]:
    """budget.wall_s 在哮天犬那里是"自开题起的墙钟"，与花没花钱、是不是在等外部回执无关。"""
    out = case_platform_misbound(s, url, plat)["out"]
    res = _submit(s, url, out, lambda b: None, "k-wall")
    assert res["ok"], res
    p = s.graph.state["problems"][out["pid"]]
    spent = s.graph.budget(out["pid"])["spent"]["usd_milli"]
    s.dog.clock = lambda: p["opened_ts"] + p["budget"]["wall_s"] * 1000
    rep = s.dog.tick()
    return {
        "spent_usd_milli": spent,
        "closed": out["pid"] in rep.closed,
        "close": s.graph.state["problems"][out["pid"]].get("closed"),
    }


def test_4b_wall_budget_is_elapsed_time_not_spend(stack, plat):
    s, url = stack
    r = case_wall_is_elapsed(s, url, plat)
    assert r["spent_usd_milli"] == 0 and r["closed"]


# ---------------------------------------------------------------- 判官侧：没有"外部回执"这一种裁决来源


def test_5_judge_side_has_no_external_verdict_path(stack, plat):
    """注册表里只有 exact_match 与 replay；判官运行器同步出裁决（fn(ctx) → Outcome），没有 pending。
    平台回执要轮询两次以上才出结果。"""
    s, _ = stack
    assert sorted(s.registry) == ["exact_match", "replay"]
    assert all(spec["kind"] != "deferred" for spec in s.registry.values())
    sid = plat.post("/api/tasks/T-17/submissions", {"answer": "x"})["submission_id"]
    assert plat.get(f"/api/submissions/{sid}")["status"] == "pending"


# ---------------------------------------------------------------- 复现记录


def transcript(tmp: Path) -> dict[str, Any]:
    plat = Platform()
    s = Stack(StackConfig.load(tmp / "home", port=0, executor="none"))
    url = s.http.serve()
    try:
        out: dict[str, Any] = {"pasted": plat.pasted(), "pasted_with_example": plat.pasted(with_example=True)}
        out["1_platform"] = case_platform_refused(s, url, plat)
        mb = case_platform_misbound(s, url, plat)
        out["1b_misbound"] = {k: v for k, v in mb.items() if k != "out"}
        a, b = plat.get("/api/tasks/T-17")["instance"], plat.get("/api/tasks/T-17")["instance"]
        out["2_instances"] = [a, b]
        out["3_human"] = case_human_accept(s, url, plat)
        out["4_time"] = case_time(s, url, plat)
        out["4b_wall"] = case_wall_is_elapsed(s, url, plat)
        out["caps"] = {"open_cap_wall_s": s.graph.cfg.open_cap_wall_s, "platform_time_limit_s": Platform.TIME_LIMIT_S}
        out["registry"] = {k: v["kind"] for k, v in s.registry.items()}
        out["platform_log"] = plat.log
        return out
    finally:
        s.http.close()
        plat.close()


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        print(json.dumps(transcript(Path(d)), ensure_ascii=False, indent=2, default=str))
