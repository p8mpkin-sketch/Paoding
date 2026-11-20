"""本地索引（五阶段的第四步）：SQLite 里的段落表、FTS5 词法索引、向量表。可以整个删掉重建，事实在书库日志里。

中文没有空格：写进 FTS 的是“分词串”（拉丁词原样、汉字按二元），查询用同一个函数切，FTS5 的 unicode61 分词器
再按空格切开。检索是混合的：词法（bm25）与向量各取前 POOL，按倒数排名融合（RRF，k=60）。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from array import array
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .chunk import Chunk
from .embed import Embedder, cosine

POOL, RRF_K = 50, 60


def terms(text: str) -> list[str]:
    t = text.lower()
    out = re.findall(r"[a-z0-9_]{2,}", t)
    for run in re.findall(r"[㐀-鿿]+", t):
        out += [run] if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)]
    return out


class Index:
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        self._db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS chunks(id TEXT, source TEXT, revision INTEGER, doc TEXT, heading TEXT,
              start INTEGER, end_ INTEGER, text TEXT, PRIMARY KEY(id, source, revision));
            CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(id UNINDEXED, source UNINDEXED, revision UNINDEXED, body);
            CREATE TABLE IF NOT EXISTS vecs(id TEXT, source TEXT, revision INTEGER, model TEXT, vec BLOB,
              PRIMARY KEY(id, source, revision, model));
            """
        )

    def close(self) -> None:
        self._db.close()

    def add(self, source: str, revision: int, doc: str, chunks: list[Chunk], emb: Embedder) -> None:
        vecs = emb.embed([f"{c.heading}\n{c.text}" for c in chunks]) if chunks else []
        with self._lock:
            db = self._db
            db.execute("BEGIN")
            try:
                for c, v in zip(chunks, vecs, strict=True):
                    db.execute(
                        "INSERT OR REPLACE INTO chunks VALUES(?,?,?,?,?,?,?,?)",
                        (c.id, source, revision, doc, c.heading, c.start, c.end, c.text),
                    )
                    db.execute(
                        "INSERT INTO fts VALUES(?,?,?,?)",
                        (c.id, source, revision, " ".join(terms(f"{c.heading} {c.text}"))),
                    )
                    db.execute(
                        "INSERT OR REPLACE INTO vecs VALUES(?,?,?,?,?)",
                        (c.id, source, revision, emb.id, array("f", v).tobytes()),
                    )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def drop(self, source: str, revision: int | None = None) -> None:
        """删掉一份资料（或它的一个版本）的全部段落；取消导入、到期清理、换版本时用。"""
        cond, args = ("source=?", (source,)) if revision is None else ("source=? AND revision=?", (source, revision))
        with self._lock:
            for t in ("chunks", "fts", "vecs"):
                self._db.execute(f"DELETE FROM {t} WHERE {cond}", args)  # noqa: S608  表名是常量

    def count(self, source: str, revision: int) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM chunks WHERE source=? AND revision=?", (source, revision)
            ).fetchone()
        return int(row[0])

    def chunk(self, cid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, source, revision, doc, heading, start, end_, text FROM chunks WHERE id=? "
                "ORDER BY revision DESC LIMIT 1",
                (cid,),
            ).fetchone()
        if row is None:
            return None
        keys = ("id", "source", "revision", "doc", "heading", "start", "end", "text")
        return dict(zip(keys, row, strict=True))

    def search(
        self, query: str, live: Iterable[tuple[str, int]], emb: Embedder, k: int = 8
    ) -> tuple[list[dict[str, Any]], str]:
        """返回 (按融合分排序的段落, 用了哪些检索)。live：可检索的 (资料, 版本)。"""
        allowed = set(live)
        if not allowed or not query.strip():
            return [], "none"
        ranks: dict[tuple[str, str, int], dict[str, int]] = {}
        qt = terms(query)
        with self._lock:
            if qt:
                match = " OR ".join('"' + t.replace('"', "") + '"' for t in dict.fromkeys(qt))
                rows = self._db.execute(
                    "SELECT id, source, revision FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
                    (match, POOL * 4),
                ).fetchall()
                lex = [(str(i), str(s), int(r)) for i, s, r in rows if (s, int(r)) in allowed][:POOL]
                for n, key in enumerate(lex):
                    ranks.setdefault(key, {})["lex"] = n
            qv = emb.embed([query])[0]
            scored = []
            rows = self._db.execute("SELECT id, source, revision, vec FROM vecs WHERE model=?", (emb.id,)).fetchall()
            for i, s, r, blob in rows:
                if (s, int(r)) not in allowed:
                    continue
                v = array("f")
                v.frombytes(blob)
                scored.append((cosine(qv, list(v)), (str(i), str(s), int(r))))
        scored.sort(key=lambda x: -x[0])
        for n, (sim, key) in enumerate(scored[:POOL]):
            if sim > 0.05:
                ranks.setdefault(key, {})["vec"] = n
        fused = sorted(ranks.items(), key=lambda kv: -sum(1 / (RRF_K + 1 + n) for n in kv[1].values()))
        out = []
        for (cid, src, rev), how in fused[:k]:
            c = self.chunk_at(cid, src, rev)
            if c:
                score = sum(1 / (RRF_K + 1 + n) for n in how.values())
                out.append({**c, "score": round(score * (RRF_K + 1) / 2, 3), "via": sorted(how)})
        return out, "lexical+vector" if scored else "lexical"

    def chunk_at(self, cid: str, source: str, revision: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, source, revision, doc, heading, start, end_, text FROM chunks "
                "WHERE id=? AND source=? AND revision=?",
                (cid, source, revision),
            ).fetchone()
        if row is None:
            return None
        keys = ("id", "source", "revision", "doc", "heading", "start", "end", "text")
        return dict(zip(keys, row, strict=True))
