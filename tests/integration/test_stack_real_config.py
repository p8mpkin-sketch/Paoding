"""macOS 补丁之三：scripts/stack.py 的 backend.kind=real 认 program / api_key / api_base / model（真实环境验证过）。

不起真 CLI、不连真模型：只组装不 start，检查配置落到了端点代理与 CLI 绑定上。启动器用 local、执行层 none，
不需要 Docker。密钥是假的。
"""

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from stack import Stack, StackConfig, StackError  # noqa: E402

from paoding_adapter.backend import LaunchPlan  # noqa: E402

FAKE_KEY = "sk-fake-config-key-not-real"


def _cfg(tmp_path, **backend):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"backend": {"kind": "real", "launcher": "local", **backend}, "executor": "none"}))
    return StackConfig.load(tmp_path / "home", p)


def _argv(stack, tmp_path):
    plan = LaunchPlan("l_1", tmp_path / "ws", tmp_path / "sys.md", "go", tmp_path / "mcp.json")
    return stack.adapter_cfg.binding.command(plan)[0]


def _close(stack):
    stack.endpoint.close()
    stack.proxy.close()


def test_real_backend_takes_program_api_base_model_and_key(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    caplog.set_level(logging.WARNING)
    cfg = _cfg(
        tmp_path,
        program="/opt/bin/claude --debug",
        api_base="https://api.deepseek.com/anthropic",
        model="deepseek-chat",
        api_key=FAKE_KEY,
    )
    assert (cfg.program, cfg.upstream, cfg.model, cfg.api_key) == (
        ("/opt/bin/claude", "--debug"),
        "https://api.deepseek.com/anthropic",
        "deepseek-chat",
        FAKE_KEY,
    )
    s = Stack(cfg)
    try:
        assert s.proxy.cfg.upstream == "https://api.deepseek.com/anthropic" and s.proxy.cfg.api_key == FAKE_KEY
        argv = _argv(s, tmp_path)
        assert argv[:2] == ["/opt/bin/claude", "--debug"]
        assert argv[argv.index("--model") + 1] == "deepseek-chat"
        assert any("backend.api_key" in r.getMessage() for r in caplog.records)
        assert not any(FAKE_KEY in r.getMessage() for r in caplog.records)  # 密钥不进日志
    finally:
        _close(s)


def test_env_key_wins_over_config_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-env")
    s = Stack(_cfg(tmp_path, program=["claude"], api_key=FAKE_KEY))
    try:
        assert s.proxy.cfg.api_key == "sk-fake-env"
        assert "--model" not in _argv(s, tmp_path)  # 没给 model 就不传
    finally:
        _close(s)


def test_real_backend_without_any_key_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(StackError, match="backend.api_key"):
        Stack(_cfg(tmp_path))


def test_bad_program_refused(tmp_path):
    with pytest.raises(StackError, match="backend.program"):
        _cfg(tmp_path, program=[1, 2])
