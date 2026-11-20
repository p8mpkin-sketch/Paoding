"""整理族：curate（前端重新设计 v5 第三期；cz 2026-11-20 裁决“删除做软删”）。

人整理自己的任务：归档、移进回收站、从回收站或归档恢复、改显示名、置顶。日志只追加，
所以“删除”也是一条事件：题目、事件账、留档与花费都还在，读数照算；读端按 shelf 把它从列表里收起来。

- shelf：active | archived | trash。进回收站要先关题（正在跑的先停：调用方在同一批里先提交 close_problem）。
- 回收站保留 TRASH_DAYS 天：期内可恢复；过期后读端标成 purged，恢复被拒，工作区由执行层清掉（只清工作区，不动账）。
- title：显示名，原题名留在 renamed 里；pinned：置顶。三项可以一起改，至少给一项。

curate 不进等级、消费门、画像与终态；关题之后照样能提交。
"""

from __future__ import annotations

from ..parse import Obj
from ..state import Actor, Body, Event, Problem, State
from .common import Config, Ok, Reject

SHELVES = ("active", "archived", "trash")
TRASH_DAYS = 30
TRASH_MS = TRASH_DAYS * 86_400_000
TITLE_MAX = 200


def trash_until(p: Problem) -> int | None:
    """回收站里的题可恢复到什么时候（毫秒时间戳）；不在回收站时为 None。"""
    sh = p.get("shelf")
    return sh["ts"] + TRASH_MS if sh and sh["state"] == "trash" else None


def shelf_of(p: Problem, now: int) -> str:
    """读端用的位置：active | archived | trash | purged（回收站过期）。"""
    sh = p.get("shelf")
    if not sh:
        return "active"
    until = trash_until(p)
    return "purged" if until is not None and now >= until else sh["state"]


def _v_curate(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    allowed = {"shelf", "title", "pinned"}
    if not body.keys() <= allowed:
        return Reject("schema_error", f"curate 的字段为 {sorted(allowed)}，多了 {sorted(body.keys() - allowed)}")
    if not body.keys():
        return Reject("schema_error", "curate 至少改 shelf、title、pinned 中的一项")
    p = state["problems"][pid]
    cur = shelf_of(p, ts)
    if cur == "purged":
        return Reject(
            "forbidden_op", f"这个任务在回收站里超过 {TRASH_DAYS} 天，工作区已清，不能再整理（事件账与花费仍保留）"
        )
    out: Body = {}
    if "shelf" in body:
        shelf = body.get("shelf")
        if shelf not in SHELVES:
            return Reject("schema_error", f"shelf 取 {SHELVES}")
        if shelf == cur:
            return Reject("schema_error", f"任务已经在 {shelf}")
        if shelf == "trash" and not p["closed"]:
            return Reject("forbidden_op", "正在跑的任务要先停（close_problem）再移进回收站")
        out["shelf"] = shelf
        out["from"] = cur
    if "title" in body:
        title = body.text("title").strip()
        if not title or len(title) > TITLE_MAX:
            return Reject("schema_error", f"title 须非空、不超过 {TITLE_MAX} 字")
        if title == p["title"]:
            return Reject("schema_error", "新名字与现在的一样")
        out["title"] = title
    if "pinned" in body:
        pinned = body.get("pinned")
        if not isinstance(pinned, bool):
            return Reject("schema_error", "pinned 取 true 或 false")
        out["pinned"] = pinned
    return Ok(out)


def _a_curate(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    b = ev["body"]
    q: Problem = {**p}
    if "shelf" in b:
        q["shelf"] = {"state": b["shelf"], "seq": ev["seq"], "ts": ev["ts"]}
    if "title" in b:
        q["renamed"] = p.get("renamed", []) + [{"seq": ev["seq"], "from": p["title"]}]
        q["title"] = b["title"]
    if "pinned" in b:
        q["pinned"] = b["pinned"]
    s["problems"] = {**s["problems"], pid: q}
