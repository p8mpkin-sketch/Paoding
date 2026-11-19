"""全栈配置的装载（P2-4 第 6 项：配置统一为 YAML）。不需要 Docker。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "scripts" / "e2e"
sys.path.insert(0, str(ROOT / "scripts"))

from stack import StackConfig  # noqa: E402


def test_sample_config_is_yaml_and_resolves_relative_paths(tmp_path):
    cfg = StackConfig.load(tmp_path, E2E / "config.yaml")
    assert cfg.backend == "fake" and cfg.executor == "docker"
    assert cfg.scripts == {k: str(E2E / f"{k}.json") for k in ("bootstrap", "reason", "explore", "solve")}
    assert cfg.bases == {"basic": "python:3.12-slim"}
    assert cfg.poll_s == 0.3 and cfg.dog_interval_s == 1.0


def test_no_config_file_means_empty_config(tmp_path):
    cfg = StackConfig.load(tmp_path)
    assert cfg.backend == "fake" and cfg.scripts == {} and cfg.executor == "docker"


def test_home_config_yaml_is_the_default(tmp_path):
    (tmp_path / "config.yaml").write_text("backend: fake\nexecutor:\n  kind: fake\npoll_s: 2\n")
    cfg = StackConfig.load(tmp_path)
    assert cfg.executor == "fake" and cfg.poll_s == 2


def test_empty_yaml_file_is_empty_config(tmp_path):
    (tmp_path / "config.yaml").write_text("# 只有注释\n")
    assert StackConfig.load(tmp_path).backend == "fake"


def test_legacy_config_json_still_loads(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"executor": {"kind": "fake"}, "poll_s": 1.5}))
    cfg = StackConfig.load(tmp_path)
    assert cfg.executor == "fake" and cfg.poll_s == 1.5


def test_both_files_present_is_an_error(tmp_path):
    (tmp_path / "config.yaml").write_text("poll_s: 1\n")
    (tmp_path / "config.json").write_text("{}")
    with pytest.raises(ValueError, match="config.json"):
        StackConfig.load(tmp_path)


def test_top_level_must_be_a_mapping(tmp_path):
    (tmp_path / "config.yaml").write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="映射"):
        StackConfig.load(tmp_path)
