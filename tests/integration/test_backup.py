"""备份与恢复（P2-3 第 3 项）：scripts/backup.sh 在图服务开着的时候备份，恢复出来的目录重放得到同一个状态。
不需要 Docker。"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from paoding_graph.contract import BlobStore, Config, GraphService, TokenRegistry

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "scripts" / "backup.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash")


def state_hash(svc: GraphService) -> str:
    from paoding_graph.replay import state_hash as h

    return h(svc.state)


def make_home(home: Path) -> tuple[GraphService, BlobStore, list[str]]:
    home.mkdir()
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": "cz"}, "tok-human")
    svc = GraphService(home / "g.sqlite", Config(), reg)
    blobs = BlobStore(home / "blobs")
    hashes = [blobs.put(f"材料 {i}".encode()) for i in range(3)]
    for i, h in enumerate(hashes):
        r = svc.submit(
            "tok-human",
            "p1",
            f"reg-{i}",
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "class": "input",
                        "hash": h,
                        "size": len(f"材料 {i}".encode()),
                        "media_type": "text/plain",
                    },
                }
            ],
        )
        assert r["ok"], r
    (home / "vault").mkdir()
    (home / "vault" / "secret").write_text("s3cret")
    (home / "human.token").write_text("tok-human")
    return svc, blobs, hashes


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(BACKUP), *args], capture_output=True, text=True)


def restore(dest: Path, target: Path) -> None:
    """docs/ops.md 的恢复步骤。"""
    target.mkdir()
    shutil.copy(dest / "g.sqlite", target / "g.sqlite")
    with tarfile.open(dest / "blobs.tar.gz") as t:
        t.extractall(target, filter="data")


def test_online_backup_restores_to_the_same_state(tmp_path):
    home = tmp_path / "home"
    svc, blobs, hashes = make_home(home)  # 图服务开着（连接没关，WAL 里有内容）
    want_head, want_state = svc.head(), state_hash(svc)
    r = run("--home", str(home), "--out", str(tmp_path / "bk"))
    assert r.returncode == 0, r.stderr
    [dest] = (tmp_path / "bk").iterdir()
    assert dest.name.startswith("paoding-backup-") and not dest.name.endswith(".partial")
    manifest = dict(
        line.split(" ", 1) for line in (dest / "MANIFEST").read_text().splitlines() if not line.startswith("sha256")
    )
    assert manifest["head_seq"] == str(want_head) and manifest["blobs"] == str(len(hashes))
    sums = {
        line.split()[1]: line.split()[2]
        for line in (dest / "MANIFEST").read_text().splitlines()
        if line.startswith("sha256")
    }
    assert set(sums) == {"g.sqlite", "blobs.tar.gz"}  # 保密库缺省不备份
    for name, digest in sums.items():
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == digest

    # 备份之后原目录继续写：不影响已做完的备份
    svc.submit(
        "tok-human",
        "p1",
        "reg-later",
        [
            {
                "op": "register_artifact",
                "body": {"class": "input", "hash": blobs.put(b"later"), "size": 5, "media_type": "text/plain"},
            }
        ],
    )

    target = tmp_path / "restored"
    restore(dest, target)
    back = GraphService(target / "g.sqlite", Config(), TokenRegistry())
    assert back.head() == want_head and state_hash(back) == want_state
    for pid in back.log.problems():
        back.log.verify(pid)  # 哈希链完整
    rb = BlobStore(target / "blobs")
    for i, h in enumerate(hashes):
        assert rb.get(h) == f"材料 {i}".encode()  # 读取时校验哈希
    assert not (target / "vault").exists() and not (target / "human.token").exists()


def test_with_vault_and_argument_errors(tmp_path):
    home = tmp_path / "home"
    make_home(home)
    r = run("--home", str(home), "--with-vault")
    assert r.returncode == 0, r.stderr
    [dest] = (home / "backups").iterdir()  # 缺省放在 <home>/backups
    with tarfile.open(dest / "vault.tar.gz") as t:
        assert "vault/secret" in t.getnames()
    assert "sha256 vault.tar.gz" in (dest / "MANIFEST").read_text()

    assert run().returncode == 2
    assert run("--home", str(tmp_path / "nope")).returncode == 2
    assert run("--home", str(home), "--frobnicate").returncode == 2
    assert not list((home / "backups").glob("*.partial"))


def test_falls_back_to_python_when_sqlite3_cli_is_missing(tmp_path):
    """没有 sqlite3 命令行的机器（CI 镜像常见）走 Python 标准库的同一个备份接口。"""
    home = tmp_path / "home"
    svc, _, _ = make_home(home)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in (
        "bash",
        "python3",
        "tar",
        "date",
        "mkdir",
        "rm",
        "mv",
        "sed",
        "grep",
        "cut",
        "sha256sum",
        "cat",
        "gzip",
        "dirname",
        "env",
    ):
        src = shutil.which(tool)
        if src:
            (bindir / tool).symlink_to(src)
    r = subprocess.run(
        ["bash", str(BACKUP), "--home", str(home), "--out", str(tmp_path / "bk")],
        capture_output=True,
        text=True,
        env={"PATH": str(bindir)},
    )
    assert r.returncode == 0, r.stderr
    [dest] = (tmp_path / "bk").iterdir()
    assert f"head_seq {svc.head()}" in (dest / "MANIFEST").read_text()
