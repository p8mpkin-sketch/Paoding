"""D1：Blob 仓库。3.2.5 的 1、4。"""
import io

import pytest

from paoding_graph import blobs
from paoding_graph.blobs import BlobNotFound, BlobStore, BlobTooLarge, CorruptBlob


def test_dedup(tmp_path):
    """3.2.5 的 1：相同字节上传两次，得到同一哈希、一个 Blob。"""
    s = BlobStore(tmp_path)
    h1, h2 = s.put(b"hello"), s.put(io.BytesIO(b"hello"))
    assert h1 == h2
    files = [p for p in tmp_path.rglob("*") if p.is_file() and "tmp" not in p.relative_to(tmp_path).parts]
    assert len(files) == 1
    assert s.get(h1) == b"hello" and s.get(h1, 1, 3) == b"el"


def test_corrupt(tmp_path):
    """3.2.5 的 4：改动 Blob 的一个字节，读取时报 corrupt。"""
    s = BlobStore(tmp_path)
    h = s.put(b"abcdef")
    p = s.path(h)
    p.chmod(0o644)
    p.write_bytes(b"abcdeF")
    with pytest.raises(CorruptBlob) as e:
        s.get(h)
    assert e.value.code == "corrupt"


def test_immutable_on_disk(tmp_path):
    s = BlobStore(tmp_path)
    assert s.path(s.put(b"x")).stat().st_mode & 0o222 == 0


def test_unknown(tmp_path):
    s = BlobStore(tmp_path)
    with pytest.raises(BlobNotFound):
        s.get("0" * 64)
    with pytest.raises(BlobNotFound):
        s.get("../etc/passwd")


def test_too_large_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(blobs, "MAX_BLOB", 10)
    s = BlobStore(tmp_path)
    with pytest.raises(BlobTooLarge):
        s.put(b"x" * 11)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]
