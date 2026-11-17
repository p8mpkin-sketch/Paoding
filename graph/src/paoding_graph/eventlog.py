"""SQLite 事件日志（规格 §3.1.1：M0 用 SQLite 单文件，WAL；单写者）。

只追加，不更新、不删除。seq 全局单调；哈希链按题独立。
同一题内同一 idem_key 的再次追加返回首次的事件，不写新行（§3.1.2 冲突表）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from .envelope import GENESIS, seal, verify_chain

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq        INTEGER PRIMARY KEY,
  problem_id TEXT    NOT NULL,
  idem_key   TEXT    NOT NULL,
  hash       TEXT    NOT NULL UNIQUE,
  doc        TEXT    NOT NULL,
  UNIQUE (problem_id, idem_key)
);
CREATE INDEX IF NOT EXISTS events_by_problem ON events (problem_id, seq);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


class EventLog:
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def append(self, *, problem_id: str, actor: dict, kind: str, body: dict, idem_key: str,
               ts: int) -> tuple[dict[str, Any], bool]:
        """追加一条事件，返回 (事件, 是否新写入)。整个过程在一个 IMMEDIATE 事务里，单写者。"""
        db = self._db
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT doc FROM events WHERE problem_id=? AND idem_key=?",
                             (problem_id, idem_key)).fetchone()
            if row:
                db.execute("COMMIT")
                return json.loads(row[0]), False
            head = db.execute("SELECT hash FROM events WHERE problem_id=? ORDER BY seq DESC LIMIT 1",
                              (problem_id,)).fetchone()
            seq = (db.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]) + 1
            ev = seal(seq=seq, problem_id=problem_id, ts=ts, actor=actor, kind=kind, body=body,
                      idem_key=idem_key, prev_hash=head[0] if head else GENESIS)
            db.execute("INSERT INTO events (seq, problem_id, idem_key, hash, doc) VALUES (?,?,?,?,?)",
                       (seq, problem_id, idem_key, ev["hash"], json.dumps(ev, ensure_ascii=False)))
            db.execute("COMMIT")
            return ev, True
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def events(self, problem_id: str | None = None, after: int = 0) -> Iterator[dict[str, Any]]:
        if problem_id is None:
            cur = self._db.execute("SELECT doc FROM events WHERE seq>? ORDER BY seq", (after,))
        else:
            cur = self._db.execute("SELECT doc FROM events WHERE problem_id=? AND seq>? ORDER BY seq",
                                   (problem_id, after))
        for (doc,) in cur:
            yield json.loads(doc)

    def problems(self) -> list[str]:
        return [r[0] for r in self._db.execute("SELECT DISTINCT problem_id FROM events ORDER BY problem_id")]

    def verify(self, problem_id: str) -> None:
        verify_chain(list(self.events(problem_id)))
