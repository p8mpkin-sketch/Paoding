"""书库日志的 reducer（与题日志、通鉴同一种基质）。validate 与 apply 都是纯函数。

事件（problem_id 固定为 LOG）：

    source_put     人    {source: {id, name, origin, scope}, file}   新资料，版本 1，进入解析
    revision_put   人    {source, file}                               旧资料的新版本，进入解析
    stage_done     书库  {source, revision, stage, info}              解析、切分做完一步
    revision_ready 书库  {source, revision, chunks, embedder}         建好索引，可检索
    stage_failed   书库  {source, revision, stage, reason}            停在这一步，等人重试或取消
    job_retry      人    {source, revision}                           从失败的那一步重来
    job_cancel     人    {source, revision}                           取消导入，建到一半的索引清掉
    source_set     人    {source, disabled}                           停用 / 启用（停用的不参与检索）
    source_curate  人    {source, action: delete|restore}             软删进回收站 30 天 / 恢复
    source_purged  书库  {source}                                     到期清掉索引；日志与已登记的引用不动

file = {hash, size, media_type, name}。scope：all（所有任务可见）| pick（只在任务指定时）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

LOG = "shuku"
STAGES = ("parse", "chunk", "index")  # 上传在 source_put / revision_put 时已完成；可用 = revision_ready
NEXT = {"parse": "chunk", "chunk": "index"}
SCOPES = ("all", "pick")
ORIGINS = ("file", "folder", "url", "text")
TRASH_MS = 30 * 86_400_000
ID_RE = re.compile(r"s_[a-z0-9]{6,32}")

WRITERS = {
    "source_put": "human",
    "revision_put": "human",
    "stage_done": "graph",
    "revision_ready": "graph",
    "stage_failed": "graph",
    "job_retry": "human",
    "job_cancel": "human",
    "source_set": "human",
    "source_curate": "human",
    "source_purged": "graph",
}

SState = dict[str, Any]


@dataclass(frozen=True)
class Ok:
    body: dict[str, Any]


@dataclass(frozen=True)
class Reject:
    code: str
    detail: str = ""


def empty() -> SState:
    return {"seq": 0, "now": 0, "sources": {}}


def latest(src: Mapping[str, Any]) -> Mapping[str, Any]:
    return src["revisions"][-1]  # type: ignore[no-any-return]


def live_revision(src: Mapping[str, Any]) -> int | None:
    """可检索的版本：最新一个建好索引的版本（新版本还在导入时，旧版本照常服务）。"""
    if src.get("disabled") or src.get("deleted_at") is not None or src.get("purged"):
        return None
    ready = [r["n"] for r in src["revisions"] if r["stage"] == "ready"]
    return ready[-1] if ready else None


def _file(f: object) -> dict[str, Any] | Reject:
    if (
        not isinstance(f, dict)
        or not isinstance(f.get("hash"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", f["hash"])
        or not isinstance(f.get("size"), int)
        or f["size"] < 0
    ):
        return Reject("schema_error", "file 是 {hash, size, media_type, name}")
    return {
        "hash": f["hash"],
        "size": f["size"],
        "media_type": str(f.get("media_type") or ""),
        "name": str(f.get("name") or "")[:300],
    }


def _rev(st: Mapping[str, Any], body: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | Reject:
    src = st["sources"].get(body.get("source"))
    if src is None:
        return Reject("unknown_ref", "资料不存在")
    n = body.get("revision")
    revs = [r for r in src["revisions"] if r["n"] == n]
    if not revs:
        return Reject("unknown_ref", "没有这个版本")
    return src, revs[0]


def validate(st: Mapping[str, Any], actor: Mapping[str, Any], kind: str, body: Mapping[str, Any]) -> Ok | Reject:
    if kind not in WRITERS:
        return Reject("schema_error", f"未知操作 {kind}")
    if actor.get("kind") != WRITERS[kind]:
        return Reject("forbidden_op", f"{actor.get('kind')} 不能提交 {kind}")
    if kind == "source_put":
        s = body.get("source")
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not ID_RE.fullmatch(s["id"]):
            return Reject("schema_error", "source.id 取 s_ 加 6 到 32 位小写字母数字")
        if s["id"] in st["sources"]:
            return Reject("schema_error", "资料 id 已存在")
        name = s.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            return Reject("schema_error", "资料要有名字（至多 200 字）")
        if s.get("origin") not in ORIGINS or s.get("scope") not in SCOPES:
            return Reject("schema_error", f"origin 取 {ORIGINS}，scope 取 {SCOPES}")
        f = _file(body.get("file"))
        if isinstance(f, Reject):
            return f
        return Ok({"source": {k: s[k] for k in ("id", "origin", "scope")} | {"name": name.strip()}, "file": f})
    if kind == "revision_put":
        src = st["sources"].get(body.get("source"))
        if src is None or src.get("purged"):
            return Reject("unknown_ref", "资料不存在")
        if src.get("deleted_at") is not None:
            return Reject("conflict", "资料在回收站里，先恢复")
        if latest(src)["stage"] in STAGES and not latest(src).get("failed"):
            return Reject("conflict", "上一个版本还在导入")
        f = _file(body.get("file"))
        return f if isinstance(f, Reject) else Ok({"source": src["id"], "file": f})
    if kind in ("source_set", "source_curate", "source_purged"):
        src = st["sources"].get(body.get("source"))
        if src is None or src.get("purged"):
            return Reject("unknown_ref", "资料不存在")
        if kind == "source_set":
            if not isinstance(body.get("disabled"), bool):
                return Reject("schema_error", "disabled 取 true 或 false")
            return Ok({"source": src["id"], "disabled": body["disabled"]})
        if kind == "source_curate":
            act = body.get("action")
            if act not in ("delete", "restore"):
                return Reject("schema_error", "action 取 delete 或 restore")
            if (act == "delete") == (src.get("deleted_at") is not None):
                return Reject("conflict", "已经在回收站里" if act == "delete" else "不在回收站里")
            return Ok({"source": src["id"], "action": act})
        if src.get("deleted_at") is None:
            return Reject("conflict", "不在回收站里")
        return Ok({"source": src["id"]})
    r = _rev(st, body)
    if isinstance(r, Reject):
        return r
    src, rev = r
    base = {"source": src["id"], "revision": rev["n"]}
    if kind in ("stage_done", "revision_ready", "stage_failed"):
        stage = body.get("stage", "index")
        if kind == "stage_done" and stage not in NEXT:
            return Reject("schema_error", f"stage_done 的 stage 取 {tuple(NEXT)}")
        if rev["stage"] != stage or rev.get("failed"):
            return Reject("conflict", f"版本 {rev['n']} 不在 {stage} 这一步")
        if kind == "stage_done":
            info = body.get("info")
            return Ok({**base, "stage": stage, "info": dict(info) if isinstance(info, dict) else {}})
        if kind == "stage_failed":
            return Ok({**base, "stage": stage, "reason": str(body.get("reason") or "")[:500]})
        return Ok({**base, "chunks": int(body.get("chunks") or 0), "embedder": str(body.get("embedder") or "")})
    if kind == "job_retry":
        if not rev.get("failed"):
            return Reject("conflict", "这一步没有失败")
        return Ok(base)
    # job_cancel
    if rev["stage"] not in STAGES:
        return Reject("conflict", "这个版本已经导入完或取消了")
    return Ok(base)


def apply(st: SState, ev: Mapping[str, Any]) -> SState:
    s = dict(st)
    s["seq"], s["now"] = ev["seq"], ev["ts"]
    b, kind = ev["body"], ev["kind"]
    sources = dict(s["sources"])
    if kind == "source_put":
        sid = b["source"]["id"]
        rev = {"n": 1, "file": b["file"], "stage": "parse", "failed": None, "info": {}, "chunks": 0, "ts": ev["ts"]}
        sources[sid] = {**b["source"], "created": ev["ts"], "revisions": [rev], "disabled": False, "deleted_at": None}
    else:
        sid = b["source"]
        src = dict(sources[sid])
        revs = [dict(r) for r in src["revisions"]]
        cur = next((r for r in revs if r["n"] == b.get("revision")), None)
        if kind == "revision_put":
            revs.append(
                {"n": len(revs) + 1, "file": b["file"], "stage": "parse", "failed": None, "info": {}, "chunks": 0}
                | {"ts": ev["ts"]}
            )
        elif kind == "stage_done" and cur is not None:
            cur["info"] = {**cur["info"], **b["info"]}
            cur["stage"] = NEXT[b["stage"]]
        elif kind == "revision_ready" and cur is not None:
            cur.update(stage="ready", chunks=b["chunks"], embedder=b["embedder"], ready_at=ev["ts"])
        elif kind == "stage_failed" and cur is not None:
            cur["failed"] = {"stage": b["stage"], "reason": b["reason"], "seq": ev["seq"]}
        elif kind == "job_retry" and cur is not None:
            cur["failed"] = None
        elif kind == "job_cancel" and cur is not None:
            cur.update(stage="cancelled", failed=None)
        elif kind == "source_set":
            src["disabled"] = b["disabled"]
        elif kind == "source_curate":
            src["deleted_at"] = ev["ts"] if b["action"] == "delete" else None
        elif kind == "source_purged":
            src["purged"] = True
        src["revisions"] = revs
        sources[sid] = src
    s["sources"] = sources
    return s
