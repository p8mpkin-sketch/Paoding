"""设置层（宪章 03 §2–§7，L1 第①个 PR）：设置存储、钥匙环端点、三道硬顶、pd settings/keys，以及金丝雀测试。

金丝雀（03 §4.4，AC0.2 / AC-M5，裁决附加 2：每一期验收都跑）：把一个形如真密钥的随机串经设置页的端点注入钥匙环，
走开题、转发、设置变更、日志（含异常栈）、pd 命令，然后在数据目录的每个文件、日志文件、stderr、应答体里逐字搜，
命中即失败。另一条：进程重启后钥匙环为空，真实后端的代理回 503，司南不开会话。

不需要 Docker：假上游、执行层 none、宿主子进程。
"""

from __future__ import annotations

import io
import json
import logging
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "e2e"))

import oplog  # noqa: E402
from drive import open_problem  # noqa: E402
from settings_hub import KEY_NOTE  # noqa: E402
from stack import Stack, StackConfig  # noqa: E402

from paoding_pd.cli import main as pd  # noqa: E402


def req(url: str, method: str, path: str, body=None, token: str | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(url + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    yield
    for h in root.handlers:
        if h not in saved:
            h.close()
    root.handlers[:] = saved
    root.setLevel(level)


def make(tmp_path: Path, backend: dict | None = None, home: Path | None = None) -> Stack:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"backend": backend or {"kind": "fake"}, "executor": "none", "poll_s": 0.1}))
    return Stack(StackConfig.load(home or tmp_path / "home", p, port=0, static_dir=None))


@pytest.fixture
def stack(tmp_path):
    s = make(tmp_path)
    s.start()
    yield s
    s.stop()


def test_settings_roundtrip_and_concurrency(stack):
    url, tok = stack.url, stack.human_token
    code, doc = req(url, "GET", "/v1/settings")
    assert code == 200 and doc["version"] == 1 and doc["settings"]["caps"]["global_usd_milli"] == 500_000
    assert doc["settings"]["models"]["routes"]["draft"] == "default"  # 起草模型的钩子（03 §3.4）
    new = json.loads(json.dumps(doc["settings"]))
    new["caps"]["open_usd_milli"] = 4000
    body = {"base_digest": doc["digest"], "settings": new}

    assert req(url, "PUT", "/v1/settings", body)[0] == 401  # 没令牌
    assert req(url, "PUT", "/v1/settings", body, stack.tok["sinan"])[0] == 403  # 组件令牌不行，只认人
    code, out = req(url, "PUT", "/v1/settings", body, tok)
    assert code == 200 and out["version"] == 2 and out["digest"] != doc["digest"]
    code, out = req(url, "PUT", "/v1/settings", body, tok)  # 同一个 base_digest 再写：过期
    assert code == 409 and out["code"] == "stale_view" and out["current"] == stack.settings.store.digest

    log = req(url, "GET", "/v1/settings/log")[1]["items"]
    assert [e["version"] for e in log] == [1, 2] and log[1]["keys"] == ["caps.open_usd_milli"]
    assert log[1]["from"] == doc["digest"] and log[1]["by"] == "human"


@pytest.mark.parametrize(
    "path,value,why",
    [
        (("caps", "open_usd_milli"), 600_000, "超过全局硬顶"),
        (("caps", "practice_usd_milli"), 600_000, "超过单题硬顶"),
        (("caps", "global_usd_milli"), None, "不可关"),
        (("caps", "open_usd_milli"), -1, "正整数"),
        (("models", "routes", "draft"), "nope", "不是已登记的档案"),
        (("models", "api_key"), "sk-x", "设置里不放密钥"),
    ],
)
def test_settings_validation(stack, path, value, why):
    doc = req(stack.url, "GET", "/v1/settings")[1]
    s = doc["settings"]
    cur = s
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    code, out = req(stack.url, "PUT", "/v1/settings", {"base_digest": doc["digest"], "settings": s}, stack.human_token)
    assert code == 400 and why in out["detail"]
    assert stack.settings.store.version == 1


