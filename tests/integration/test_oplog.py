"""结构化日志（P2-3 第 1 项）：字段、上下文 ID 的白名单、文件与 stderr 两路。不需要 Docker。"""
from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import oplog  # noqa: E402
from stack import StackConfig  # noqa: E402


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


def lines(text: str) -> list[dict]:
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def test_json_lines_go_to_stderr_and_file_with_context_ids(tmp_path, monkeypatch, restore_logging):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    f = tmp_path / "logs" / "stack.log"
    oplog.setup_logging(file=f)
    logging.getLogger("sinan").info("会话开始：%s", "bootstrap", extra=oplog.ctx(problem_id="p1", lease_id="l-3"))
    logging.getLogger("graph").warning("多行\n消息", extra=oplog.ctx(seq=7, kind="lease", request_id=None))
    logging.getLogger("judge").debug("级别以下，不出")
    for out in (lines(err.getvalue()), lines(f.read_text(encoding="utf-8"))):
        assert [r["component"] for r in out] == ["sinan", "graph"]
        a, b = out
        assert a["level"] == "info" and a["msg"] == "会话开始：bootstrap"
        assert a["problem_id"] == "p1" and a["lease_id"] == "l-3"
        assert a["ts"].endswith("Z") and len(a["ts"]) == len("2026-11-18T06:00:00.000Z")
        assert b["level"] == "warning" and b["msg"] == "多行\n消息" and b["seq"] == 7 and "request_id" not in b
        assert set(a) == {"ts", "level", "component", "msg", "problem_id", "lease_id"}


def test_exceptions_carry_a_traceback_on_one_line(tmp_path, monkeypatch, restore_logging):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    oplog.setup_logging()
    try:
        raise RuntimeError("坏了")
    except RuntimeError:
        logging.getLogger("watchdog").exception("tick 失败")
    raw = err.getvalue()
    assert raw.count("\n") == 1                                         # 回溯在 JSON 字符串里，不另起行
    [r] = lines(raw)
    assert r["level"] == "error" and "RuntimeError: 坏了" in r["exc"]


def test_only_registered_context_keys_are_emitted(tmp_path, monkeypatch, restore_logging):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    oplog.setup_logging()
    logging.getLogger("stack").info("x", extra={"token": "secret-value", "problem_id": "p1"})
    [r] = lines(err.getvalue())
    assert "token" not in r and "secret-value" not in err.getvalue() and r["problem_id"] == "p1"
    with pytest.raises(KeyError):
        oplog.ctx(token="secret-value")


def test_text_format_only_changes_stderr(tmp_path, monkeypatch, restore_logging):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    f = tmp_path / "stack.log"
    oplog.setup_logging(fmt="text", file=f)
    logging.getLogger("graph").info("#3 p1 lease", extra=oplog.ctx(seq=3))
    assert err.getvalue().split(" ", 1)[1].startswith("graph")
    assert lines(f.read_text(encoding="utf-8"))[0]["seq"] == 3
    with pytest.raises(ValueError):
        oplog.setup_logging(level="loud")
    with pytest.raises(ValueError):
        oplog.setup_logging(fmt="xml")


def test_log_options_come_from_config(tmp_path):
    cfg = StackConfig.load(tmp_path)
    assert cfg.log == {"level": "info", "format": "json", "file": "logs/stack.log", "access": False}
    assert cfg.log_file() == tmp_path / "logs" / "stack.log"
    name = "config.yaml" if "yaml" in (StackConfig.load.__doc__ or "").lower() else "config.json"
    (tmp_path / name).write_text(json.dumps({"log": {"access": True, "file": "", "level": "debug"}}))
    cfg = StackConfig.load(tmp_path)
    assert cfg.log["access"] is True and cfg.log["level"] == "debug" and cfg.log_file() is None
    (tmp_path / name).write_text(json.dumps({"log": {"colour": True}}))
    with pytest.raises(ValueError):
        StackConfig.load(tmp_path)
