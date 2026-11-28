"""进化读数（焚决 F5 的读端，docs/design/fenjue/04-evolution.md §7）：品阶史、已裁炼档与结局统计、常设留出的对照读数。

纯函数：输入是炼档 JSON、内核状态里的题与题目列表的行（graph views.problems 的
items），输出给 GET /v1/evolution。只读、不写任何东西；读数不驱动任何默认值（量具只显示）。

常设留出的对照：一道题分在哪一臂，按它开题时记下的那一版功法算（FJ6，与派工时用的是同一版），所以只有开在
“带这处留出的那几版功法”之下的题进这处对照；焚决之前开的题、存档里找不到摘要的题不进任何一臂。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .shapes import archived_digests, at, current, fire_at, for_problem, gongfa, stamp_of

MARKS = {"unjudged": "原形门未判", "failed": "原形门未过"}  # 两个记号公开显示（现行设计 4.4）；过了门的不挂
OUTCOMES = ("huolian", "helian", "buji", "binghuo", "fanshi")  # 火莲、合炼、不及原形、并火、反噬（03 §3）
DONE = ("solved", "accepted", "delivered")  # 做成：本地或外部判定通过、人工验收、开放道交付


def _arm_stats(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    closed = [r for r in rows if r["closed"]]
    done = [r for r in closed if r["terminal"] in DONE]
    spent = sum(int(r["spent_usd_milli"]) for r in rows)
    return {
        "tasks": len(rows),
        "open": len(rows) - len(closed),
        "closed": len(closed),
        "done": len(done),
        "done_rate": len(done) / len(closed) if closed else None,
        "spent_usd_milli": spent,
        "avg_spent_usd_milli": sum(int(r["spent_usd_milli"]) for r in closed) // len(closed) if closed else None,
        "avg_wall_s": sum(int(r["wall"]["elapsed_s"]) for r in closed) // len(closed) if closed else None,
    }


def _dossier_row(d: Mapping[str, Any]) -> dict[str, Any]:
    v = d.get("verdict") if isinstance(d.get("verdict"), dict) else None
    f = d.get("fire") or {}
    return {
        "dossier": d["dossier"],
        "name": d["name"],
        "title": d["title"],
        "status": d["status"],
        "identified": d["identified"],
        "fire": f"{f['id']}@{f['ver']}" if f.get("id") else None,
        "slot": f.get("slot"),
        "replaces": list((f.get("lineage") or {}).get("from") or []),
        "kernel_lines_changed": d.get("kernel_lines_changed"),
        "measure_lines_changed": d.get("measure_lines_changed"),  # 量具改动行数；验体之前、划线之前的炼档是 None
        "origin": d.get("origin"),  # 出身：自炼、手工、修订；没登记的是 None
        # 原形门的记号：未判、未过；判过了的、还没出读数的、不归门管的炼档是 None
        "gate_mark": MARKS.get(str((d.get("yuanxing_gate") or {}).get("state"))),
        "outcome_proposed": d.get("outcome_proposed"),
        "jie_proposed": d.get("jie_proposed"),
        "verdict": (
            {
                k: v[k]
                for k in ("by", "date", "outcome", "jie", "conditions", "basis", "system", "installed", "mark")
                if k in v
            }
            if v
            else None
        ),
        "reverts": [dict(r) for r in d.get("reverts") or []],
        "readings": [
            {k: r[k] for k in ("dim", "kind", "dir", "B", "A1", "F", "gate", "verdict") if k in r}
            for r in d.get("readings") or []
        ],
    }


def _archive(live_digest: str) -> list[dict[str, Any]]:
    out = []
    for dg in archived_digests():
        v = current() if dg == live_digest else at(dg)
        if v is not None:
            out.append({"jie": int(v.g["jie"]), "digest": dg, "current": dg == live_digest})
    return sorted(out, key=lambda r: (r["jie"], r["digest"]))


def evolution(
    dossiers: Iterable[Mapping[str, Any]],
    problems: Mapping[str, Mapping[str, Any]],
    items: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    live = gongfa()
    rows = {r["id"]: r for r in items}

    # 每一版功法下开了几道题、做成几道（按开题时记下的品阶与摘要分组）。人改钉过的题（体质修炼 003）前后用了
    # 两版，单列一行（按改钉到的那一版），不混进任何一版的读数
    by_version: dict[tuple[int, str | None, bool], list[Mapping[str, Any]]] = {}
    for pid, p in problems.items():
        if pid not in rows:
            continue
        moved = bool(p.get("repins"))
        s = stamp_of(p) or {}
        by_version.setdefault((int(s.get("jie", 0)), s.get("digest"), moved), []).append(rows[pid])
    versions = [
        {"jie": jie, "digest": dg, "current": dg == live["digest"] and not moved, "repinned": moved, **_arm_stats(rs)}
        for (jie, dg, moved), rs in sorted(by_version.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2]))
    ]

    ds = sorted((_dossier_row(d) for d in dossiers), key=lambda d: d["dossier"])
    counts = {o: 0 for o in OUTCOMES}
    manual = 0  # 出身是手工的炼档单列一栏「手工引导」，不计入任何一种结局（N6）
    for d in ds:
        if d["verdict"] and d["verdict"].get("outcome") in counts:
            if d["origin"] == "手工":
                manual += 1
            else:
                counts[d["verdict"]["outcome"]] += 1
    tally = {
        **counts,
        "manual": manual,
        "decided": sum(counts.values()) + manual,
        "pending": sum(1 for d in ds if not d["verdict"]),
        "reverted": sum(1 for d in ds if d["status"] == "reverted"),
    }

    # 常设留出：每一处（火位、留出的火、被顶替的火）两臂各自的读数
    arms: dict[tuple[str, str, str], dict[str, list[Mapping[str, Any]]]] = {}
    for pid, p in problems.items():
        if pid not in rows:
            continue
        v = for_problem(p)
        if not v.pinned or p.get("repins"):  # 改钉过的题前后两版，不进任何一臂
            continue
        for slot in v.g.get("holdout") or {}:
            for active_id, h in v.stand_ins(slot).items():
                a = next(r for r in v.g["fires"][slot] if r.partition("@")[0] == active_id)
                key = (slot, f"{h['id']}@{h['ver']}", a)
                side = "holdout" if v.in_holdout(pid, slot) else "main"
                arms.setdefault(key, {"main": [], "holdout": []})[side].append(rows[pid])
    for slot in live.get("holdout") or {}:  # 此刻的留出即使还没有题，也列出来
        for active_id, h in for_problem(None).stand_ins(slot).items():
            a = next(r for r in live["fires"][slot] if r.partition("@")[0] == active_id)
            arms.setdefault((slot, f"{h['id']}@{h['ver']}", a), {"main": [], "holdout": []})
    by_fire = {d["fire"]: d for d in ds if d["fire"]}
    holdout = []
    for (slot, href, aref), sides in sorted(arms.items()):
        f = fire_at(aref)
        holdout.append(
            {
                "slot": slot,
                "holdout": href,
                "active": aref,
                "dossier": by_fire[aref]["dossier"] if aref in by_fire else None,
                "live": href in (live.get("holdout") or {}).get(slot, []),
                "retire_signal": f.get("organ", {}).get("retire_signal"),
                "control_arm": f.get("organ", {}).get("control_arm"),
                "main": _arm_stats(sides["main"]),
                "held": _arm_stats(sides["holdout"]),
            }
        )

    return {
        "current": {
            "jie": live["jie"],
            "digest": live["digest"],
            "holdout_permille": int(live.get("holdout_permille", 0)),
            "fires": {k: list(v) for k, v in live["fires"].items()},
        },
        "history": [dict(h) for h in live.get("history") or []],
        # 功法存档里的每一版（体质修炼 003：人改钉只许改到这里有的版本；pd repin 与回滚弹窗按它把品阶解析成摘要）
        "archive": _archive(live["digest"]),
        "revisions": [dict(r) for r in live.get("revisions") or []],
        "versions": versions,
        "dossiers": ds,
        "outcomes": tally,
        "holdout": holdout,
    }
