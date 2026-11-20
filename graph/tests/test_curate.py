"""整理（curate，前端重新设计 v5 第三期；cz 2026-11-20 裁决“删除做软删”）。

- 只有人能整理；关题之后照样能整理。
- 进回收站要先关题；回收站 30 天内可恢复，过期为 purged，再整理被拒。
- 软删不动账：题目、花费、读数合计照旧。
- 改名留下原名；置顶是布尔。
"""

from __future__ import annotations

from conftest import HUMAN, Kernel
from test_open_lane import open_lane

from paoding_graph import views
from paoding_graph.reducer.curate import TRASH_MS

SINAN = {"kind": "sinan", "id": "sn1"}


def row(k: Kernel, pid: str = "p1") -> dict:
    return next(x for x in views.problems(k.state)["items"] if x["id"] == pid)


def test_only_human_and_shape():
    k = Kernel()
    open_lane(k)
    assert k.submit(SINAN, "p1", "curate", {"pinned": True}) == "forbidden_op"
    assert k.submit(HUMAN, "p1", "curate", {}) == "schema_error"
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "gone"}) == "schema_error"
    assert k.submit(HUMAN, "p1", "curate", {"pinned": "yes"}) == "schema_error"
    assert k.submit(HUMAN, "p1", "curate", {"title": "  "}) == "schema_error"
    assert k.submit(HUMAN, "p1", "curate", {"title": "t"}) == "schema_error"  # 与现名相同
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "active"}) == "schema_error"  # 已经在
    assert k.submit(HUMAN, "p1", "curate", {"x": 1}) == "schema_error"


def test_rename_and_pin_keep_the_old_title():
    k = Kernel()
    open_lane(k)
    assert k.submit(HUMAN, "p1", "curate", {"title": "新名字", "pinned": True}) == "ok"
    p = k.state["problems"]["p1"]
    assert p["title"] == "新名字" and p["pinned"] is True
    assert p["renamed"] == [{"seq": len(k.events), "from": "t"}]
    r = row(k)
    assert r["title"]["value"] == "新名字" and r["pinned"] is True and r["shelf"] == "active"


def test_trash_needs_close_first_and_keeps_the_books():
    k = Kernel()
    open_lane(k)
    before = views.problems(k.state)["totals"]
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "trash"}) == "forbidden_op"  # 正在跑：先停
    assert k.submit(HUMAN, "p1", "close_problem", {"reason": "不要了"}) == "ok"
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "trash"}) == "ok"
    r = row(k)
    assert r["shelf"] == "trash" and r["trash_until"] == k.ts + TRASH_MS
    after = views.problems(k.state)["totals"]
    assert after["problems"] == before["problems"] and after["spent_usd_milli"] == before["spent_usd_milli"]
    assert k.events[-1]["body"] == {"shelf": "trash", "from": "active"}


def test_restore_within_thirty_days_then_purged():
    k = Kernel()
    open_lane(k)
    k.submit(HUMAN, "p1", "close_problem", {})
    k.submit(HUMAN, "p1", "curate", {"shelf": "trash"})
    k.ts += TRASH_MS - 10
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "active"}) == "ok"  # 期内恢复
    assert row(k)["shelf"] == "active" and row(k)["trash_until"] is None
    k.submit(HUMAN, "p1", "curate", {"shelf": "trash"})
    k.ts += TRASH_MS
    open_lane(k, "p2")  # 推进状态时钟
    assert row(k)["shelf"] == "purged"
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "active"}) == "forbidden_op"
    assert k.submit(HUMAN, "p1", "curate", {"pinned": True}) == "forbidden_op"
    assert views.problems(k.state)["totals"]["problems"] == 2  # 账还在


def test_archive_does_not_need_close():
    k = Kernel()
    open_lane(k)
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "archived"}) == "ok"
    assert row(k)["shelf"] == "archived" and not k.state["problems"]["p1"]["closed"]
    assert k.submit(HUMAN, "p1", "curate", {"shelf": "active"}) == "ok"
