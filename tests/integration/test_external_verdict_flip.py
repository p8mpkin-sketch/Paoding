"""外部裁决的验收门：复现翻转表（docs/design/external-verdict/ §9）里已落地的各行，在全栈上翻过来。

同一个平台模拟（platform_mock.Platform）。二期起判官是真的 connector 运行器：注册表条目与连接器档案写进
临时的 judges.d、connectors.d，经 StackConfig 交给组装根，平台令牌经环境变量注入钥匙环槽位，与部署同一条路。
一期用过的测试替身已删，断言不变。

| 行 | 翻过来的是什么 |
| 1  | 已登记的平台：结构化开题被接受，goal.authority=external，快照带连接器摘要（入口一侧的翻转在三期） |
| 2  | 开题时连接器领题，资源公告（含运行时分到的服务地址）作 input 类材料登记；scope 不因此变宽（批准归 #91） |
| 4  | 平台时限进 deadline，wall_s 守在单题硬顶以内：不裁、不拒 |
| 4b | wall_mode 两种取值：elapsed 照旧关（缺省没变），spend 不关 |
| 5  | 回执两次 pending 后 accepted：Goal 到 E3，终态 solved，authority=external；平台只收到一次提交 |
| 金丝雀 | 平台令牌跑完上面的路径，在数据目录、日志、事件里逐字搜不到（§9 第 4 条） |
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "e2e"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive import call  # noqa: E402
from paoding_judgebox.contract import DEFAULT_DIR, Connector  # noqa: E402
from platform_mock import Platform, profile  # noqa: E402
from stack import Stack, StackConfig  # noqa: E402

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
ENV = "PD_CONNECTOR_MOCK_PLATFORM"  # 槽位 mock-platform 的环境变量名


@pytest.fixture
def plat():
    p = Platform()
    yield p
    p.close()


def _stack(tmp_path: Path, plat: Platform, monkeypatch, wall_mode: str = "elapsed") -> tuple[Stack, str]:
    jd, cd = tmp_path / "judges.d", tmp_path / "connectors.d"
    shutil.copytree(DEFAULT_DIR, jd)
    (jd / "ext_receipt.yaml").write_text(yaml.safe_dump(EXT_SPEC), encoding="utf-8")
    cd.mkdir()
    (cd / "mock-platform.yaml").write_text(yaml.safe_dump(profile(plat), allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv(ENV, plat.token)
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none", judges_dir=jd, connectors_dir=cd))
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
    """ "从平台导入"会生成的那份结构化开题（三期的入口照这个形状生成）。领题由连接器替人去取（§5.5）。"""
    tok = s.human_token
    conn = Connector(s.connectors["mock-platform"]["doc"], s.keyring.get)
    t = conn.tasks()[0]
    notice = conn.notice(t["id"])  # 开题时领题：平台此刻开始计时，服务地址此刻现分配
    brief = json.loads(notice)
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
                    "at": opened_at + int(conn.field(brief, "time_limit_s")) * 1000,
                    "bound_by": "$1",
                },
            },
        }
    )
    return call(url, "/v1/problems", {"id": pid, "idem_key": f"open-{pid}", "ops": ops}, token=tok)


def test_row1_structured_open_is_accepted(tmp_path, plat, monkeypatch):
    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        res = _open(s, url, plat)
        assert res["ok"], res
        p = s.graph.state["problems"]["ext1"]
        assert p["goal"]["authority"] == "external" and p["profile"]["judge"] == "deferred"
        c = s.connectors["mock-platform"]
        assert p["judge_snapshot"]["ext_receipt"]["connector"] == {
            "id": "mock-platform",
            "version": "1",
            "digest": c["digest"],
        }
        assert p["scope"] == [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}]
    finally:
        s.http.close()


def test_row4_platform_limit_goes_to_deadline_not_budget(tmp_path, plat, monkeypatch):
    s, url = _stack(tmp_path, plat, monkeypatch)
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
def test_row4b_both_wall_modes(tmp_path, plat, monkeypatch, mode, closed):
    s, url = _stack(tmp_path, plat, monkeypatch, wall_mode=mode)
    try:
        assert _open(s, url, plat)["ok"]
        p = s.graph.state["problems"]["ext1"]
        assert p.get("wall_mode", "elapsed") == mode
        s.dog.clock = lambda: p["opened_ts"] + p["budget"]["wall_s"] * 1000  # 花费 0，开题墙钟走满 wall_s
        rep = s.dog.tick()
        assert ("ext1" in rep.closed) is closed
    finally:
        s.http.close()


def _solve(s: Stack, url: str, plat: Platform) -> list[str]:
    """交一份候选（平台的口令），按判官的时钟一路复判到关题，返回各次裁决的原因码。"""
    tok = s.human_token
    cand = _blob(url, tok, plat.flag.encode())
    aid = s.graph.submit(tok, "ext1", "cand", [cand])["results"][0]["id"]
    rq = {"op": "request_judge", "body": {"target": "goal", "judge_id": "ext_receipt", "candidate": aid}}
    assert s.graph.submit(tok, "ext1", "rq", [rq])["ok"]
    t = {"now": 10**12}
    s.judge.clock = lambda: t["now"]
    results: list[str] = []
    for _ in range(6):
        results += [d["reason"] for d in s.judge.tick("ext1")]
        if s.graph.state["problems"]["ext1"].get("closed"):
            break
        assert results == [] or results[-1] == "pending" or results[-1] == "ok"
        assert s.judge.tick("ext1") == []  # recheck_at 未到：不复判
        t["now"] += 2000
    return results


def test_row2_resource_notice_is_registered_at_open(tmp_path, plat, monkeypatch):
    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        assert _open(s, url, plat)["ok"]
        st = s.graph.state
        p = st["problems"]["ext1"]
        addr = plat.started["T-17"]  # 这次领题分到的地址：开题前没有任何一方知道
        (mid,) = p["origin"]["materials"]
        art = st["artifacts"][mid]
        assert art["class"] == "input"  # 资源公告是材料，不是证据（红线 2）
        assert json.loads(s.blobs.get(art["hash"]))["instance"] == addr
        assert p["deadline"]["bound_by"] == mid
        # 地址进了公告，scope 照旧只有 workspace：智能体要用它，得照 #91 申请扩权
        assert p["scope"] == [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}]
    finally:
        s.http.close()


def test_row5_pending_twice_then_accepted_solves(tmp_path, plat, monkeypatch):
    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        assert _open(s, url, plat)["ok"]
        assert _solve(s, url, plat) == ["pending", "pending", "ok"]
        p = s.graph.state["problems"]["ext1"]
        assert p["closed"] and p["terminal"] == "solved" and p["goal"]["authority"] == "external"
        assert sum(1 for line in plat.log if line.startswith("POST")) == 1  # 复判只读回执，不重交
        assert s.keyring.slot_status("mock-platform")["source"] == "env"
    finally:
        s.http.close()


def test_canary_platform_token_never_lands(tmp_path, plat, monkeypatch, caplog):
    """平台令牌只在钥匙环与请求头里。跑完开题、领题、交付、读回执、关题，再故意让一次调用失败，
    数据目录（图库、Blob、提交号状态目录、日志文件）、事件、判官输出与日志里都搜不到它。"""
    caplog.set_level("DEBUG")
    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        assert _open(s, url, plat)["ok"]
        assert _solve(s, url, plat)[-1] == "ok"
        plat.close()  # 平台下线：连接器报错的那条路也走一遍
        conn = Connector(s.connectors["mock-platform"]["doc"], s.keyring.get)
        with pytest.raises(Exception) as e:
            conn.call("receipt", sid="s-x")
        assert plat.token not in str(e.value)
        needle = plat.token.encode()
        hits = [f for f in (tmp_path / "home").rglob("*") if f.is_file() and needle in f.read_bytes()]
        assert hits == []
        assert plat.token not in json.dumps(s.graph.state, ensure_ascii=False)
        assert plat.token not in caplog.text
        assert all(plat.token not in json.dumps(x) for x in s.keyring.status())
    finally:
        s.http.close()


# ---------------------------------------------------------------- 三期：入口（行 1、1b 的起草一侧，§5.8）


def _codes(out: dict[str, Any]) -> list[str]:
    return [n["code"] for n in out["notes"]]


def _submit_view(s: Stack, url: str, out: dict[str, Any]) -> dict[str, Any]:
    tok = s.human_token
    for b in out["blobs"]:
        call(url, "/v1/blobs", token=tok, raw=b["text"].encode())
    return call(url, "/v1/problems", {"id": out["pid"], "idem_key": f"k-{out['pid']}", "ops": out["ops"]}, token=tok)


def test_row1_registered_platform_is_recognized_then_imported(tmp_path, plat, monkeypatch):
    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        tok = s.human_token
        out = call(url, "/v1/drafts", {"text": plat.pasted()}, token=tok)
        assert out["lane"] == "confirm"
        assert out["input"]["goal"]["check"]["judge_id"] == "ext_receipt"
        assert out["external"] == {"connector": "mock-platform", "judge_id": "ext_receipt", "task": "T-17"}
        assert "external_platform" in _codes(out)
        assert out["ops"] is None and plat.started == {}  # 起草不领题：创建时才领
        assert all(r["resource"] == "workspace" for r in out["input"]["scope"])  # 平台地址不进授权
        # 卡上改过的预算带进导入
        imp = call(
            url,
            "/v1/connectors/mock-platform/import",
            {"task": "T-17", "budget": {"wall_s": 3600}},
            token=tok,
        )
        assert plat.started  # 领了题
        assert imp["lane"] == "confirm" and imp["ops"]
        body = imp["ops"][-1]["body"]
        assert body["budget"]["wall_s"] == 3600
        assert body["goal"]["check"]["binding"] == {"connector": "mock-platform", "task": "T-17", "max_submissions": 3}
        assert body["deadline"]["source"] == "external" and body["deadline"]["bound_by"].startswith("$")
        res = _submit_view(s, url, imp)
        assert res["ok"], res
        p = s.graph.state["problems"][imp["pid"]]
        assert p["goal"]["authority"] == "external" and p["deadline"]["at"] > p["opened_ts"]
        notice = s.graph.state["artifacts"][p["origin"]["materials"][0]]
        assert json.loads(s.blobs.get(notice["hash"]))["instance"] == plat.started["T-17"]
    finally:
        s.http.close()


def test_row1_unregistered_platform_refuses_with_register_way(tmp_path, plat):
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none"))
    url = s.http.serve()
    try:
        out = call(url, "/v1/drafts", {"text": plat.pasted()}, token=s.human_token)
        assert out["lane"] == "refuse" and "no_criterion" in _codes(out)
        assert "register_platform" in out["ways"]
        assert call(url, "/v1/connectors", token=s.human_token) == {"items": []}
    finally:
        s.http.close()


def test_row1b_registered_submit_example_is_only_material(tmp_path, plat, monkeypatch):
    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        out = call(url, "/v1/drafts", {"text": plat.pasted(with_example=True)}, token=s.human_token)
        assert out["lane"] == "confirm"
        assert out["input"]["goal"]["check"]["judge_id"] == "ext_receipt"
        assert "submit_example_material" in _codes(out) and "command_criterion" not in _codes(out)
        assert "spec_ref" not in out["input"]["goal"]["check"]
    finally:
        s.http.close()


def test_row1b_unregistered_command_needs_explicit_ack(tmp_path, plat):
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none"))
    url = s.http.serve()
    try:
        tok = s.human_token
        out = call(url, "/v1/drafts", {"text": plat.pasted(with_example=True)}, token=tok)
        assert out["lane"] == "confirm" and out["input"]["goal"]["check"]["judge_id"] == "replay"
        assert {"command_criterion", "command_outbound"} <= set(_codes(out))
        assert out["needs_ack"] == "command" and out["ops"] is None  # 不勾选拿不到批次
        again = call(
            url,
            "/v1/drafts",
            {
                "text": plat.pasted(with_example=True),
                "draft": out["draft"],
                "model": out["model"],
                "nonce": out["nonce"],
                "overrides": {"ack_command": True},
            },
            token=tok,
        )
        assert again["needs_ack"] is None and again["ops"]
        ack = [r for r in again["derivation"] if r["field"] == "goal.check.ack"]
        assert ack and ack[0]["source"] == "human"
    finally:
        s.http.close()


def test_connector_listing_and_tasks(tmp_path, plat, monkeypatch):
    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        tok = s.human_token
        (c,) = call(url, "/v1/connectors", token=tok)["items"]
        assert c["id"] == "mock-platform" and c["judges"] == ["ext_receipt"] and c["slot_set"] is True
        assert plat.token not in json.dumps(c)
        items = call(url, "/v1/connectors/mock-platform/tasks", token=tok)["items"]
        assert items == [{"task": "T-17", "title": "找出服务里的口令", "time_limit_s": 21600, "max_submissions": 3}]
        assert plat.started == {}  # 列清单不领题
    finally:
        s.http.close()


def test_pd_connector_import(tmp_path, plat, monkeypatch):
    import io

    from paoding_pd.cli import main

    s, url = _stack(tmp_path, plat, monkeypatch)
    try:
        monkeypatch.setenv("PD_TOKEN", s.human_token)
        out = io.StringIO()
        assert main(["--url", url, "connector", "list"], out=out) == 0
        assert "mock-platform@1" in out.getvalue() and "已设" in out.getvalue()
        out = io.StringIO()
        assert main(["--url", url, "connector", "tasks", "mock-platform"], out=out) == 0
        assert out.getvalue().startswith("T-17")
        out = io.StringIO()
        rc = main(
            ["--url", url, "connector", "import", "mock-platform", "T-17", "--minutes", "30"],
            out=out,
            read=lambda _: "",
        )
        assert rc == 0, out.getvalue()
        assert "外部判定 · 平台 mock-platform" in out.getvalue() and plat.token not in out.getvalue()
        (pid,) = [p for p in s.graph.state["problems"] if p.startswith("kt-")]
        p = s.graph.state["problems"][pid]
        assert p["goal"]["authority"] == "external" and p["budget"]["wall_s"] == 1800
        out = io.StringIO()  # 被拒的路：没登记的平台
        assert main(["--url", url, "connector", "tasks", "nope"], out=out) == 1 and "没有登记平台" in out.getvalue()
    finally:
        s.http.close()
