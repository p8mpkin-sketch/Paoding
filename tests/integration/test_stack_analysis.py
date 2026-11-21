"""方案分析实例（docs/design/fenjue/13-kernel.md §7）：scripts/stack.py 整套起来，analysis.enabled 打开。

开题抄分析实例的功法；司南照开放道派 solve；会话跑固定流程的驱动程序（宿主子进程），模型由假上游按调用键回放
录音；人在确认点上追问；工作区导出到 <home>/analyses/<题号>/。执行层关着（上传的材料不用沙箱）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "adapter" / "tests"))

from stack import Stack, StackConfig, analysis_config  # noqa: E402
from tunshi_rig import Replay, cases, fixture_tar  # noqa: E402

from paoding_fenjue import shapes  # noqa: E402
from paoding_fenjue.contract import GONGFA_ENV, analysis, engine_gongfa_path  # noqa: E402


@pytest.fixture
def engine_env(monkeypatch):
    """Stack 会把环境变量设成分析实例的功法；先由 monkeypatch 设上同一个值，测试结束时它负责还原。"""
    monkeypatch.setenv(GONGFA_ENV, str(engine_gongfa_path()))
    shapes.gongfa.cache_clear()
    yield
    monkeypatch.delenv(GONGFA_ENV, raising=False)
    shapes.gongfa.cache_clear()


def make(tmp_path, analysis_cfg=None, model="claude-sonnet-5-5"):
    p = tmp_path / "config.yaml"
    cfg = {
        "backend": {"kind": "fake", "model": model},
        "executor": "none",
        "poll_s": 0.1,
        "analysis": analysis_cfg if analysis_cfg is not None else {"enabled": True, "canaries": cases.CANARIES},
    }
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return Stack(StackConfig.load(tmp_path / "home", p, port=0, static_dir=None))


def put(s, data: bytes, media: str, pid: str, n: int) -> str:
    out = s.graph.submit(
        s.human_token,
        pid,
        f"in-{pid}-{n}",
        [
            {
                "op": "register_artifact",
                "body": {"hash": s.blobs.put(data), "size": len(data), "media_type": media, "class": "input"},
            }
        ],
    )
    assert out["ok"], out
    return out["results"][0]["id"]


def open_analysis(s, pid="pa1"):
    mid = put(s, fixture_tar("alpha"), "application/gzip", pid, 1)
    doc = {**cases.intake("alpha", "code"), "sources": [{"no": 1, "form": "code", "via": "upload", "artifact": mid}]}
    iid = put(s, json.dumps(doc, ensure_ascii=False).encode(), analysis.INTAKE_MEDIA, pid, 2)
    sid = put(s, "看看验收夹具甲里有什么值得集成的做法".encode(), "text/plain", pid, 3)
    body = {
        "title": "方案分析：验收夹具甲",
        "origin": {"statement_ref": sid, "materials": [mid, iid]},
        "goal": {"statement": "看看验收夹具甲里有什么值得集成的做法", "accept": "open"},
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": 20_000, "wall_s": 14_400, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": [],
    }
    out = s.graph.submit(s.human_token, pid, f"open-{pid}", [{"op": "open_problem", "body": body}])
    assert out["ok"], out


def wait_deliveries(s, pid, n, timeout=60):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        p = s.graph.state["problems"].get(pid) or {}
        ds = p.get("deliveries") or []
        busy = any(x["active"] for x in s.graph.state["leases"].values() if x["problem_id"] == pid)
        if len(ds) >= n and not busy:
            return ds
        time.sleep(0.1)
    raise AssertionError(f"{timeout} 秒内没有第 {n} 次交付：{s.graph.state['problems'].get(pid)}")


def test_an_analysis_instance_runs_an_analysis_through_its_first_two_confirmations(tmp_path, engine_env):
    s = make(tmp_path)
    s.upstream.reply = Replay(cases.recording("alpha", "code"))
    s.start()
    try:
        assert s.graph.cfg.gongfa[1] == shapes.gongfa_digest(json.loads(engine_gongfa_path().read_text()))
        open_analysis(s)
        p = s.graph.state["problems"]["pa1"]
        assert p["gongfa"]["digest"] == s.graph.cfg.gongfa[1]  # 开题记下的是分析实例的那一版
        (d1,) = wait_deliveries(s, "pa1", 1)
        lease = s.graph.state["leases"][d1["lease"]]
        assert lease["form"] == "h1.tunshi@1" and d1["outcome"] == "partial"
        # 各档位的模型取自设置层（这里只有一个缺省档案：三档都用它）；单价取端点代理的价目表
        prof = s._analysis_profile("pa1")
        assert prof["models"] == {
            "heavy": "claude-sonnet-5-5",
            "mid": "claude-sonnet-5-5",
            "light": "claude-sonnet-5-5",
        }
        assert prof["prices"]["heavy"] == [2000, 10000] and prof["bang"] and prof["locks"] == []
        assert {b["model"] for b in s.upstream.reply.requests} == {"claude-sonnet-5-5"}
        # 工作区导出给界面的读端点
        exported = s.cfg.home / "analyses" / "pa1"
        run = json.loads((exported / "run.json").read_text(encoding="utf-8"))
        assert run["step"] == "G1"
        cands = json.loads((exported / "artifacts" / f"{run['artifacts']['candidates.json']}.json").read_text())
        seen = {"seq": s.graph.state["seq"]}
        out = s.graph.submit(
            s.human_token,
            "pa1",
            "fu-1",
            [{"op": "follow_up", "body": {"text": cases.g1_block(cands), "seen": seen}}],
        )
        assert out["ok"], out
        ds = wait_deliveries(s, "pa1", 2)
        assert ds[-1]["outcome"] == "partial" and "第 2 次确认" in ds[-1]["needs"][-1]
        assert json.loads((exported / "run.json").read_text(encoding="utf-8"))["step"] == "G2"
        assert s.upstream.reply.misses == []
        # 会话活动的读端点照常（结构栏的工作流图读它）
        view = s.runner.activity(ds[-1]["lease"])
        assert view and any(x["kind"] == "turn" for x in view["items"])
    finally:
        s.stop()


def test_without_any_model_the_analysis_says_so(tmp_path, engine_env):
    s = make(tmp_path, model="")
    s.start()
    try:
        open_analysis(s)
        (d,) = wait_deliveries(s, "pa1", 1)
        assert d["outcome"] == "blocked" and "没有给" in d["needs"][0] and "档位配模型" in d["needs"][0]
    finally:
        s.stop()


def test_the_analysis_section_is_validated():
    assert analysis_config(None)["enabled"] is False
    assert analysis_config({"enabled": True})["access_wait_s"] == 600
    for bad in (
        {"enabeld": True},
        {"enabled": "yes"},
        {"pains": [{"dim": "x"}]},
        {"canaries": [""]},
        {"access_wait_s": -1},
        {"access_wait_s": True},
        {"by": " "},
        [],
    ):
        with pytest.raises(ValueError):
            analysis_config(bad)


def test_an_instance_pointed_at_another_gongfa_refuses_to_become_an_analysis_instance(tmp_path, monkeypatch):
    monkeypatch.setenv(GONGFA_ENV, str(tmp_path / "trial.json"))
    from stack import StackError

    with pytest.raises(StackError, match="分析实例的功法"):
        make(tmp_path)
    monkeypatch.delenv(GONGFA_ENV)
    shapes.gongfa.cache_clear()


def test_a_normal_instance_is_unchanged(tmp_path):
    s = make(tmp_path, analysis_cfg={})
    try:
        assert s.adapter_cfg.drivers == {} and s.adapter_cfg.analysis is None and s.adapter_cfg.analysis_export is None
        assert (
            s.graph.cfg.gongfa[1] == shapes.gongfa()["digest"] and shapes.current().form("solve")["fire"] != "h1.tunshi"
        )
    finally:
        s.stop()


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "tunshi.py"), *args], capture_output=True, text=True, timeout=60
    )


def test_the_helper_script_opens_an_analysis_over_http_and_the_engine_takes_it_up(tmp_path, engine_env):
    s = make(tmp_path)
    s.upstream.reply = Replay(cases.recording("alpha", "code"))
    url = s.start()
    try:
        tar = tmp_path / "alpha.tar.gz"
        tar.write_bytes(fixture_tar("alpha"))
        tf = str(s.cfg.home / "human.token")
        r = run_script(
            "--url", url, "--token-file", tf, "--pid", "ph1", "--statement", "看看验收夹具甲", "--upload", str(tar),
            "--upload-origin", "https://github.com/o/alpha@" + "a" * 40,
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["ok"] and out["intake"]["mode"] == "formal"
        (src,) = out["intake"]["sources"]
        # 上传的归档带着出处（试算在本机下载钉住的提交再上传）：只登记，不当地址类来源去抓
        assert src["via"] == "upload" and src["form"] == "code"
        assert (src["url"], src["ref"]) == ("https://github.com/o/alpha", "a" * 40)
        p = s.graph.state["problems"]["ph1"]
        arts = s.graph.state["artifacts"]
        media = [arts[a]["media_type"] for a in p["origin"]["materials"]]
        assert media == ["application/gzip", analysis.INTAKE_MEDIA]
        (d1,) = wait_deliveries(s, "ph1", 1)
        assert d1["outcome"] == "partial" and "第 1 次确认" in d1["needs"][-1]
        # 地址类来源与试算模式只能经立项单给；仓库不写提交或标签就不开题
        r = run_script(
            "--url", url, "--token-file", tf, "--pid", "ph2", "--statement", "x", "--repo", "https://github.com/o/r"
        )
        assert r.returncode != 0 and "提交或标签" in r.stderr and "ph2" not in s.graph.state["problems"]
        r = run_script(
            "--url", url, "--token-file", tf, "--pid", "ph4", "--statement", "x", "--upload-origin", "https://github.com/o/r@v1",
        )  # fmt: skip
        assert (
            r.returncode != 0
            and "--upload-origin 比 --upload 多" in r.stderr
            and "ph4" not in s.graph.state["problems"]
        )
        r = run_script(
            "--url", url, "--token-file", tf, "--pid", "ph3", "--statement", "看看这个仓库",
            "--repo", "https://github.com/o/r@v1.2.0", "--doc", "https://example.org/guide.md", "--dry-run",
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
        doc = json.loads(r.stdout)["intake"]
        assert doc["mode"] == "dry_run" and [x["via"] for x in doc["sources"]] == ["repo_url", "doc_url"]
        assert doc["sources"][0]["ref"] == "v1.2.0" and "ph3" in s.graph.state["problems"]
    finally:
        s.stop()
