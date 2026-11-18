"""Blob 仓库（契约 2，规格 §3.2.2）：本地目录，按 sha256 寻址。

- 写入：先写临时文件、fsync，再原子改名；相同内容自动去重；一经写入不可变。
- 读取：每次校验哈希，不符抛 CorruptBlob（3.2.5 的 4，错误码 corrupt）。
- 单个 Blob 上限 256 MB；超出的截断由采集方负责（保留头尾、置 truncated），本层只拒绝。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

MAX_BLOB = 256 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1 << 20


class BlobError(Exception):
    code = "blob_error"


class CorruptBlob(BlobError):
    code = "corrupt"


class BlobTooLarge(BlobError):
    code = "too_large"


class BlobNotFound(BlobError):
    code = "unknown_ref"


class BlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "tmp").mkdir(parents=True, exist_ok=True)

    def path(self, h: str) -> Path:
        if not _HEX64.match(h):
            raise BlobNotFound(f"不是 sha256：{h!r}")
        return self.root / h[:2] / h[2:]

    def put(self, data: bytes | BinaryIO) -> str:
        stream = _as_stream(data)
        hasher, size = hashlib.sha256(), 0
        fd, tmp = tempfile.mkstemp(dir=self.root / "tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > MAX_BLOB:
                        raise BlobTooLarge(f"超过 {MAX_BLOB} 字节")
                    hasher.update(chunk)
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            h = hasher.hexdigest()
            dest = self.path(h)
            if dest.exists():
                os.unlink(tmp)  # 去重：已存在即同一内容
            else:
                dest.parent.mkdir(exist_ok=True)
                os.chmod(tmp, 0o444)
                os.replace(tmp, dest)
            return h
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def exists(self, h: str) -> bool:
        return self.path(h).exists()

    def get(self, h: str, start: int = 0, end: int | None = None) -> bytes:
        """读取并校验整个 Blob 的哈希；range 读取同样先校验全文。"""
        p = self.path(h)
        if not p.exists():
            raise BlobNotFound(h)
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != h:
            raise CorruptBlob(h)
        return data[start:end]

    def size(self, h: str) -> int:
        return self.path(h).stat().st_size


def _as_stream(data: bytes | BinaryIO) -> BinaryIO:
    if isinstance(data, (bytes, bytearray, memoryview)):
        import io

        return io.BytesIO(bytes(data))
    return data
