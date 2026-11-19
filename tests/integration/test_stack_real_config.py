"""macOS 补丁之三：scripts/stack.py 的 backend.kind=real 认 program / api_key / api_base / model（真实环境验证过）。

不起真 CLI、不连真模型：只组装不 start，检查配置落到了端点代理与 CLI 绑定上。启动器用 local、执行层 none，
不需要 Docker。密钥是假的。
"""

import json
import logging
import os
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


def _fake_cli(d: Path, name: str = "claude") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text("#!/bin/sh\nexit 0\n")
    f.chmod(0o755)
    return f


def test_real_backend_takes_program_api_base_model_and_key(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    caplog.set_level(logging.WARNING)
    cli = _fake_cli(tmp_path / "opt" / "bin")
    cfg = _cfg(
        tmp_path,
        program=f"{cli} --debug",
        api_base="https://api.deepseek.com/anthropic",
        model="deepseek-chat",
        api_key=FAKE_KEY,
    )
    assert (cfg.program, cfg.upstream, cfg.model, cfg.api_key) == (
        (str(cli), "--debug"),
        "https://api.deepseek.com/anthropic",
        "deepseek-chat",
        FAKE_KEY,
    )
    s = Stack(cfg)
    try:
        assert s.proxy.cfg.upstream == "https://api.deepseek.com/anthropic"
        assert s.keyring.get("default") == FAKE_KEY and s.keyring.slot_status("default")["source"] == "config"
        assert s.proxy.cfg.api_key == ""  # 配置对象里不留密钥，只在钥匙环
        argv = _argv(s, tmp_path)
        assert argv[:2] == [str(cli), "--debug"]
        assert argv[argv.index("--model") + 1] == "deepseek-chat"
        assert any("backend.api_key" in r.getMessage() for r in caplog.records)
        assert not any(FAKE_KEY in r.getMessage() for r in caplog.records)  # 密钥不进日志
    finally:
        _close(s)


def test_env_key_wins_over_config_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-env")
    monkeypatch.setenv("PATH", f"{_fake_cli(tmp_path / 'bin').parent}:{os.environ['PATH']}")
    s = Stack(_cfg(tmp_path, program=["claude"], api_key=FAKE_KEY))
    try:
        assert s.keyring.get("default") == "sk-fake-env" and s.keyring.slot_status("default")["source"] == "env"
        assert "--model" not in _argv(s, tmp_path)  # 没给 model 就不传
    finally:
        _close(s)


def test_real_backend_without_any_key_starts_and_waits(tmp_path, monkeypatch, caplog):
    """宪章 03 §4.2：没有密钥也照常组装，钥匙环该槽未设，告警里写明怎么注入；司南等密钥（见 test_keys_canary）。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATH", f"{_fake_cli(tmp_path / 'bin').parent}:{os.environ['PATH']}")
    caplog.set_level(logging.WARNING)
    s = Stack(_cfg(tmp_path, program=["claude"]))
    try:
        assert not s.keyring.ready("default")
        assert s.keyring.slot_status("default")["env"] == "ANTHROPIC_API_KEY"
        assert any("密钥未设" in r.getMessage() and "环境变量持久注入" in r.getMessage() for r in caplog.records)
    finally:
        _close(s)


def test_local_cli_resolved_on_host_path(tmp_path, monkeypatch):
    """宿主子进程起真 CLI 时，CLI 进程的 PATH 是固定的几个系统目录：命令按 run.py 的 PATH 解析成绝对路径，
    它所在的目录（以及符号链接指向的目录，node 常在那里）加到 CLI 的 PATH 前面。找不到就当场报错。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-env")
    real = _fake_cli(tmp_path / "pkg" / "bin")
    link_dir = tmp_path / "npm" / "bin"
    link_dir.mkdir(parents=True)
    (link_dir / "claude").symlink_to(real)
    monkeypatch.setenv("PATH", f"{link_dir}:{os.environ['PATH']}")
    s = Stack(_cfg(tmp_path))
    try:
        plan = LaunchPlan("l_1", tmp_path / "ws", tmp_path / "sys.md", "go", tmp_path / "mcp.json")
        argv, env = s.adapter_cfg.binding.command(plan)
        assert argv[0] == str(link_dir / "claude")
        assert env["PATH"].split(":")[:2] == [str(link_dir), str(real.parent)]
    finally:
        _close(s)
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(StackError, match="找不到 CLI 命令"):
        Stack(_cfg(tmp_path))


def test_bad_program_refused(tmp_path):
    with pytest.raises(StackError, match="backend.program"):
        _cfg(tmp_path, program=[1, 2])
