"""交接（docs/design/fenjue/12-handoff.md）：引擎交出的交接包，与 `lianhua.py import` 收下它时做的全部确定性的事。

两边用同一组函数：引擎在 S6 用 `render_cuiyi`、`bang_updates`、`v_handoff` 出交接包；导入命令用 `check`（V1–V12
再跑一遍、功法摘要）、`slot_locks`（火位锁）、`recheck`（入位复核）、`to_dossier`（`lianhua.new → cuiyi → ruwei`，
炼档加 `engine`、`group` 两个可选键）、`apply_bang`（写异火榜）。读写文件与原子改名在 `scripts/lianhua.py`。
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from .. import lianhua as lh
from .. import shapes
from . import checks, data, ruwei, schema, sections, text

HOLDS = {"yes": "成立", "partial": "部分成立", "no": "不成立"}
IN_FLIGHT = ("placed", "design_approved", "trialed", "readings_ready")  # 火位锁：在途炼档（12 §2.1 第 2 步）
HARD_K = ("K1", "K2", "K3", "K4", "K5", "K7", "K8")
PLACEMENT_EXTRA = ("atoms", "group", "conflicts", "steps", "kernel_forecast", "split", "new_slot", "difficulty")


class ImportRefused(ValueError):
    """导入不了：校验不过、功法变了且复核不过、火位被占。"""


# ---------------------------------------------------------------- 萃意八栏（12 §2.2）


def render_cuiyi(essence: Mapping[str, Any], by: str = "cz") -> dict[str, str]:
    """火意 → 炼档的萃意八栏。只渲染九栏齐全的火意（进过归位的都是）；不齐的由调用方先用 `sections.gaps` 挡下。"""
    m = essence["masked"]
    premise = []
    for p in m.get("premises", []):
        alt = f"；替代：{p['replaced_by']}" if p.get("replaced_by") else ""
        premise.append(f"{p['statement']}（{HOLDS.get(p['holds_here'], p['holds_here'])}：{p['why']}{alt}）")
    overlap = [f"{o['fire']}（{'、'.join(o.get('dims', []))}，{o['relation']}）" for o in m.get("overlaps", [])]
    conflict = [f"{c['with']}：{c['statement']} → {c.get('how') or c['resolution']}" for c in m.get("conflicts", [])]
    emergent = [e["dim"] for e in m["fusion"].get("emergent", [])]
    split = [f"{s['part']} → {s['kernel']}（{s['to']}）" for s in m.get("split", [])]
    return {
        "yi": m["statement"],
        "premise": "；".join(premise) or "无",
        "cost": "；".join(c["cost"] for c in m.get("costs", [])) or "无",
        "overlap": "；".join(overlap) or "无",
        "conflict": "；".join(conflict) or "无",
        "hypothesis": f"{m['fusion']['statement']}。新生维：{'、'.join(emergent) or '无'}",
        "split": "；".join(split) or "无",
        "masked": masked_line(essence.get("checks", []), by),
    }


def masked_line(rows: Sequence[Mapping[str, Any]], by: str = "cz") -> str:
    got = {c["id"]: c for c in rows}
    bad = [k for k in HARD_K if k in got and not got[k]["ok"]]
    over = [k for k in bad if got[k].get("override")]
    head = "机器检验 K1–K5、K7、K8 全过" if not bad else f"机器检验未过 {'、'.join(bad)}"
    k6 = got.get("K6")
    blind = "K6 盲审未猜中出处" if not k6 or k6["ok"] else "K6 盲审猜中出处，只作读数"
    tail = f"；{by} 坚持的未过项：{'、'.join(f'{k}（人改，检验未过）' for k in over)}" if over else ""
    return f"{head}（{blind}）{tail}；闸点 2 由 {by} 确认遮住出处成立"


# ---------------------------------------------------------------- 异火榜更新提议（09 §8、10 §11）


def _next_ids(bang: Sequence[Mapping[str, Any]]) -> Iterator[str]:
    n = max((int(e["id"][2:]) for e in bang), default=0)
    while True:
        n += 1
        yield f"Y-{n:03d}"


def bang_updates(
    bang: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, Any],
    *,
    run: str,
    mode: str,
    date: str,
    fates: Mapping[str, tuple[str, str, str]],
    essences: Mapping[str, Mapping[str, Any]],
    artifacts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """fates：候选 → (走到哪一步, 榜状态或空, 说明)。已在榜上的记 set_status / add_run，首次出现的记 add。"""
    out: list[dict[str, Any]] = []
    ids = _next_ids(bang)
    basis = candidates["basis"]
    lic = basis["snapshots"][0]["license"]
    form = basis["snapshots"][0]["form"]
    for c in candidates["candidates"]:
        if c["id"] not in fates:
            continue
        reached, status, note = fates[c["id"]]
        # candidate 只在交接包里用（导入时把档号填回对应条目），写进榜之前去掉
        row_run: dict[str, Any] = {"run": run, "mode": mode, "reached": reached, "outcome": note, "candidate": c["id"]}
        if artifacts:
            row_run["artifacts"] = list(artifacts)
        known = c.get("dedupe", {}).get("bang")
        if known:
            if status:
                out.append({"op": "set_status", "id": known, "status": status, "note": note})
            out.append({"op": "add_run", "id": known, "run": row_run})
            continue
        ess = essences.get(c["id"])
        if ess is not None and sections.gaps(ess):
            ess = None  # 九栏不齐的提炼结果不往榜上写：本质句退回用识别时的现象描述，不写融合假设
        entry: dict[str, Any] = {
            "id": next(ids),
            "title": c["title"][:40],
            "essence": (ess["masked"]["statement"] if ess else c["seed"]["shihuo"]["phenomenon"])[:80],
            "slot": c["slot"],
            "status": status or "identified",
            "history": [{"date": date, "status": status or "identified", "by": "方案分析（提议）", "note": note}],
        }
        if ess:
            entry["fusion"] = ess["masked"]["fusion"]["statement"][:300]
        if c.get("also_slots"):
            entry["also_slots"] = list(c["also_slots"])
        entry["dims"] = [g["dim"] for g in c["gaps"]]
        entry["source_kind"] = f"{data.FORM_ZH.get(form, form)}形态的外部系统"
        entry["license"] = dict(lic)
        for k in ("value", "confidence", "difficulty", "risk", "priority"):
            entry[k] = c[k]
        entry["basis_gongfa_digest"] = basis["gongfa_digest"]
        entry["kernel_lines_expected"] = 0
        entry["runs"] = [{k: v for k, v in row_run.items() if k != "candidate"}]
        out.append({"op": "add", "entry": entry, "note": f"候选 {c['id']}"})
    return out


def apply_bang(
    doc: Mapping[str, Any], updates: Sequence[Mapping[str, Any]], date: str, numbers: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """把更新写进异火榜（导入命令与 `lianhua.py bang` 用）。numbers：候选编号 → 新档号（交实现线的填进条目）。"""
    out = copy.deepcopy(dict(doc))
    entries = {e["id"]: e for e in out["entries"]}
    numbers = dict(numbers or {})

    def run_row(e: dict[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(row)
        cid = row.pop("candidate", None)
        if cid in numbers:
            e["dossier"] = numbers[cid]
        return row

    for u in updates:
        op = u["op"]
        if op == "add":
            e = copy.deepcopy(dict(u["entry"]))
            if e["id"] in entries:
                raise ImportRefused(f"异火榜里已经有 {e['id']}：交接包按旧榜编的号，要按新榜重出交接包")
            e["runs"] = [run_row(e, r) for r in e.get("runs", [])]
            cid = str(u.get("note", "")).removeprefix("候选 ")
            if cid in numbers:
                e["dossier"] = numbers[cid]
            out["entries"].append(e)
            entries[e["id"]] = e
            continue
        found = entries.get(str(u.get("id")))
        if found is None:
            raise ImportRefused(f"异火榜里没有 {u.get('id')}")
        e = found
        if op == "set_status":
            e["status"] = u["status"]
            e["history"].append({"date": date, "status": u["status"], **({"note": u["note"]} if u.get("note") else {})})
        elif op == "add_run":
            e.setdefault("runs", []).append(run_row(e, u["run"]))
        elif op == "merge_into":
            e["status"] = "superseded"
            e["history"].append({"date": date, "status": "superseded", "note": f"并入 {u['into']}"})
    errs = schema.errors(out, "bang")
    if errs:
        raise ImportRefused(f"写完的异火榜不合 Schema：{errs[:3]}")
    return out


# ---------------------------------------------------------------- 交接包的校验（V1–V12）


def v_handoff(
    h: Mapping[str, Any], ctx: checks.Context | None = None, to_implementation: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    """交接包的校验。ctx 为 None 是导入时（没有观察库与快照原文）：只核对包内自洽的部分。"""
    ctx = ctx or checks.Context(names=[], corpus=[], observations={}, license=h["basis"]["snapshots"][0]["license"])
    items = h.get("items", [])
    v3, v8, v9, v10, v11 = [], [], [], [], []
    for it in items:
        cid = it["candidate"]
        if shapes.digest(it["essence"]) != it["artifacts"]["essence"]:
            v3.append(f"{cid} 的火意与 artifacts.essence 的 sha256 不符")
        if shapes.digest(it["placement"]) != it["artifacts"]["placement"]:
            v3.append(f"{cid} 的入位方案与 artifacts.placement 的 sha256 不符")
        v8 += [f"{cid}：{x}" for x in checks.v8(it["placement"])]
        missing = sections.gaps(it["essence"])
        if missing:  # 手改过或别处来的交接包：缺栏的火意不逐栏核对（读不动），照实报缺什么
            v11.append(f"{cid} 的火意缺栏目，不能交实现线：{'；'.join(missing[:6])}"[:300])
            continue
        v9 += [f"{cid}：{x}" for x in checks.v9(it["placement"], it["essence"])]
        v10 += [f"{cid}：{x}" for x in checks.v10(it["placement"], it["essence"])]
        if render_cuiyi(it["essence"], h["decided_by"]) != it["cuiyi"]:
            v11.append(f"{cid} 的萃意八栏与火意按 12 §2.2 渲染的不同")
        if it["placement"]["candidate"] != cid or it["essence"]["candidate"] != cid:
            v11.append(f"{cid} 的火意或入位方案属于别的候选")
    if to_implementation is not None and sorted(it["candidate"] for it in items) != sorted(to_implementation):
        v11.append("交接包的候选与闸点 3 交实现线的不一致")
    pos = [o["position"] for o in h.get("order", [])]
    v4 = [] if pos == list(range(1, len(pos) + 1)) else ["火序的位次不连续"]
    v7 = checks._v7({"basis": h["basis"]}, ctx)
    for it in items:
        v7 += checks._v7(it["essence"], ctx)
    names = [o["candidate"] for o in h.get("order", [])]
    return [
        checks.result("V1", schema.errors(h, "handoff")),
        checks.result("V2", checks._dupes(names) + checks._dupes([it["candidate"] for it in items])),
        checks.result("V3", v3),
        checks.result("V4", v4),
        checks.result("V5", checks._plain(checks.displayed(h, "handoff"))),
        checks.result("V6", checks._copy_problems([s for it in items for s in text.strings(it)], ctx)),
        checks.result("V7", v7),
        checks.result("V8", v8),
        checks.result("V9", v9),
        checks.result("V10", v10),
        checks.result("V11", v11),
        checks.result("V12", checks._v12(h, ctx)),
    ]


# ---------------------------------------------------------------- 导入（lianhua.py import 的纯函数部分）


def check(h: Mapping[str, Any]) -> list[str]:
    """第 1 步：Schema、交接包自带的校验结果、再跑一遍的 V1–V12。"""
    errs = schema.errors(h, "handoff")
    if errs:
        return [f"交接包不合 Schema：{e}" for e in errs[:5]]
    out = [f"交接包自带的 {c['id']} 未过：{c.get('detail', '')}" for c in h["validator"] if not c["ok"]]
    out += [f"再跑 {c['id']} 未过：{c.get('detail', '')}" for c in v_handoff(h) if not c["ok"]]
    return out


def slot_locks(dossiers: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """第 2 步：在途炼档（入位到读数已出之间）占着的火位 → 档号（含火组成员的火位）。"""
    out: dict[str, str] = {}
    for d in dossiers:
        if d.get("status") not in IN_FLIGHT:
            continue
        for f in [d["fire"], *[g["fire"] for g in d.get("group") or []]]:
            if f.get("slot"):
                out.setdefault(f["slot"], d["dossier"])  # 先入位的占着
    return out


def slots_of(item: Mapping[str, Any]) -> list[str]:
    p = item["placement"]
    return [p["fire"]["slot"], *[g["slot"] for g in p["group"]]]


def recheck(placement: Mapping[str, Any], gongfa: Mapping[str, Any] | None = None) -> list[str]:
    """第 3 步，入位复核（09 §9）：按当前功法重算原子归属。被替换的火、原子的拥有者、兼及火位都没变才继续。"""
    owners = ruwei.ownership(gongfa)
    g = gongfa or shapes.gongfa()
    live = {r.partition("@")[0]: r for rs in g["fires"].values() for r in rs}
    seats = set(placement["fire"].get("seats", []))
    out = []
    for a in placement["atoms"]:
        if not a["home"].startswith("H"):
            continue
        now = [
            o.fire for o in owners.get(a["atom"], []) if o.slot == a["home"] and (a["home"] != "H1" or o.seat in seats)
        ]
        was = a.get("owner_now")
        if was and was not in now:
            out.append(f"{a['atom']} 的拥有者从 {was} 变成了 {now or '无'}")
        if not was and now:
            out.append(f"{a['atom']} 现在有了拥有者 {now}")
    for f in [placement["fire"], *placement["group"]]:
        for x in f["lineage"]["from"]:
            if x not in live:
                out.append(f"{f['id']} 要顶替的 {x} 已不在功法里")
    return out


def to_dossier(
    item: Mapping[str, Any], no: str, *, run: str, provenance: Mapping[str, Any], by: str = "cz"
) -> dict[str, Any]:
    """第 4–5 步：调既有纯函数开档、萃意、入位，顺序与手工相同；清单草稿填上档号；炼档加 engine 与 group。"""
    seed = item["seed"]
    d = lh.new(no, seed["name"], seed["title"], seed["identified"], seed["shihuo"])
    d = lh.cuiyi(d, item["cuiyi"])
    p = item["placement"]
    fire = copy.deepcopy(p["fire"])
    fire["lineage"]["dossier"] = no
    group = []
    for g in p["group"]:
        gf = copy.deepcopy(g)
        gf["lineage"]["dossier"] = no
        group.append({"fire": gf, "replaces": gf["lineage"]["from"][0] if gf["lineage"]["from"] else None})
    readings = [{k: v for k, v in r.items() if k in ("dim", "kind", "dir", "gate", "test")} for r in p["readings"]]
    d = lh.ruwei(
        d, fire, p["replaces"], p["arms"], readings, f"本档第三节（{no}，由方案分析 {run} 导入时登记）", group=group
    )
    d["engine"] = {
        "run": run,
        "candidate": item["candidate"],
        "decided_by": by,
        "artifacts": dict(item["artifacts"]),
        "essence": copy.deepcopy(item["essence"]),
        "placement_extra": {k: copy.deepcopy(p[k]) for k in PLACEMENT_EXTRA},
        "readings_extra": [
            {k: v for k, v in r.items() if k not in ("dim", "kind", "dir", "gate", "test")} | {"dim": r["dim"]}
            for r in p["readings"]
            if set(r) - {"dim", "kind", "dir", "gate", "test"}
        ],
        "provenance": copy.deepcopy(dict(provenance)),
    }
    return d


# ---------------------------------------------------------------- 结局回写（12 §5，由 lianhua.py jue / sanhuo 顺手做）


def writeback(
    doc: Mapping[str, Any], d: Mapping[str, Any], event: str, date: str, by: str, why: str = ""
) -> dict[str, Any] | None:
    """炼档裁决或散火后改异火榜上对应的条目（按 dossier 找）。event：jue 或 sanhuo。榜上没有这份炼档时返回 None。"""
    out = copy.deepcopy(dict(doc))
    e = next((x for x in out["entries"] if x.get("dossier") == d["dossier"]), None)
    if e is None:
        return None
    if event == "sanhuo":
        e["status"] = "reverted"
        e["history"].append({"date": date, "status": "reverted", "by": by, **({"note": why} if why else {})})
    else:
        v = d["verdict"]
        taken = v["outcome"] in lh.TAKEN
        e["status"] = "absorbed" if taken else "rejected"
        note = f"炼档 {d['dossier']}：{lh.OUTCOMES[v['outcome']]}"
        if taken:
            e["jie"] = v["jie"]
        else:
            e["lessons"] = [*e.get("lessons", []), *[str(w) for w in d.get("outcome_why", [])]]
        e["history"].append({"date": date, "status": e["status"], "by": by, "note": note})
    errs = schema.errors(out, "bang")
    if errs:
        raise ImportRefused(f"回写后的异火榜不合 Schema：{errs[:3]}")
    return out


def ready_to_import(doc: Mapping[str, Any], dossiers: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """排队的候选（已交实现线、还没有档号）里，火位已经空出来的：提示先做入位复核再导入（12 §5 末行）。"""
    locks = slot_locks(dossiers)
    out = []
    for e in doc["entries"]:
        if e["status"] != "handed_off" or e.get("dossier"):
            continue
        slots = [e["slot"], *e.get("also_slots", [])]
        if not any(s in locks for s in slots):
            out.append(dict(e))
    return out
