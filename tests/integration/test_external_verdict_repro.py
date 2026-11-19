"""复现：外部裁决类任务开不了题（设计 docs/design/external-verdict/ §1）。不需要 Docker，不调模型。

最小外部平台模拟只有四类端点：任务清单、说明、提交、回执。它在本机起一个 HTTP 服务，说明里的服务地址
每次领题时现分配（运行时才知道），时限由平台规定（6 小时，超过本地单题硬顶 4 小时），"怎么算做完"由平台
回执给出（本地没有答案，也没有可跑的检查）。

每条用例断言的都是**今天的行为**，作为设计的证据，不是期望的行为。方案落地时这些断言要按设计 §9 翻转，
翻转后的版本就是验收门。

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

# ---------------------------------------------------------------- 最小外部平台模拟


class Platform:
    """四类端点。凭据是一条 Bearer 令牌（真实部署里它归钥匙环管，见设计 §5.6）。

    GET  /api/tasks                       任务清单：id、标题、时限、提交次数上限
    GET  /api/tasks/{id}                  说明：题面；领题即开始计时，服务地址此刻现分配
    POST /api/tasks/{id}/submissions      提交：{answer} → 202 {submission_id}
    GET  /api/submissions/{sid}           回执：先 pending 若干次，再 accepted / rejected（平台说了算）
    """

    TIME_LIMIT_S = 6 * 3600
    MAX_SUBMISSIONS = 3
    PENDING_POLLS = 2

    def __init__(self) -> None:
        self.token = "plat-" + secrets.token_hex(8)
        self.flag = "FLAG-" + secrets.token_hex(6)  # 只有平台知道；本地任何一方都拿不到
        self.ports = itertools.count(31000)
        self.started: dict[str, str] = {}  # task → 本次领题分到的服务地址
        self.subs: dict[str, dict[str, Any]] = {}
        self.log: list[str] = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        plat = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, code: int, body: Any) -> None:
                data = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {plat.token}":
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self) -> None:  # noqa: N802
                if not self._authed():
                    return
                plat.log.append(f"GET {self.path}")
                parts = self.path.strip("/").split("/")
                if parts == ["api", "tasks"]:
                    return self._send(
                        200,
                        [
                            {
                                "id": "T-17",
                                "title": "找出服务里的口令",
                                "time_limit_s": plat.TIME_LIMIT_S,
                                "max_submissions": plat.MAX_SUBMISSIONS,
                            }
                        ],
                    )
                if parts[:2] == ["api", "tasks"] and len(parts) == 3:
                    addr = f"127.0.0.1:{next(plat.ports)}"  # 每次领题现分配：开题时无从预测
                    plat.started[parts[2]] = addr
                    return self._send(
                        200,
                        {
                            "id": parts[2],
                            "statement": "服务里藏着一个口令，找到后提交给平台。平台按回执判定，限时与计分由平台规定。",
                            "instance": addr,
                            "time_limit_s": plat.TIME_LIMIT_S,
                        },
                    )
                if parts[:2] == ["api", "submissions"] and len(parts) == 3:
                    s = plat.subs.get(parts[2])
                    if s is None:
                        return self._send(404, {"error": "no such submission"})
                    s["polls"] += 1
                    if s["polls"] <= plat.PENDING_POLLS:
                        return self._send(200, {"id": parts[2], "task": s["task"], "status": "pending"})
                    ok = s["answer"] == plat.flag
                    return self._send(
                        200,
                        {
                            "id": parts[2],
                            "task": s["task"],
                            "status": "accepted" if ok else "rejected",
                            "score": 100 * ok,
                        },
                    )
                self._send(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authed():
                    return
                plat.log.append(f"POST {self.path}")
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "submissions":
                    n = sum(1 for s in plat.subs.values() if s["task"] == parts[2])
                    if n >= plat.MAX_SUBMISSIONS:
                        return self._send(429, {"error": "submission limit"})
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                    sid = "s-" + secrets.token_hex(4)
                    plat.subs[sid] = {"task": parts[2], "answer": body.get("answer"), "polls": 0}
                    return self._send(202, {"submission_id": sid})
                self._send(404, {"error": "not found"})

        return H

    # 测试方的动作：读清单与说明，把任务的自然语言描述拼出来贴进一句话开题
    def get(self, path: str) -> Any:
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def post(self, path: str, body: Any) -> Any:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def pasted(self, with_example: bool = False) -> str:
        t = self.get("/api/tasks")[0]
        hours = t["time_limit_s"] // 3600
        text = (
            f"平台任务 {t['id']}：{t['title']}。服务里藏着一个口令，找到后提交给平台，平台回执判定通过就算完成。"
            f"服务地址领题后由平台返回。限时 {hours} 小时，每题最多提交 {t['max_submissions']} 次。"
        )
        if with_example:  # 平台说明里常见的"提交示例"
            text += f'提交方式：`curl -X POST {self.base}/api/tasks/{t["id"]}/submissions -d \'{{"answer":"..."}}\'`'
        return text


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
