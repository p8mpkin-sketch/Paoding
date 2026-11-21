"""scripts/trial/trial.py 的开题一步（在 cz 自己的电脑上跑）：钉住提交、核对许可证、在本机下载归档随题上传。

这里不联网：git、GitHub 的接口与下载都换成替身，只看脚本自己的规则
（缓存、大小上限、题号、记录、传给 tunshi.py 的参数）。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def trial():
    spec = importlib.util.spec_from_file_location("trial_script", ROOT / "scripts" / "trial" / "trial.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_urlopen(data: bytes, seen: list[str]):
    def urlopen(req, timeout=0):
        seen.append(req.full_url)
        return Body(data)

    return urlopen


SHA = "0123456789abcdef0123456789abcdef01234567"


def test_download_pins_the_commit_and_reuses_a_verified_cache(trial, tmp_path, monkeypatch):
    seen: list[str] = []
    data = b"\x1f\x8b fake tarball" * 1000
    monkeypatch.setattr(trial.urllib.request, "urlopen", fake_urlopen(data, seen))
    f, digest = trial.download("https://github.com/o/r", SHA, tmp_path / "cache")
    assert seen == [f"https://codeload.github.com/o/r/tar.gz/{SHA}"]  # 按提交哈希取，不取分支
    assert f.read_bytes() == data and digest == hashlib.sha256(data).hexdigest()
    assert f.name == f"o-r-{SHA[:12]}.tar.gz" and not list((tmp_path / "cache").glob("*.part"))
    # 再开一次（例如重跑）：缓存的摘要对得上，不再下载
    assert trial.download("https://github.com/o/r.git", SHA, tmp_path / "cache") == (f, digest) and len(seen) == 1
    # 缓存被改过：摘要对不上，重新下载
    f.write_bytes(b"tampered")
    assert trial.download("https://github.com/o/r", SHA, tmp_path / "cache") == (f, digest) and len(seen) == 2


def test_download_refuses_oversized_archives_and_foreign_hosts(trial, tmp_path, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(trial, "ARCHIVE_MAX", 1000)
    monkeypatch.setattr(trial.urllib.request, "urlopen", fake_urlopen(b"x" * 5000, seen))
    with pytest.raises(SystemExit, match="归档超过"):
        trial.download("https://github.com/o/big", SHA, tmp_path / "cache")
    assert list((tmp_path / "cache").iterdir()) == []  # 半截的不留
    with pytest.raises(SystemExit, match="只认 https://github.com"):
        trial.download("https://gitlab.com/o/r", SHA, tmp_path / "cache")
    assert len(seen) == 1


def args(**kw) -> argparse.Namespace:
    base = {
        "url": "http://127.0.0.1:8100",
        "token_file": "human.token",
        "cases": "",
        "only": [],
        "usd": 20.0,
        "via": "upload",
        "tag": "",
        "cache": "trial-cache",
    }
    return argparse.Namespace(**{**base, **kw})


@pytest.fixture
def stubbed(trial, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases = tmp_path / "cases.json"
    rows = [
        {"id": "trial-a", "case": "甲", "repo": "https://github.com/o/a", "statement": "看看甲"},
        {"id": "trial-b", "case": "乙", "repo": "https://github.com/o/b", "ref": "v1", "statement": "看看乙"},
    ]
    cases.write_text(json.dumps({"cases": rows}), encoding="utf-8")
    monkeypatch.setattr(trial, "pin", lambda repo, ref: (SHA, f"{ref or '最新标签'} → {SHA[:12]}"))
    lic = {"https://github.com/o/a": "Apache-2.0", "https://github.com/o/b": "NOASSERTION"}
    monkeypatch.setattr(trial, "license_of", lambda repo, sha: {"spdx": lic[repo]})
    got: list[tuple] = []

    def download(repo, sha, cache):
        got.append((repo, sha, cache))
        f = tmp_path / "a.tar.gz"
        f.write_bytes(b"tar")
        return f, "d" * 64

    monkeypatch.setattr(trial, "download", download)
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(trial.subprocess, "run", run)
    return str(cases), got, calls


def test_open_uploads_the_pinned_archive_with_its_origin(trial, stubbed, tmp_path):
    cases, got, calls = stubbed
    assert trial.open_cases(args(cases=cases, tag="2")) == 1  # 乙的许可证不清楚：不开题，退出码照实非零
    assert [x[:2] for x in got] == [("https://github.com/o/a", SHA)]  # 许可证不清楚的连下载都不做
    (argv,) = calls
    at = argv.index("--upload")
    assert argv[at : at + 4] == [
        "--upload",
        str(tmp_path / "a.tar.gz"),
        "--upload-origin",
        f"https://github.com/o/a@{SHA}",
    ]
    assert "--repo" not in argv and "--dry-run" in argv
    assert argv[argv.index("--pid") + 1] == "trial-a-2"  # 重跑换题号
    assert argv[argv.index("--title") + 1] == f"试算：甲（o/a@{SHA[:12]}）"
    record = json.loads((tmp_path / "trial-record.json").read_text(encoding="utf-8"))
    assert set(record) == {"trial-a-2", "trial-b"}
    a = record["trial-a-2"]
    assert a["opened"] and a["commit"] == SHA and a["license"]["spdx"] == "Apache-2.0"
    assert a["archive"] == {"file": str(tmp_path / "a.tar.gz"), "sha256": "d" * 64, "bytes": 3}
    assert record["trial-b"]["skipped"] and "pid" not in record["trial-b"]


def test_open_via_repo_lets_the_session_fetch(trial, stubbed):
    cases, got, calls = stubbed
    trial.open_cases(args(cases=cases, via="repo", only=["trial-a"]))
    (argv,) = calls
    assert got == [] and "--upload" not in argv
    assert (
        argv[argv.index("--repo") + 1] == f"https://github.com/o/a@{SHA}" and argv[argv.index("--pid") + 1] == "trial-a"
    )
