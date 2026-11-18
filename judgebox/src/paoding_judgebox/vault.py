"""保密库（§3.3.2 判官资产的含密级）：Blob 仓库之外的一个目录，只有判官运行器读。

Problem 里出现的只有键与加盐摘要 `VaultRef {vault, digest}`：摘要让人事后核对资产没被换过，
盐让它不能用来离线穷举。库里的内容不进日志、不进 Blob、不进任何容器。
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class VaultError(Exception):
    """键不存在、键非法，或内容与登记的摘要不符（资产被换过）。"""


class Vault:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _path(self, key: str) -> Path:
        if not _KEY.match(key):
            raise VaultError(f"键非法：{key!r}")
        return self.root / key

    def put(self, key: str, content: bytes) -> dict:
        """存入一份资产，返回写进 Check.sealed 的引用。"""
        p = self._path(key)
        salt = secrets.token_bytes(16)
        for path, data in ((p, content), (p.with_name(p.name + ".salt"), salt)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        return {"vault": key, "digest": hashlib.sha256(salt + content).hexdigest()}

    def open(self, ref: dict) -> bytes:
        p = self._path(str(ref.get("vault", "")))
        try:
            content, salt = p.read_bytes(), p.with_name(p.name + ".salt").read_bytes()
        except OSError:
            raise VaultError(f"保密库里没有 {ref.get('vault')!r}") from None
        if hashlib.sha256(salt + content).hexdigest() != ref.get("digest"):
            raise VaultError("保密库内容与登记的摘要不符")
        return content
