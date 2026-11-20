"""书库第一期：解析、切分、向量、索引、reducer、服务全流程。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from paoding_graph.contract import BlobStore
from paoding_shuku import reducer as rd
from paoding_shuku.chunk import MAX, chunk
from paoding_shuku.embed import HashEmbedder, cosine, make_embedder
from paoding_shuku.index import Index, terms
from paoding_shuku.parse import Unsupported, parse
from paoding_shuku.service import Rejected, Shuku

DOC = """# 部署

部署前先跑全量测试，再打标签。

## 回滚

回滚用上一个标签重新发布。数据库迁移要能反向执行，否则回滚会失败。

# 监控

告警阈值写在 alerts.yaml 里，延迟超过 300ms 持续五分钟就报警。
"""


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000

    def __call__(self) -> int:
        return self.t


def fileof(blobs: BlobStore, data: bytes, name: str, media: str = "") -> dict[str, Any]:
    return {"hash": blobs.put(data), "size": len(data), "media_type": media, "name": name}


@pytest.fixture
def env(tmp_path: Path) -> tuple[Shuku, BlobStore, Clock]:
    blobs = BlobStore(tmp_path / "blobs")
    clock = Clock()
    sk = Shuku(tmp_path / "shuku", blobs, clock=clock)
    yield sk, blobs, clock
    sk.close()


def run(sk: Shuku, n: int = 5) -> None:
    for _ in range(n):
        if not sk.tick():
            return


# ---------- 解析 ----------


def test_parse_kinds() -> None:
    assert parse(b"# t\nhi", "", "a.md").kind == "markdown"
    assert parse(b"x = 1\n", "", "a.py").kind == "code"
    p = parse(b"<html><script>bad()</script><h1>Title</h1><p>a &amp; b</p></html>", "text/html", "x.html")
    assert p.kind == "html" and "bad()" not in p.text and "a & b" in p.text and "Title" in p.text
    assert parse("中文".encode("gb18030"), "", "a.txt").text == "中文"


def test_parse_rejects_later_formats_and_binary() -> None:
    with pytest.raises(Unsupported, match="第三期"):
        parse(b"%PDF-1.4", "application/pdf", "a.pdf")
    with pytest.raises(Unsupported):
        parse(bytes(range(256)) * 4, "application/octet-stream", "a.bin")


# ---------- 切分 ----------


def test_chunk_is_deterministic_and_tracks_headings() -> None:
    a = chunk("h1", DOC, "ops.md")
    b = chunk("h1", DOC, "ops.md")
    assert [c.id for c in a] == [c.id for c in b]
    assert any("部署 / 回滚" in c.heading for c in a)
    assert any(c.heading.endswith("监控") for c in a)
    for c in a:
        assert DOC[c.start : c.end].strip() == c.text
    assert [c.id for c in chunk("h2", DOC)] != [c.id for c in a]  # id 随文档走


def test_chunk_splits_long_blocks() -> None:
    text = "。".join(["这是一句比较长的话用来凑长度" * 3] * 60)
    cs = chunk("h", text)
    assert len(cs) > 1 and all(c.end - c.start <= MAX for c in cs)


# ---------- 向量与索引 ----------


def test_hash_embedder_is_normalised_and_similar() -> None:
    e = HashEmbedder()
    a, b, c = e.embed(["回滚数据库迁移", "数据库迁移的回滚", "告警阈值"])
    assert abs(cosine(a, a) - 1) < 1e-6
    assert cosine(a, b) > cosine(a, c)


def test_make_embedder_falls_back_with_note() -> None:
    assert make_embedder(None)[1] == ""
    emb, note = make_embedder({"kind": "onnx"})
    assert emb.id == "hash-512-v1" and "第三期" in note
    with pytest.raises(ValueError):
        make_embedder({"kind": "nope"})


def test_terms_mix_latin_and_cjk() -> None:
    assert terms("Alerts.yaml 回滚失败") == ["alerts", "yaml", "回滚", "滚失", "失败"]


def test_index_search_respects_live_set(tmp_path: Path) -> None:
    idx, e = Index(tmp_path / "i.sqlite"), HashEmbedder()
    idx.add("s_aaaaaa", 1, "ops.md", chunk("h1", DOC, "ops.md"), e)
    idx.add("s_bbbbbb", 1, "other.md", chunk("h2", "回滚的另一份说明。", "other.md"), e)
    hits, how = idx.search("回滚", [("s_aaaaaa", 1)], e)
    assert how == "lexical+vector" and hits and {h["source"] for h in hits} == {"s_aaaaaa"}
    assert "回滚" in hits[0]["text"] and "lex" in hits[0]["via"]
    assert idx.search("回滚", [], e) == ([], "none")
    idx.drop("s_aaaaaa")
    assert idx.count("s_aaaaaa", 1) == 0
    idx.close()


# ---------- reducer ----------


def test_reducer_writers_and_stage_guard() -> None:
    st = rd.empty()
    f = {"hash": "0" * 64, "size": 1, "media_type": "", "name": "a.md"}
    put = {"source": {"id": "s_abcdef", "name": "A", "origin": "file", "scope": "all"}, "file": f}
    assert isinstance(rd.validate(st, {"kind": "graph"}, "source_put", put), rd.Reject)
    ok = rd.validate(st, {"kind": "human"}, "source_put", put)
    assert isinstance(ok, rd.Ok)
    st = rd.apply(st, {"seq": 1, "ts": 1, "kind": "source_put", "body": ok.body})
    bad = {"source": "s_abcdef", "revision": 1, "stage": "chunk", "info": {}}
    r = rd.validate(st, {"kind": "graph"}, "stage_done", bad)
    assert isinstance(r, rd.Reject) and r.code == "conflict"
    r = rd.validate(st, {"kind": "graph"}, "stage_done", {**bad, "stage": "index"})
    assert isinstance(r, rd.Reject) and r.code == "schema_error"
    r = rd.validate(st, {"kind": "human"}, "revision_put", {"source": "s_abcdef", "file": f})
    assert isinstance(r, rd.Reject) and r.code == "conflict"  # 上一个版本还在导入


# ---------- 服务 ----------


def test_import_flow_and_search(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, _ = env
    sid = sk.put_source("运维手册", "file", "all", fileof(blobs, DOC.encode(), "ops.md"))
    assert sk.jobs()[0]["stage"] == "parse"
    assert sk.search("回滚")["hits"] == []  # 还没建好
    sk.tick()
    assert sk.jobs()[0]["stage"] == "chunk"
    run(sk)
    assert sk.jobs() == []
    src = sk.sources()[0]
    assert src["id"] == sid and src["live_revision"] == 1 and src["chunks"] > 0 and not src["importing"]
    res = sk.search("回滚失败")
    assert res["hits"][0]["source_name"] == "运维手册" and res["embedder"] == "hash-512-v1"
    c = sk.chunk(res["hits"][0]["id"])
    assert c is not None and c["newer_revision"] is False and "回滚" in c["text"]


def test_scope_pick_only_when_named(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, _ = env
    sid = sk.put_source("私房", "text", "pick", fileof(blobs, "回滚要先停写入。".encode(), "note.txt"))
    run(sk)
    assert sk.search("回滚")["hits"] == []
    assert sk.search("回滚", pick=[sid])["hits"]


def test_failure_retry_and_cancel(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, _ = env
    sid = sk.put_source("坏的", "file", "all", fileof(blobs, b"%PDF-1.4", "a.pdf"))
    sk.tick()
    job = sk.jobs()[0]
    assert job["failed"]["stage"] == "parse" and "第三期" in job["failed"]["reason"]
    assert sk.tick() == []  # 失败的停住，不反复跑
    sk.act("job_retry", {"source": sid, "revision": 1})
    sk.tick()
    assert sk.jobs()[0]["failed"] is not None  # 重试后还是失败，又停住
    with pytest.raises(Rejected) as ei:
        sk.act("job_retry", {"source": sid, "revision": 9})
    assert ei.value.code == "unknown_ref"
    sk.act("job_cancel", {"source": sid, "revision": 1})
    assert sk.jobs() == [] and sk.sources()[0]["live_revision"] is None
    with pytest.raises(Rejected):
        sk.act("stage_done", {"source": sid})


def test_empty_text_fails_clearly(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, _ = env
    sk.put_source("空", "text", "all", fileof(blobs, b"   \n", "e.txt"))
    sk.tick()
    assert "空的" in sk.jobs()[0]["failed"]["reason"]


def test_new_revision_keeps_old_one_serving(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, _ = env
    sid = sk.put_source("手册", "file", "all", fileof(blobs, "旧版：回滚靠手工。".encode(), "m.md"))
    run(sk)
    old = sk.search("回滚")["hits"][0]["id"]
    assert sk.put_revision(sid, fileof(blobs, "新版：回滚靠脚本，一键回滚。".encode(), "m.md")) == 2
    sk.tick()  # 新版本在解析，旧的照常检索
    hits = sk.search("回滚")["hits"]
    assert hits and all(h["revision"] == 1 for h in hits)
    run(sk)
    hits = sk.search("回滚")["hits"]
    assert hits and all(h["revision"] == 2 for h in hits)
    assert sk.chunk(old) is not None and sk.chunk(old)["newer_revision"] is True  # type: ignore[index]


def test_disable_delete_restore_purge(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, clock = env
    sid = sk.put_source("手册", "file", "all", fileof(blobs, "回滚靠脚本。".encode(), "m.md"))
    run(sk)
    sk.act("source_set", {"source": sid, "disabled": True})
    assert sk.search("回滚")["hits"] == []
    sk.act("source_set", {"source": sid, "disabled": False})
    assert sk.search("回滚")["hits"]
    sk.act("source_curate", {"source": sid, "action": "delete"})
    assert sk.search("回滚")["hits"] == [] and sk.sources()[0]["deleted_at"] is not None
    with pytest.raises(Rejected) as ei:
        sk.put_revision(sid, fileof(blobs, b"x", "m.md"))
    assert ei.value.code == "conflict"
    sk.act("source_curate", {"source": sid, "action": "restore"})
    assert sk.search("回滚")["hits"]
    sk.act("source_curate", {"source": sid, "action": "delete"})
    clock.t = sk.state["sources"][sid]["deleted_at"] + rd.TRASH_MS - 1  # 日志时间戳单调，可能比钟略前
    assert sk.tick() == []
    clock.t += 1
    assert sk.tick() == [f"{sid}:purged"]
    assert sk.sources() == [] and sk.index.count(sid, 1) == 0
    with pytest.raises(Rejected):
        sk.act("source_curate", {"source": sid, "action": "restore"})


def test_restart_resumes_from_log_and_rebuild(tmp_path: Path) -> None:
    blobs, clock = BlobStore(tmp_path / "blobs"), Clock()
    sk = Shuku(tmp_path / "shuku", blobs, clock=clock)
    sid = sk.put_source("手册", "file", "all", fileof(blobs, DOC.encode(), "ops.md"))
    sk.tick()  # 解析完就“关掉”
    sk.close()
    sk = Shuku(tmp_path / "shuku", blobs, clock=clock)
    assert sk.jobs()[0]["stage"] == "chunk"
    run(sk)
    want = [h["id"] for h in sk.search("告警阈值")["hits"]]
    sk.close()
    (tmp_path / "shuku" / "shuku-index.sqlite").unlink()
    for p in (tmp_path / "shuku").glob("shuku-index.sqlite-*"):
        p.unlink()
    sk = Shuku(tmp_path / "shuku", blobs, clock=clock)
    assert sk.search("告警阈值")["hits"] == []
    assert sk.rebuild() == sk.sources()[0]["chunks"]
    assert [h["id"] for h in sk.search("告警阈值")["hits"]] == want  # 段落 id 不因重建变
    assert sk.sources()[0]["id"] == sid
    sk.close()


def test_search_k_is_clamped(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, _ = env
    body = "\n\n".join(f"第{i}段讲回滚的第{i}种情况。" + "填充" * 300 for i in range(30))
    sk.put_source("长", "file", "all", fileof(blobs, body.encode(), "long.md"))
    run(sk)
    assert len(sk.search("回滚", k=999)["hits"]) == 20
    assert len(sk.search("回滚", k=0)["hits"]) == 1


def test_text_blob_is_stored_by_hash(env: tuple[Shuku, BlobStore, Clock]) -> None:
    sk, blobs, _ = env
    sid = sk.put_source("手册", "text", "all", fileof(blobs, "回滚。".encode(), "n.txt"))
    sk.tick()
    rev = sk.state["sources"][sid]["revisions"][0]
    assert rev["info"]["text"] == hashlib.sha256("回滚。".encode()).hexdigest()