def test_open_cap_and_settings_digest_reach_open_problem(stack):
    url, tok = stack.url, stack.human_token
    doc = req(url, "GET", "/v1/settings")[1]
    s = doc["settings"]
    s["caps"]["open_usd_milli"] = 4999  # drive.py 的题预算 5000
    s["caps"]["practice_usd_milli"] = 1000
    s["caps"]["global_usd_milli"] = 400_000
    req(url, "PUT", "/v1/settings", {"base_digest": doc["digest"], "settings": s}, tok)
    assert stack.proxy.cfg.global_cap_usd_milli == 400_000  # 全局硬顶立即生效
    out = open_problem(url, tok, "capped")
    assert not out["ok"] and any(r.get("code") == "over_budget" for r in out["results"])

    doc = req(url, "GET", "/v1/settings")[1]
    s = doc["settings"]
    s["caps"]["open_usd_milli"] = 5000
    req(url, "PUT", "/v1/settings", {"base_digest": doc["digest"], "settings": s}, tok)
    assert open_problem(url, tok, "fits")["ok"]
    p = stack.graph.state["problems"]["fits"]
    assert p["settings"] == {"version": stack.settings.store.version, "digest": stack.settings.store.digest}


def test_keys_endpoints(stack):
    url, tok = stack.url, stack.human_token
    assert req(url, "GET", "/v1/keys")[0] == 401
    code, out = req(url, "GET", "/v1/keys", token=tok)
    assert code == 200 and out["note"] == KEY_NOTE == "密钥重启后失效，可用环境变量持久注入"
    assert [s["source"] for s in out["slots"]] == ["fake"]
    assert req(url, "PUT", "/v1/keys/BAD%20SLOT", {"key": "x"}, tok)[0] == 400
    assert req(url, "PUT", "/v1/keys/default", {"key": "has space"}, tok)[0] == 400
    code, st = req(url, "PUT", "/v1/keys/second", {"key": "sk-second-1234"}, tok)
    assert code == 200 and st["set"] and st["fingerprint"].endswith("1234") and "sk-second-1234" not in json.dumps(st)
    assert req(url, "DELETE", "/v1/keys/second", token=tok)[1]["set"] is False
    out = req(url, "DELETE", "/v1/keys", token=tok)[1]
    assert not any(s["set"] for s in out["slots"]) and not stack.keyring.ready("default")


def test_pd_settings_and_keys(stack, monkeypatch):
    monkeypatch.setenv("PD_TOKEN", stack.human_token)
    out = io.StringIO()
    assert pd(["--url", stack.url, "settings", "show"], out=out) == 0
    assert "global_usd_milli: 500000" in out.getvalue()
    out = io.StringIO()
    assert pd(["--url", stack.url, "settings", "set", "caps.open_usd_milli", "20000"], out=out) == 0
    assert stack.graph.cfg.open_cap_usd_milli == 20000 and "v2" in out.getvalue()
    out = io.StringIO()
    assert pd(["--url", stack.url, "settings", "set", "caps.open_usd_milli", "900000"], out=out) == 1
    assert "超过全局硬顶" in out.getvalue()
    assert pd(["--url", stack.url, "settings", "set", "caps.nope", "1"], out=io.StringIO()) == 2
    out = io.StringIO()
    assert pd(["--url", stack.url, "keys", "set", "default"], out=out, read_key=lambda: "sk-from-pd-5678") == 0
    assert stack.keyring.get("default") == "sk-from-pd-5678" and "sk-from-pd-5678" not in out.getvalue()
    out = io.StringIO()
    assert pd(["--url", stack.url, "keys", "show"], out=out) == 0
    assert "default：已设" in out.getvalue() and "环境变量持久注入" in out.getvalue()
    assert pd(["--url", stack.url, "keys", "clear", "--all"], out=io.StringIO()) == 0
    assert not stack.keyring.ready("default")


def _grep_tree(root: Path, needle: bytes) -> list[str]:
    return [str(f) for f in root.rglob("*") if f.is_file() and needle in f.read_bytes()]


