"""SQLite 事件日志（规格 §3.1.1：M0 用 SQLite 单文件，WAL；单写者）。

只追加，不更新、不删除。seq 全局单调；哈希链按题独立。
同一题内同一 idem_key 的再次追加返回首次的事件，不写新行（§3.1.2 冲突表）。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

from .envelope import GENESIS, seal, verify_chain
from .state import Actor, Body, Event

Append = Callable[[str, str, Body, Actor, int, str], Event]  # (pid, kind, body, actor, ts, idem_key) → 事件

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq        INTEGER PRIMARY KEY,
  problem_id TEXT    NOT NULL,
  idem_key   TEXT    NOT NULL,
  hash       TEXT    NOT NULL UNIQUE,
  doc        TEXT    NOT NULL,
  UNIQUE (problem_id, idem_key)
);
CREATE TABLE IF NOT EXISTS proposals (
  problem_id TEXT NOT NULL,
  idem_key   TEXT NOT NULL,
  results    TEXT NOT NULL,
  PRIMARY KEY (problem_id, idem_key)
);
CREATE INDEX IF NOT EXISTS events_by_problem ON events (problem_id, seq);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


class BatchRejected(Exception):
    """build 以此表示整批被拒：本批事件撤回，batch_results 照样记下，重放返回同一结果。"""

    def __init__(self, batch_results: Body) -> None:
        super().__init__("batch rejected")
        self.batch_results = batch_results


class EventLog:
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def append(
        self, *, problem_id: str, actor: Actor, kind: str, body: Body, idem_key: str, ts: int
    ) -> tuple[Event, bool]:
        """追加一条事件，返回 (事件, 是否新写入)。整个过程在一个 IMMEDIATE 事务里，单写者。"""
        db = self._db
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT doc FROM events WHERE problem_id=? AND idem_key=?", (problem_id, idem_key)
            ).fetchone()
            if row:
                db.execute("COMMIT")
                return cast(Event, json.loads(row[0])), False
            head = db.execute(
                "SELECT hash FROM events WHERE problem_id=? ORDER BY seq DESC LIMIT 1", (problem_id,)
            ).fetchone()
            seq = (db.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]) + 1
            ev = seal(
                seq=seq,
                problem_id=problem_id,
                ts=ts,
                actor=actor,
                kind=kind,
                body=body,
                idem_key=idem_key,
                prev_hash=head[0] if head else GENESIS,
            )
            db.execute(
                "INSERT INTO events (seq, problem_id, idem_key, hash, doc) VALUES (?,?,?,?,?)",
                (seq, problem_id, idem_key, ev["hash"], json.dumps(ev, ensure_ascii=False)),
            )
            db.execute("COMMIT")
            return ev, True
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def commit_batch(self, problem_id: str, idem_key: str, build: Callable[[Append], Body]) -> tuple[Body, bool]:
        """整批原子提交：在一个 IMMEDIATE 事务里调用 build(append) 生成事件与结果，连同结果一起落盘。

        build 收到一个 append(kind, body, actor, ts, idem) 函数，返回结果列表（可 JSON 化）。
        同一 (problem_id, idem_key) 已提交过时不调用 build，直接返回首次结果（恰好一次）。
        build 抛出 BatchRejected 表示整批被拒：本批事件撤回，结果照样记下，重放返回同一结果。
        其它异常整体回滚，日志与结果表都不留痕。
        """
        db = self._db
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT results FROM proposals WHERE problem_id=? AND idem_key=?", (problem_id, idem_key)
            ).fetchone()
            if row:
                db.execute("COMMIT")
                return cast(Body, json.loads(row[0])), False

            def append(pid: str, kind: str, body: Body, actor: Actor, ts: int, idem: str) -> Event:
                head = db.execute(
                    "SELECT hash FROM events WHERE problem_id=? ORDER BY seq DESC LIMIT 1", (pid,)
                ).fetchone()
                seq = db.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0] + 1
                ev = seal(
                    seq=seq,
                    problem_id=pid,
                    ts=ts,
                    actor=actor,
                    kind=kind,
                    body=body,
                    idem_key=idem,
                    prev_hash=head[0] if head else GENESIS,
                )
                db.execute(
                    "INSERT INTO events (seq, problem_id, idem_key, hash, doc) VALUES (?,?,?,?,?)",
                    (seq, pid, idem, ev["hash"], json.dumps(ev, ensure_ascii=False)),
                )
                return ev

            db.execute("SAVEPOINT batch")
            try:
                results = build(append)
            except BatchRejected as e:  # 整批被拒：撤回本批事件，只记下结果
                db.execute("ROLLBACK TO batch")
                results = e.batch_results
            db.execute("RELEASE batch")
            db.execute(
                "INSERT INTO proposals (problem_id, idem_key, results) VALUES (?,?,?)",
                (problem_id, idem_key, json.dumps(results, ensure_ascii=False)),
            )
            db.execute("COMMIT")
            return results, True
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def events(self, problem_id: str | None = None, after: int = 0) -> Iterator[Event]:
        if problem_id is None:
            cur = self._db.execute("SELECT doc FROM events WHERE seq>? ORDER BY seq", (after,))
        else:
            cur = self._db.execute(
                "SELECT doc FROM events WHERE problem_id=? AND seq>? ORDER BY seq", (problem_id, after)
            )
        for (doc,) in cur:
            yield cast(Event, json.loads(doc))

    def problems(self) -> list[str]:
        return [r[0] for r in self._db.execute("SELECT DISTINCT problem_id FROM events ORDER BY problem_id")]

    def verify(self, problem_id: str) -> None:
        verify_chain(list(self.events(problem_id)))
