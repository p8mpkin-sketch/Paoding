"""书库服务：书库日志的唯一写入者，加一份可重建的本地索引。

- 写：人的导入、重试、取消、停用、软删、恢复（带人的身份）；书库自己的阶段推进（tick）。
- 状态由日志重放得出；索引丢了可以按日志重建（rebuild）。
- 读：资料列表、导入作业、检索、单段原文。检索只在给定的可见范围里做。

导入一次推进一步（tick 每次每个版本至多做一步），关掉页面、进程重启都从日志里记的那一步接着做。
原文与解析出的纯文本都存进 Blob（按哈希），日志里只记哈希。
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from paoding_graph.contract import BlobError, EventLog, replay

from . import creds
from . import reducer as rd
from .chunk import CHUNKER, chunk
from .embed import make_embedder
from .index import Index
from .parse import Unsupported, parse

SERVICE: dict[str, str] = {"kind": "graph", "id": "shuku"}
SEARCH_K_MAX = 20


class Blobs(Protocol):
    def put(self, data: bytes) -> str: ...

    def get(self, h: str, start: int = 0, end: int | None = None) -> bytes: ...


class Rejected(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


@dataclass
class ShukuConfig:
    embedder: dict[str, Any] = field(default_factory=lambda: {"kind": "hash"})


class Shuku:
    def __init__(
        self,
        home: str | Path,
        blobs: Blobs,
        cfg: ShukuConfig | None = None,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ):
        home = Path(home)
        home.mkdir(parents=True, exist_ok=True)
        self.cfg = cfg or ShukuConfig()
        self.blobs, self._clock = blobs, clock
        self.log = EventLog(home / "shuku.sqlite")
        self.index = Index(home / "shuku-index.sqlite")
        self.embedder, self.embedder_note = make_embedder(self.cfg.embedder)
        self.state: dict[str, Any] = replay(self.log.events(), rd.apply, rd.empty())
        self._lock = threading.RLock()

    def close(self) -> None:
        self.log.close()
        self.index.close()

    # ---------- 写 ----------

    def _commit(self, idem: str, actor: Mapping[str, Any], kind: str, body: Mapping[str, Any]) -> int:
        with self._lock:
            r = rd.validate(self.state, actor, kind, body)
            if isinstance(r, rd.Reject):
                raise Rejected(r.code, r.detail)
            st = self.state
            ok = r

            def build(append: Any) -> dict[str, Any]:
                ts = max(self._clock(), st["now"] + 1)
                ev = append(rd.LOG, kind, ok.body, dict(actor), ts, idem)
                staged["state"] = rd.apply(st, ev)
                return {"ok": True, "seq": ev["seq"]}

            staged: dict[str, Any] = {}
            out, fresh = self.log.commit_batch(rd.LOG, idem, build)
            if fresh:
                self.state = staged["state"]
            return int(out["seq"])

    def put_source(self, name: str, origin: str, scope: str, file: Mapping[str, Any], who: str = "human") -> str:
        sid = "s_" + secrets.token_hex(6)
        body = {"source": {"id": sid, "name": name, "origin": origin, "scope": scope}, "file": dict(file)}
        self._commit(f"put:{sid}", {"kind": "human", "id": who}, "source_put", body)
        return sid

    def put_revision(self, sid: str, file: Mapping[str, Any], who: str = "human") -> int:
        n = len(self.state["sources"].get(sid, {}).get("revisions", [])) + 1
        body = {"source": sid, "file": dict(file)}
        self._commit(f"rev:{sid}:{n}", {"kind": "human", "id": who}, "revision_put", body)
        return n

    def act(self, kind: str, body: Mapping[str, Any], who: str = "human") -> int:
        """人的其余操作：job_retry、job_cancel、source_set、source_curate。"""
        if kind not in ("job_retry", "job_cancel", "source_set", "source_curate"):
            raise Rejected("forbidden_op", f"人不能直接提交 {kind}")
        out = self._commit(f"{kind}:{secrets.token_hex(8)}", {"kind": "human", "id": who}, kind, body)
        if kind == "job_cancel":
            self.index.drop(str(body["source"]), int(body["revision"]))
        return out

    # ---------- 推进 ----------

    def tick(self) -> list[str]:
        """每个在导入的版本推进一步；再把回收站里到期的资料清掉。返回本轮做了什么（给日志看）。"""
        done = []
        for sid, src in sorted(self.state["sources"].items()):
            for rev in src["revisions"]:
                if rev["stage"] in rd.STAGES and not rev.get("failed"):
                    done.append(f"{sid}#{rev['n']}:{rev['stage']}")
                    self._step(sid, rev)
            if src.get("deleted_at") is not None and not src.get("purged"):
                if self._clock() - int(src["deleted_at"]) >= rd.TRASH_MS:
                    self.index.drop(sid)
                    self._commit(f"purge:{sid}", SERVICE, "source_purged", {"source": sid})
                    done.append(f"{sid}:purged")
        return done

    def _fail(self, sid: str, rev: Mapping[str, Any], reason: str, code: str = "error", **extra: Any) -> None:
        body = {"source": sid, "revision": rev["n"], "stage": rev["stage"], "reason": reason, "code": code, **extra}
        self._commit(f"fail:{sid}:{rev['n']}:{rev['stage']}:{len(self.log_tail(sid))}", SERVICE, "stage_failed", body)

    def log_tail(self, sid: str) -> list[Any]:
        return [e for e in self.log.events(rd.LOG) if e["body"].get("source") == sid]

    def _step(self, sid: str, rev: Mapping[str, Any]) -> None:
        n, stage, f = rev["n"], rev["stage"], rev["file"]
        idem = f"{stage}:{sid}:{n}:{rev['info'].get('retry', 0)}:{len(self.log_tail(sid))}"
        try:
            if stage == "parse":
                p = parse(self.blobs.get(f["hash"]), f["media_type"], f["name"])
                if not p.text.strip():
                    return self._fail(sid, rev, "解析出来是空的：这份文件里没有文字", "empty")
                text, warnings = p.text, list(p.warnings)
                hits = creds.found(text)
                if hits and not rev.get("mask"):
                    # 原因里只写处数，不写串本身：日志、页面、会话都看不到它
                    why = f"发现 {len(hits)} 处像密钥或口令的串。可以遮盖后导入，或取消这次导入"
                    return self._fail(sid, rev, why, "secrets", count=len(hits))
                if hits:
                    text = creds.mask(text, hits)
                    warnings.append(f"已遮盖 {len(hits)} 处像密钥或口令的串")
                th = self.blobs.put(text.encode("utf-8"))
                info = {"text": th, "chars": len(text), "kind": p.kind, "warnings": warnings}
                self._commit(idem, SERVICE, "stage_done", {"source": sid, "revision": n, "stage": stage, "info": info})
            elif stage == "chunk":
                text = self.blobs.get(rev["info"]["text"]).decode("utf-8")
                cs = chunk(rev["info"]["text"], text, f["name"])
                info = {"chunks": len(cs), "chunker": CHUNKER}
                self._commit(idem, SERVICE, "stage_done", {"source": sid, "revision": n, "stage": stage, "info": info})
            else:
                text = self.blobs.get(rev["info"]["text"]).decode("utf-8")
                cs = chunk(rev["info"]["text"], text, f["name"])
                self.index.drop(sid, n)  # 重来时先清掉上次建到一半的
                self.index.add(sid, n, f["name"], cs, self.embedder)
                body = {"source": sid, "revision": n, "chunks": len(cs), "embedder": self.embedder.id}
                self._commit(idem, SERVICE, "revision_ready", body)
        except Unsupported as e:
            self._fail(sid, rev, str(e), "unsupported")
        except (BlobError, OSError, KeyError, UnicodeDecodeError) as e:
            self._fail(sid, rev, f"{type(e).__name__}: {e}")

    def rebuild(self) -> int:
        """索引丢了或换了向量模型：按日志把每个可检索的版本重建一遍。返回段落数。"""
        total = 0
        for sid, src in self.state["sources"].items():
            n = rd.live_revision(src)
            if n is None:
                continue
            rev = next(r for r in src["revisions"] if r["n"] == n)
            text = self.blobs.get(rev["info"]["text"]).decode("utf-8")
            cs = chunk(rev["info"]["text"], text, rev["file"]["name"])
            self.index.drop(sid, n)
            self.index.add(sid, n, rev["file"]["name"], cs, self.embedder)
            total += len(cs)
        return total

    # ---------- 读 ----------

    def live(self, pick: list[str] | None = None) -> list[tuple[str, int]]:
        """可检索的 (资料, 版本)。pick 为 None：所有 scope=all 的资料；给了：只这几份（不论 scope）。"""
        out = []
        for sid, src in sorted(self.state["sources"].items()):
            n = rd.live_revision(src)
            if n is None:
                continue
            if (pick is None and src["scope"] == "all") or (pick is not None and sid in pick):
                out.append((sid, n))
        return out

    def search(self, query: str, k: int = 8, pick: list[str] | None = None) -> dict[str, Any]:
        k = max(1, min(int(k), SEARCH_K_MAX))
        hits, how = self.index.search(query, self.live(pick), self.embedder, k)
        names = {sid: s["name"] for sid, s in self.state["sources"].items()}
        return {
            "hits": [{**h, "source_name": names.get(h["source"], h["source"])} for h in hits],
            "via": how,
            "embedder": self.embedder.id,
            "note": self.embedder_note,
        }

    def chunk(self, cid: str) -> dict[str, Any] | None:
        c = self.index.chunk(cid)
        if c is None:
            return None
        src = self.state["sources"].get(c["source"], {})
        newer = bool(src) and rd.latest(src)["n"] > c["revision"] and rd.latest(src)["stage"] == "ready"
        return {**c, "source_name": src.get("name", c["source"]), "newer_revision": newer}

    def sources(self) -> list[dict[str, Any]]:
        out = []
        for sid, src in sorted(self.state["sources"].items(), key=lambda kv: -int(kv[1]["created"])):
            if src.get("purged"):
                continue
            last = rd.latest(src)
            live = rd.live_revision(src)
            cur = next((r for r in src["revisions"] if r["n"] == live), None)
            out.append(
                {
                    "id": sid,
                    "name": src["name"],
                    "origin": src["origin"],
                    "scope": src["scope"],
                    "disabled": src["disabled"],
                    "deleted_at": src["deleted_at"],
                    "created": src["created"],
                    "revisions": len(src["revisions"]),
                    "live_revision": live,
                    "chunks": cur["chunks"] if cur else 0,
                    "size": (cur or last)["file"]["size"],
                    "updated": (cur or last)["ts"],
                    "importing": last["stage"] in rd.STAGES,
                    "failed": last.get("failed"),
                }
            )
        return out

    def jobs(self) -> list[dict[str, Any]]:
        """正在导入（含失败待处理）的版本，带五阶段进度。"""
        out = []
        for sid, src in sorted(self.state["sources"].items()):
            if src.get("purged"):
                continue
            for r in src["revisions"]:
                if r["stage"] not in rd.STAGES:
                    continue
                out.append(
                    {
                        "source": sid,
                        "name": src["name"],
                        "revision": r["n"],
                        "file": r["file"],
                        "stage": r["stage"],
                        "failed": r.get("failed"),
                        "warnings": r["info"].get("warnings", []),
                        "chunks": r["info"].get("chunks"),
                        "started": r["ts"],
                    }
                )
        return out
