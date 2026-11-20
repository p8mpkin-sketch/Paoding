"""验收①（cz 2026-11-20）：金丝雀密钥放进导入资料，确认它不出现在索引、日志与会话能拿到的东西里。

会话（第二期）拿到的只有检索结果与单段原文，这里把它们、书库日志、索引库文件、解析出的纯文本 Blob 都查一遍。
原文 Blob 是人交来的字节本身，不改它，所以不在检查范围里。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paoding_graph.contract import BlobStore
from paoding_shuku import creds
from paoding_shuku.service import Rejected, Shuku

CANARIES = {
    "prefixed": "sk-canary7Qm2Zx9Lw4Rt8Yp",
    "labeled": "Kc4nary-Lbl-9931",
    "aws": "AKIACANARY0000FAKE42",
    "pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIcanaryPEMbody0123456789\n-----END RSA PRIVATE KEY-----",
}

DOC = f"""# 部署

回滚用上一个标签重新发布。

## 账号

调接口用 {CANARIES["prefixed"]}，备用 password: {CANARIES["labeled"]}

对象存储的访问键 {CANARIES["aws"]}。

{CANARIES["pem"]}

## 监控

延迟超过 300ms 报警。
"""


def needles() -> list[bytes]:
    out = []
    for v in CANARIES.values():
        out.append(v.encode())
        out.append(v.encode("utf-16-le"))  # FTS 等内部存储换编码时也查得到
    out.append(b"MIIcanaryPEMbody")
    return out


def assert_clean(blob: bytes, where: str) -> None:
    for n in needles():
        assert n not in blob, f"金丝雀出现在 {where}"


def test_found_recognises_every_canary() -> None:
    hits = creds.found(DOC)
    for v in CANARIES.values():
        assert any(v in h or h in v for h in hits), v
    masked = creds.mask(DOC, hits)
    assert_clean(masked.encode(), "遮盖后的文字")
    assert "回滚用上一个标签" in masked and "延迟超过 300ms" in masked


def test_canary_never_reaches_index_log_or_session(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    sk = Shuku(tmp_path / "shuku", blobs)
    data = DOC.encode()
    sid = sk.put_source(
        "运维手册", "file", "all", {"hash": blobs.put(data), "size": len(data), "media_type": "", "name": "ops.md"}
    )
    sk.tick()
    job = sk.jobs()[0]
    assert job["failed"]["code"] == "secrets" and job["failed"]["count"] >= 4
    assert_clean(json.dumps(sk.jobs(), ensure_ascii=False).encode(), "导入作业")
    assert sk.tick() == []  # 停住，不自己往下走
    with pytest.raises(Rejected):  # mask 只取布尔
        sk.act("job_retry", {"source": sid, "revision": 1, "mask": "yes"})
    sk.act("job_retry", {"source": sid, "revision": 1, "mask": True})
    for _ in range(4):
        sk.tick()
    src = sk.sources()[0]
    assert src["live_revision"] == 1 and src["chunks"] > 0

    # 会话能拿到的：检索结果、单段原文
    seen = []
    for q in ("账号", "接口", "password", "访问键", "PRIVATE KEY", "回滚", "sk-canary7Qm2Zx9Lw4Rt8Yp"):
        res = sk.search(q, k=20)
        seen.append(res)
        for h in res["hits"]:
            seen.append(sk.chunk(h["id"]))
    assert any(h["hits"] for h in seen if isinstance(h, dict) and "hits" in h)
    assert_clean(json.dumps(seen, ensure_ascii=False).encode(), "检索结果与单段原文")
    assert any(creds.MASK in json.dumps(x, ensure_ascii=False) for x in seen)
    assert_clean(json.dumps([sk.sources(), sk.jobs()], ensure_ascii=False).encode(), "资料列表")

    # 解析出的纯文本 Blob
    rev = sk.state["sources"][sid]["revisions"][0]
    assert_clean(blobs.get(rev["info"]["text"]), "解析出的纯文本")
    assert "已遮盖" in "".join(rev["info"]["warnings"])
    sk.close()

    # 书库日志与索引库（连同 WAL）
    for f in sorted((tmp_path / "shuku").iterdir()):
        assert_clean(f.read_bytes(), f.name)


def test_mask_only_for_secrets_failures(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    sk = Shuku(tmp_path / "shuku", blobs)
    data = b"%PDF-1.4"
    sid = sk.put_source(
        "扫描件", "file", "all", {"hash": blobs.put(data), "size": 8, "media_type": "application/pdf", "name": "a.pdf"}
    )
    sk.tick()
    assert sk.jobs()[0]["failed"]["code"] == "unsupported"
    with pytest.raises(Rejected) as ei:
        sk.act("job_retry", {"source": sid, "revision": 1, "mask": True})
    assert ei.value.code == "conflict"
    sk.close()