def test_canary_key_never_leaves_the_keyring(tmp_path, monkeypatch, restore_logging, capfd):
    canary = "sk-ant-canary-" + secrets.token_hex(20)
    home = tmp_path / "home"
    oplog.setup_logging(file=home / "logs" / "stack.log")  # 与 run.py 同样先起日志
    s = make(tmp_path, home=home)
    s.start()
    seen: list[str] = []
    try:
        url, tok = s.url, s.human_token
        code, st = req(url, "PUT", "/v1/keys/default", {"key": canary}, tok)
        seen.append(json.dumps(st))
        assert code == 200 and s.keyring.get("default") == canary
        # 开题、改设置、经代理转发一次（真密钥换上去发给假上游）
        seen.append(json.dumps(open_problem(url, tok, "canary")))
        doc = req(url, "GET", "/v1/settings")[1]
        doc["settings"]["caps"]["open_usd_milli"] = 50_000
        seen.append(
            json.dumps(
                req(url, "PUT", "/v1/settings", {"base_digest": doc["digest"], "settings": doc["settings"]}, tok)
            )
        )
        seen += [json.dumps(req(url, "GET", p, token=tok)) for p in ("/v1/settings", "/v1/settings/log", "/v1/keys")]
        s.proxy.register_task("task-canary", "l_none", "canary", 1000)
        import http.client

        c = http.client.HTTPConnection(
            "127.0.0.1", int(s.proxy.url.rsplit(":", 1)[1]) if s.proxy.url else 0, timeout=10
        )
        c.request(
            "POST",
            "/v1/messages",
            body=b'{"model":"claude-sonnet-5-5","messages":[]}',
            headers={"x-api-key": "task-canary"},
        )
        r = c.getresponse()
        seen.append(r.read().decode(errors="replace"))
        c.close()
        assert (
            s.upstream.seen and {k.lower(): v for k, v in s.upstream.seen[-1]["headers"].items()}["x-api-key"] == canary
        )
        # 组件不小心把密钥写进日志（消息、参数、异常栈）：遮盖要挡住
        L = logging.getLogger("adapter")
        L.warning("上游拒了密钥 " + canary)
        L.error("参数里 %s", canary)
        try:
            raise RuntimeError(f"connect failed key={canary}")
        except RuntimeError:
            L.exception("异常栈里")
        out = io.StringIO()
        monkeypatch.setenv("PD_TOKEN", tok)
        pd(["--url", url, "keys", "show"], out=out)
        pd(["--url", url, "settings", "show"], out=out)
        seen.append(out.getvalue())
    finally:
        s.stop()
    for h in logging.getLogger().handlers:
        h.flush()
    needle = canary.encode()
    assert (home / "logs" / "stack.log").exists()
    assert _grep_tree(home, needle) == []  # g.sqlite、blobs、settings/、logs/、sessions/ …
    assert _grep_tree(tmp_path, needle) == []  # 配置文件也没有
    err = capfd.readouterr()
    assert canary not in err.out + err.err
    assert not any(canary in x for x in seen)
    assert "<密钥 " in (home / "logs" / "stack.log").read_text(encoding="utf-8")


def _leases(s: Stack, pid: str, after_seq: int = 0) -> list:
    return [le for le in s.graph.state["leases"].values() if le["problem_id"] == pid and le["issued_seq"] > after_seq]


def _until(cond, timeout: float = 10.0) -> bool:
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_no_key_sinan_waits_then_restart_empties_keyring(tmp_path, monkeypatch, caplog):
    """没有密钥：真实后端照常起，司南不开会话并说明在等密钥；注入后才开。重启后钥匙环为空，又回到等待。"""
    import time

    caplog.set_level(logging.INFO)
    monkeypatch.delenv("PD_TEST_KEY", raising=False)
    cli = tmp_path / "bin" / "claude"
    cli.parent.mkdir()
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    backend = {"kind": "real", "launcher": "local", "program": str(cli), "api_key_env": "PD_TEST_KEY"}
    s = make(tmp_path, backend)
    s.start()
    try:
        assert s.health()["adapter"]["key_set"] is False
        assert open_problem(s.url, s.human_token, "waits")["ok"]
        assert _until(lambda: any("模型密钥未设" in r.getMessage() for r in caplog.records))
        time.sleep(0.5)
        assert _leases(s, "waits") == []
        assert req(s.url, "PUT", "/v1/keys/default", {"key": "sk-before-restart-0000"}, s.human_token)[0] == 200
        assert _until(lambda: _leases(s, "waits") != [])  # 唯一挡着的就是密钥
    finally:
        s.stop()
    s = make(tmp_path, backend)
    head = s.graph.head()
    s.start()
    try:
        assert not s.keyring.ready("default") and s.health()["adapter"]["key_set"] is False
        out = req(s.url, "GET", "/v1/keys", token=s.human_token)[1]
        assert out["slots"][0]["set"] is False and out["slots"][0]["env"] == "PD_TEST_KEY"
        time.sleep(1.0)
        assert _leases(s, "waits", head) == []
    finally:
        s.stop()
