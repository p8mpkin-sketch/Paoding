"""入位（docs/design/fenjue/08-algorithms.md §5）：把一份确认过的火意落到火位上，出入位方案（placement.schema.json）。

十二步里只有三步交给丹：第 1 步拆原子（位丹，中档）、第 9–11 步各臂、预登记读数与实现步骤（主丹，重档）。
其余全部确定性：归位、主火位、兼及火位与火组、席位、经脉、冲突、替换谁、必登读数、体质影响预判、难度。
丹给的原子只能从原子表（`tables/atoms.json`）里选，或选 `other` 并写理由；冲突的种类由参数类型签名判，不由丹判；
丹可以在允许的化解里挑一种（参数冲突：取新值、分区、暴露为参数；语义冲突：替换、分区、不收），H1 上同一席位只能替换。

试算模式只做位丹那一步（`full=False`）：主火位、火组、替换谁、冲突、体质影响预判、难度，不写各臂与实现步骤。
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .. import shapes
from ..lianhua import KERNEL_PATHS
from ..tables import SEATS
from . import data, formulas
from .dan import Dan

ATTEMPTS = 3
TYPES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "num": (int, float),
    "bool": (bool,),
    "list": (list,),
    "obj": (dict,),
}
# 必登的本火维（08 §5.2 第 10 步）：旧日志逐字节回放、凭据泄漏数；动到 H1–H5 的加“严格道事件日志不变”
MANDATORY: tuple[dict[str, Any], ...] = (
    {"dim": "旧日志逐字节回放", "kind": "本火", "dir": "up", "gate": "过", "test": "tests/fenjue/test_t4_zhang.py"},
    {"dim": "凭据泄漏数", "kind": "本火", "dir": "down", "gate": 0, "test": "tests/fenjue/trials.py T2"},
)
STRICT_LANE: dict[str, Any] = {
    "dim": "严格道事件日志不变",
    "kind": "本火",
    "dir": "up",
    "gate": "相同",
    "test": "tests/fenjue/zero_diff.py --check（开关关时）",
}
STRICT_SLOTS = ("H1", "H2", "H3", "H4", "H5")
# 体质项 → 可能触到的体质路径（试算报告的体质影响预判用；正式入位按实现步骤的文件区求交）
KERNEL_AREAS = {
    "T1": ["judgebox/", "graph/src/"],
    "T2": [p for p in KERNEL_PATHS if p.startswith("adapter/")],
    "T3": ["adapter/src/paoding_adapter/proxy.py"],
    "T4": ["graph/src/"],
    "T5": ["graph/src/"],
}
ALLOWED = {
    "parametric": ("param", "partition", "replace"),
    "semantic": ("replace", "partition", "reject"),
}
DEFAULT = {"parametric": "param", "semantic": "replace"}
INFEASIBLE = "infeasible:"
_PORT_ORDER = re.compile(r"^M([1-7])(?::(.*))?$")


# ---------------------------------------------------------------- 原子表与原子归属


def atoms() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = data.table("atoms")["atoms"]
    return out


def _key_map() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = data.table("atoms")["keys"]
    return rows


def atom_of(slot: str, key: str) -> str | None:
    """清单 params 的一个键（H1 写成 `forms.*.<键>`）→ 原子；不认识的给 None（校验器要求功法里没有这种键）。"""
    for row in _key_map():
        if row["slot"] in (slot, "*") and row["key"] == key:
            return row["atom"]
    return None


def _param_keys(f: Mapping[str, Any]) -> Iterable[tuple[str | None, str, Any]]:
    """(席位, 映射用的键, 值)。H1 的形态参数在 forms.<席位> 之下。"""
    params = f.get("params", {})
    if f["slot"] == "H1" and isinstance(params.get("forms"), dict):
        for seat, form in params["forms"].items():
            for k, v in form.items():
                yield seat, f"forms.*.{k}", v
        for k, v in params.items():
            if k != "forms":
                yield None, k, v
        return
    for k, v in params.items():
        yield None, k, v


@dataclass(frozen=True)
class Owner:
    fire: str  # id@ver
    slot: str
    seat: str | None
    params: tuple[tuple[str, Any], ...]

    @property
    def fid(self) -> str:
        return self.fire.partition("@")[0]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.params)


def ownership(gongfa: Mapping[str, Any] | None = None) -> dict[str, list[Owner]]:
    """原子 → 今天拥有它的生效火（常设留出里的不算）。H1 按席位分开记。"""
    g = gongfa or shapes.gongfa()
    acc: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for slot, refs in g["fires"].items():
        for r in refs:
            f = shapes.fire_at(r)
            for seat, key, v in _param_keys(f):
                atom = atom_of(slot, key)
                if atom is None or atom == "scope.lanes":
                    continue
                acc.setdefault((atom, r, seat), {})[key.rpartition(".")[2]] = v
    out: dict[str, list[Owner]] = {}
    for (atom, r, seat), params in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")):
        slot = shapes.fire_at(r)["slot"]
        out.setdefault(atom, []).append(Owner(r, slot, seat, tuple(sorted(params.items()))))
    return out


def unmapped(gongfa: Mapping[str, Any] | None = None) -> list[str]:
    """功法里每团生效火的每个参数键都要有原子（08 §5.1：校验器核对）。"""
    g = gongfa or shapes.gongfa()
    out = []
    for slot, refs in g["fires"].items():
        for r in refs:
            for _, key, _ in _param_keys(shapes.fire_at(r)):
                if atom_of(slot, key) is None:
                    out.append(f"{r}：{key}")
    return out


def seat_forms(gongfa: Mapping[str, Any] | None = None) -> dict[str, str]:
    """H1 每个席位今天的形态（id@ver）。同一席位今天只能有一个形态（08 §5.2 第 5 步）。"""
    g = gongfa or shapes.gongfa()
    out = {}
    for r in g["fires"].get("H1", []):
        for seat in shapes.fire_at(r).get("seats", []):
            out[seat] = r
    return out


def family(atom: str, params: Mapping[str, Any]) -> str | None:
    """规则族：参数键都在某一族的类型签名里、值的类型也对上，就属于那一族（08 §5.3）。"""
    if not params:
        return None
    for name, sig in atoms().get(atom, {}).get("families", {}).items():
        ok = True
        for k, v in params.items():
            t = sig.get(k)
            if t is None or not isinstance(v, TYPES[t]) or (t in ("int", "num") and isinstance(v, bool)):
                ok = False
                break
        if ok:
            return str(name)
    return None


def conflict_kind(atom: str, ours: Mapping[str, Any], theirs: Mapping[str, Any]) -> str:
    a, b = family(atom, ours), family(atom, theirs)
    return "parametric" if a is not None and a == b else "semantic"


# ---------------------------------------------------------------- 丹的输入


def _masked(essence: Mapping[str, Any]) -> dict[str, Any]:
    m = essence["masked"]
    return {k: m[k] for k in ("statement", "mechanism", "conflicts", "fusion", "split") if k in m}


def placer_payload(
    cand: Mapping[str, Any], essence: Mapping[str, Any], errors: Sequence[str], owners: Mapping[str, list[Owner]]
) -> dict[str, Any]:
    slots = {cand["slot"], *cand.get("also_slots", [])}
    p: dict[str, Any] = {
        "template": "ruwei/place/v1",
        "candidate": {k: cand[k] for k in ("id", "name", "title", "slot", "also_slots") if k in cand},
        "essence": _masked(essence),
        "atoms": {k: {"home": v["home"], "meaning": v["meaning"]} for k, v in sorted(atoms().items())},
        "owners": {
            atom: [{"fire": o.fire, "seat": o.seat, "params": o.as_dict()} for o in rows if o.slot in slots]
            for atom, rows in sorted(owners.items())
            if any(o.slot in slots for o in rows)
        },
        "seats": {k: list(v) for k, v in sorted(SEATS.items())},
        "seat_forms": seat_forms(),
        "schema": "placer.v1：atoms[{atom, mechanism_steps, params, emergent, why_other}], fire{id, seats, params, "
        "assets, organ}, group[{slot, id, params, assets, organ}], resolutions[{atom, fire, resolution, "
        "partition_by, note}], new_slot, depends_on, plain_summary",
    }
    if errors:
        p["errors"] = list(errors)
    return p


def design_payload(skeleton: Mapping[str, Any], essence: Mapping[str, Any], errors: Sequence[str]) -> dict[str, Any]:
    p: dict[str, Any] = {
        "template": "ruwei/design/v1",
        "placement": {k: skeleton[k] for k in ("candidate", "atoms", "fire", "group", "replaces", "conflicts")},
        "emergent": essence["masked"]["fusion"]["emergent"],
        "mandatory": [r["dim"] for r in mandatory_readings(skeleton)],
        "kernel_paths": list(KERNEL_PATHS),
        "schema": "design.v1：arms{B, A1, F, B1, A0?}, readings[{dim, kind, dir, gate, test|run}], "
        "steps[{do, slot, where, tests, kernel_lines, accept}]",
    }
    if errors:
        p["errors"] = list(errors)
    return p


# ---------------------------------------------------------------- 确定性的几步


def _port_key(p: str) -> tuple[int, str]:
    m = _PORT_ORDER.match(p)
    return (int(m.group(1)), m.group(2) or "") if m else (9, p)


def _tool_ports(params: Mapping[str, Any]) -> set[str]:
    out = set()
    for form in (params.get("forms") or {}).values():
        for t in form.get("tools", []):
            out |= {f"M1:{ev}" for ev in shapes.TOOL_EVENTS.get(t, ())}
    return out


def mandatory_readings(placement: Mapping[str, Any]) -> list[dict[str, Any]]:
    slots = {placement["fire"]["slot"], *[g["slot"] for g in placement.get("group", [])]}
    rows = [dict(r) for r in MANDATORY]
    if slots & set(STRICT_SLOTS):
        rows.append(dict(STRICT_LANE))
    for r in rows:
        r["mandatory"] = True
    return rows


def kernel_forecast(steps: Sequence[Mapping[str, Any]]) -> list[str]:
    """第 12 步：实现步骤的文件区 ∩ KERNEL_PATHS（前缀相交即算：写到上级目录也算碰到）。"""
    hits = set()
    for s in steps:
        for w in s.get("where", []):
            area = re.split(r"[（(\s]", w.strip(), maxsplit=1)[0]
            for kp in KERNEL_PATHS:
                if area and (area.startswith(kp) or kp.startswith(area)):
                    hits.add(kp)
    return sorted(hits)


def kernel_issues(essence: Mapping[str, Any], placement: Mapping[str, Any]) -> list[str]:
    """冲突探针命中的体质项都已化解（萃意融掉）或拆出（V9 的第三条）。"""
    feats = data.features()
    covered = {k["kernel"] for k in placement["conflicts"]["kernel"]} | {s["kernel"] for s in placement["split"]}
    out = []
    for st in essence["masked"].get("mechanism", []):
        for f in st.get("features", []):
            k = feats.get(f, {}).get("kernel")
            if k and k not in covered:
                out.append(f"机制第 {st['step']} 步的 {f} 碰到 {k}，既没化解也没拆出")
    return out


def difficulty_parts(
    placement: Mapping[str, Any], essence: Mapping[str, Any], baseline_ports: Iterable[str], *, new_tool: bool
) -> dict[str, int]:
    ports = set(placement["fire"]["ports"])
    emergent = essence["masked"]["fusion"]["emergent"]
    a1 = str(placement.get("arms", {}).get("A1", ""))
    return {
        "behavior_slots_minus_1": len(placement["group"]),
        "extra_ports": len(ports - set(baseline_ports)),
        "new_tool": int(new_tool),
        "kernel_split": int(bool(placement["split"])),
        "a1_infeasible": int(a1.startswith(INFEASIBLE)),
        "run_only_emergent": int(any(e.get("measure") == "run" for e in emergent)),
    }


def _plain_conflict(row: Mapping[str, Any]) -> str:
    return f"{row['fire']} {row['atom']}：{row['kind']} → {row['resolution']}"


@dataclass
class Skeleton:
    """位丹那一步之后的确定性结果（试算到此为止）。"""

    placement: dict[str, Any]
    problems: list[str]
    baseline_ports: list[str]
    new_tool: bool
    depends_on: list[str] = field(default_factory=list)


def skeleton(
    cand: Mapping[str, Any],
    essence: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    owners: Mapping[str, list[Owner]] | None = None,
    locks: Sequence[Mapping[str, Any]] = (),
) -> Skeleton:
    """第 2–8 步与第 12 步的一半（体质原子、拆分）：确定性，丹的提议只作输入。"""
    owners = owners if owners is not None else ownership()
    table = atoms()
    problems: list[str] = []
    rows: list[dict[str, Any]] = []
    emergent_homes: list[str] = []
    split = [dict(s) for s in essence["masked"].get("split", [])]
    kernel_rows: list[dict[str, Any]] = []
    for c in essence["masked"].get("conflicts", []):
        if c["kind"] == "kernel":
            res = "fused_away" if c["resolution"] == "fused_away" else "split_to_kernel"
            kernel_rows.append({"kernel": c["with"], "resolution": res, "note": c.get("how") or c["statement"]})
    other_why = []
    for a in proposal.get("atoms", []):
        name = str(a.get("atom", ""))
        steps = [int(x) for x in a.get("mechanism_steps", []) if isinstance(x, int)] or [1]
        if name == "other":
            why = str(a.get("why_other", "")).strip()
            if not why:
                problems.append("选了 other 的原子要写一句为什么")
            other_why.append(why)
            rows.append({"atom": "other", "home": "none", "mechanism_steps": steps, "why_other": why[:300]})
            continue
        if name not in table or name == "scope.lanes":
            problems.append(f"没有这个决策原子：{name}（只能从原子表里选，或选 other）")
            continue
        home = table[name]["home"]
        row: dict[str, Any] = {"atom": name, "home": home, "mechanism_steps": steps}
        if isinstance(a.get("params"), dict) and a["params"]:
            row["params"] = dict(a["params"])
        rows.append(row)
        if home.startswith("T"):
            why = str(a.get("why_other") or table[name]["meaning"])
            split.append(
                {"part": f"{table[name]['meaning']}（{why}）"[:300], "kernel": home, "to": "体质修炼变更表草稿"}
            )
            if not any(k["kernel"] == home for k in kernel_rows):
                kernel_rows.append({"kernel": home, "resolution": "split_to_kernel", "note": f"原子 {name} 属于内核"})
            continue
        if a.get("emergent"):
            emergent_homes.append(home)
    if not rows:
        problems.append("位丹没有拆出任何决策原子")
    # 合并去重：同一体质项拆出一次（与萃意第 8 步合并）
    seen: set[tuple[str, str]] = set()
    uniq = []
    for sp in split:
        if (sp["kernel"], sp["part"]) not in seen:
            seen.add((sp["kernel"], sp["part"]))
            uniq.append(sp)
    split = uniq
    kernel_rows = list({k["kernel"]: k for k in reversed(kernel_rows)}.values())[::-1]
    for k in kernel_rows:
        if k["resolution"] == "split_to_kernel" and not any(s["kernel"] == k["kernel"] for s in split):
            split.append({"part": k["note"][:300], "kernel": k["kernel"], "to": "体质修炼变更表草稿"})
    homes = [r["home"] for r in rows if r["home"].startswith("H")]
    # 第 3 步：主火位
    if emergent_homes:
        main = sorted(Counter(emergent_homes).items(), key=lambda kv: (-kv[1], int(kv[0][1:])))[0][0]
    elif homes:
        main = sorted(Counter(homes).items(), key=lambda kv: (-kv[1], int(kv[0][1:])))[0][0]
    else:
        main = cand["slot"]
    # 第 4 步：兼及火位与火组
    behavior = sorted({h for h in homes if h != main}, key=lambda s: int(s[1:]))
    also = [s for s in cand.get("also_slots", []) if s != main and s not in behavior]
    fp = dict(proposal.get("fire") or {})
    seats = [str(s) for s in fp.get("seats", [])] if main == "H1" else []
    # 第 5 步：席位（仅 H1）
    forms_now = seat_forms()
    if main == "H1":
        if not seats:
            problems.append("H1 的新形态要写席位（seats）")
        for s in seats:
            if s not in SEATS:
                problems.append(f"没有席位 {s}：新席位是体质修炼（T1/T5），拆出去")
    # 第 7 步：冲突
    by_slot_atoms: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["home"].startswith("H"):
            by_slot_atoms.setdefault(r["home"], []).append(r)
    res_prop = [dict(x) for x in proposal.get("resolutions", []) if isinstance(x, dict)]
    fire_conflicts: list[dict[str, Any]] = []
    replaced: dict[str, set[str]] = {}
    for slot in [main, *behavior]:
        slot_seats = set(seats) if slot == "H1" else None
        mine = {r["atom"] for r in by_slot_atoms.get(slot, [])}
        touched: set[str] = set()
        for r in by_slot_atoms.get(slot, []):
            for o in owners.get(r["atom"], []):
                if o.slot != slot or (slot_seats is not None and o.seat not in slot_seats):
                    continue
                r.setdefault("owner_now", o.fire)
                touched.add(o.fire)
                kind = conflict_kind(r["atom"], r.get("params", {}), o.as_dict())
                prop = next(
                    (x for x in res_prop if x.get("atom") == r["atom"] and x.get("fire") in (None, o.fire, o.fid)),
                    {},
                )
                res = str(prop.get("resolution") or DEFAULT[kind])
                note = str(prop.get("note", ""))
                if slot == "H1":
                    if res != "replace" and res != "reject":
                        note = "同一个会话角色只能有一种会话策略（按角色取），不能分开并存" + (
                            f"；{note}" if note else ""
                        )
                    res = "reject" if res == "reject" else "replace"
                elif res not in ALLOWED[kind]:
                    problems.append(f"{o.fire} 的 {r['atom']} 是{kind}冲突，不能用 {res} 化解")
                    res = DEFAULT[kind]
                row = {"fire": o.fire, "atom": r["atom"], "kind": kind, "resolution": res}
                if res == "partition":
                    pb = str(prop.get("partition_by", "")).strip()
                    if not pb:
                        problems.append(
                            f"{o.fire} 的 {r['atom']} 按分区化解，要写分区条件（开题时就确定、写进事件的量）"
                        )
                    else:
                        row["partition_by"] = pb
                if note:
                    row["note"] = note[:300]
                fire_conflicts.append(row)
                if res == "replace":
                    replaced.setdefault(slot, set()).add(o.fid)
                if res == "reject":
                    problems.append(f"{o.fire} 的 {r['atom']} 判为不收：这个候选不能入位")
        # 同一火位上（H1 为同一席位）不争同一决定的火：并存
        listed = {row["fire"] for row in fire_conflicts}
        for atom, os_ in sorted(owners.items()):
            for o in os_:
                if o.slot != slot or o.fire in listed or o.fire in touched or atom in mine:
                    continue
                if slot_seats is not None and o.seat not in slot_seats:
                    continue
                fire_conflicts.append(
                    {
                        "fire": o.fire,
                        "atom": atom,
                        "kind": "none",
                        "resolution": "coexist",
                        "note": f"新模块只负责 {'、'.join(sorted(mine)) or '无'}，与它并存",
                    }
                )
                listed.add(o.fire)
    # 第 8 步：替换谁（H1：席位上已有形态就只能替换）
    if main == "H1":
        for s in seats:
            if s in forms_now:
                replaced.setdefault("H1", set()).add(forms_now[s].partition("@")[0])
    for slot, ids in replaced.items():
        if len(ids) > 1:
            problems.append(f"{slot} 上要同时替换 {sorted(ids)}：一团火只能顶替一团")
    rep_main = sorted(replaced.get(main, set()))[0] if replaced.get(main) else None
    # 第 6 步：经脉
    baseline = set(shapes.fire_at(_live_ref(rep_main))["ports"]) if rep_main else {"M4"}
    ports = set(baseline) | {"M4"} | _tool_ports(fp.get("params", {}))
    for r in by_slot_atoms.get(main, []):
        ports |= set(atoms()[r["atom"]]["ports"])
    for s in seats:
        if s in SEATS:
            for p in sorted(ports):
                if p.startswith("M1:") and p[3:] not in SEATS[s]:
                    problems.append(f"席位 {s} 不能提交 {p[3:]}（经脉越过席位上限）")
    fire = _draft(fp, main, seats, also, ports, rep_main)
    group = []
    gprops = {str(g.get("slot")): g for g in proposal.get("group", []) if isinstance(g, dict)}
    for slot in behavior:
        gp = gprops.pop(slot, None)
        if gp is None:
            problems.append(
                f"{slot} 的行为有变（原子 {', '.join(r['atom'] for r in by_slot_atoms[slot])}），要一团火组成员"
            )
            continue
        rep = sorted(replaced.get(slot, set()))[0] if replaced.get(slot) else None
        gports = {"M4"} | set(shapes.fire_at(_live_ref(rep))["ports"] if rep else ())
        for r in by_slot_atoms[slot]:
            gports |= set(atoms()[r["atom"]]["ports"])
        group.append(_draft(gp, slot, [], [], gports, rep))
    for slot in gprops:
        problems.append(f"火组成员 {slot} 上没有任何决策原子：只读的写进兼及火位")
    new_slot = None
    if other_why:
        ns = proposal.get("new_slot")
        if not isinstance(ns, dict) or not all(ns.get(k) for k in ("name", "decides", "why_not_existing")):
            problems.append("有 other 原子：要写新火位提议（名、决定什么、为什么现有八个都不是）")
        else:
            new_slot = {k: ns[k] for k in ("name", "decides", "why_not_existing", "ports", "scattered_in") if k in ns}
    slot_locks = [{"slot": lk["slot"], "dossier": lk["dossier"]} for lk in locks if lk["slot"] in {main, *behavior}]
    existing = set(shapes.fire_ids())
    for f in [fire, *group]:
        if f["id"] in existing:
            problems.append(f"清单 id {f['id']} 已经有了：新火另起名，改旧火是本火修订")
        if not re.match(rf"^{f['slot'].lower()}\.[a-z0-9-]+$", str(f["id"])):
            problems.append(f"清单 id {f['id']!r} 要以 {f['slot'].lower()}. 开头、只用小写字母数字与连字符")
    new_tool = any(r["atom"].startswith("tool.") and "owner_now" not in r for r in rows)
    placement: dict[str, Any] = {
        "v": 1,
        "candidate": cand["id"],
        "atoms": rows,
        "fire": fire,
        "group": group,
        "replaces": rep_main,
        "arms": {},
        "readings": [],
        "conflicts": {"fires": fire_conflicts, "kernel": kernel_rows, "candidates": [], "slot_locks": slot_locks},
        "steps": [],
        "kernel_forecast": [],
        "split": split,
        "new_slot": new_slot,
        "difficulty": {"value": 1, "parts": {}},
        "checks": [],
        "plain_summary": str(proposal.get("plain_summary", ""))[:600],
    }
    deps = [str(x) for x in proposal.get("depends_on", []) if isinstance(x, str)]
    return Skeleton(placement, problems, sorted(baseline), new_tool, deps)


def _live_ref(fid: str | None) -> str:
    assert fid is not None
    return shapes.ref(fid)


def _draft(
    fp: Mapping[str, Any], slot: str, seats: list[str], also: list[str], ports: set[str], rep: str | None
) -> dict[str, Any]:
    f: dict[str, Any] = {"id": str(fp.get("id", "")), "ver": 1, "slot": slot}
    if slot == "H1":
        f["seats"] = seats
    if also:
        f["also_touches"] = also
    f["ports"] = sorted(ports, key=_port_key)
    f["params"] = copy.deepcopy(fp.get("params", {})) if isinstance(fp.get("params"), dict) else {}
    f["assets"] = [{"name": str(a["name"])} for a in fp.get("assets", []) if isinstance(a, dict) and a.get("name")]
    organ: dict[str, Any] = fp["organ"] if isinstance(fp.get("organ"), dict) else {}
    f["organ"] = {k: str(organ.get(k, "")) for k in ("class", "retire_signal", "enable_when", "control_arm")}
    if not f["organ"]["retire_signal"]:
        del f["organ"]["retire_signal"]
    f["lineage"] = {"dossier": None, "from": [rep] if rep else []}
    f["switch"] = f"fires.{slot}"
    return f


def complete(sk: Skeleton, essence: Mapping[str, Any], design: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """第 9–12 步：主丹的各臂、读数、实现步骤，加上确定性的必登读数、体质影响预判与难度。"""
    p = copy.deepcopy(sk.placement)
    problems: list[str] = []
    arms: dict[str, Any] = design["arms"] if isinstance(design.get("arms"), dict) else {}
    p["arms"] = {k: str(arms[k]) for k in ("B", "A1", "F", "B1", "A0") if k in arms and arms[k]}
    miss = [k for k in ("B", "A1", "F", "B1") if k not in p["arms"]]
    if miss:
        problems.append(f"各臂缺 {miss}")
    p["readings"], rp = readings(design.get("readings", []), essence, p)
    problems += rp
    steps = []
    for i, s in enumerate([x for x in design.get("steps", []) if isinstance(x, dict)], 1):
        row = {
            "n": i,
            "do": str(s.get("do", "")),
            "slot": str(s.get("slot", "")),
            "where": [str(w) for w in s.get("where", [])],
            "tests": [str(t) for t in s.get("tests", [])],
            "kernel_lines": s.get("kernel_lines", 0),
            "accept": str(s.get("accept", "")),
        }
        steps.append(row)
    if not steps:
        problems.append("至少写一步实现步骤")
    slots = {p["fire"]["slot"], *[g["slot"] for g in p["group"]], *p["fire"].get("also_touches", []), "meter"}
    for s in steps:
        if s["slot"] not in slots:
            problems.append(f"第 {s['n']} 步落在 {s['slot']}，不在主火位、火组或兼及火位里")
        if s["kernel_lines"] != 0:
            problems.append(f"第 {s['n']} 步预计改体质 {s['kernel_lines']} 行：要为 0，那一部分拆去体质修炼")
    p["steps"] = steps
    p["kernel_forecast"] = kernel_forecast(steps)
    if p["kernel_forecast"]:
        problems.append(f"实现步骤碰到体质路径 {p['kernel_forecast']}：退回第 2 步，把那一部分拆去体质修炼")
    finish(p, sk, essence)
    return p, problems


def finish(p: dict[str, Any], sk: Skeleton, essence: Mapping[str, Any]) -> None:
    parts = difficulty_parts(p, essence, sk.baseline_ports, new_tool=sk.new_tool)
    value, full = formulas.difficulty(parts)
    p["difficulty"] = {"value": value, "parts": full}


def readings(
    rows: Sequence[Any], essence: Mapping[str, Any], placement: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """第 10 步：主丹的读数 + 火意的新生维（门槛以火意为准）+ 必登本火维（确定性补齐，标 mandatory）。"""
    problems: list[str] = []
    keys = ("dim", "kind", "dir", "gate", "test", "run")
    given = [{k: r[k] for k in keys if k in r} for r in rows if isinstance(r, dict) and r.get("dim")]
    emergent = {e["dim"]: e for e in essence["masked"]["fusion"]["emergent"]}
    out: list[dict[str, Any]] = []
    for r in given:
        if r["dim"] in emergent:
            e = emergent[r["dim"]]
            r["kind"] = "新生"
            r["dir"] = e.get("dir", r.get("dir", "up"))
            r["gate"] = e["gate"]
            if e["measure"] == "structural" and not r.get("test"):
                problems.append(f"新生维 {r['dim']} 是结构读数，要写测试名")
            if e["measure"] == "run" and not (r.get("run") or r.get("test")):
                problems.append(f"新生维 {r['dim']} 是运行读数，要写怎么跑")
        out.append(r)
    have = {r["dim"] for r in out}
    for d in emergent:
        if d not in have:
            problems.append(f"新生维 {d} 没有登记读数")
    must = mandatory_readings(placement)
    must_dims = {m["dim"] for m in must}
    out = [r for r in out if r["dim"] not in must_dims]
    # 必登维排在最后一条非共有维之后（共有维收尾，与设计样例一致）
    at = max((i + 1 for i, r in enumerate(out) if r.get("kind") != "共有"), default=0)
    out = [*out[:at], *must, *out[at:]]
    for r in out:
        if r.get("kind") not in ("共有", "本火", "异火", "新生") or r.get("dir") not in ("up", "down"):
            problems.append(f"读数 {r['dim']} 要有 kind 与 dir")
    if not any(r.get("kind") == "共有" for r in out):
        problems.append("至少登记一维共有维（花费、墙钟、事件数一类）")
    return out, problems


# ---------------------------------------------------------------- 候选之间（08 §5.3 下表）


def relations(
    placements: Mapping[str, Mapping[str, Any]],
    depends: Mapping[str, Sequence[str]] | None = None,
    bang: Sequence[Mapping[str, Any]] = (),
    names: Mapping[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """两两比原子集合与火位：兼容、先后、依赖、互斥；另与异火榜上在途的（选中、已交实现线）比火位。"""
    names = dict(names or {})
    by_name = {v: k for k, v in names.items()}
    info = {}
    for cid, p in placements.items():
        beh = {p["fire"]["slot"], *[g["slot"] for g in p["group"]]}
        params = {a["atom"]: a.get("params", {}) for a in p["atoms"] if a["home"].startswith("H")}
        info[cid] = (beh, set(p["fire"].get("also_touches", [])), params)
    out: dict[str, list[dict[str, Any]]] = {cid: [] for cid in placements}
    ids = sorted(placements, key=lambda c: int(c[1:]))
    for i, x in enumerate(ids):
        for y in ids[i + 1 :]:
            bx, ax, px = info[x]
            by, ay, py = info[y]
            shared = sorted(set(px) & set(py))
            rel, note = "compatible", ""
            if any(conflict_kind(a, px[a], py[a]) == "semantic" for a in shared):
                rel = "exclusive"
                note = f"同一决定 {'、'.join(shared)} 上规则不同，二选一"
            elif shared:
                rel, note = "sequential", f"都改 {'、'.join(shared)}，参数不同"
            elif ax & by or ay & bx:
                rel = "sequential"
                slot = sorted((ax & by) | (ay & bx))[0]
                note = f"一方读的 {slot} 由另一方改"
            if rel != "compatible":
                out[x].append({"other": y, "relation": rel, "note": note})
                out[y].append({"other": x, "relation": rel, "note": note})
    for cid, deps in (depends or {}).items():
        for d in deps:
            other = d if d in placements else by_name.get(d)
            if other and other != cid:
                out[cid] = [r for r in out[cid] if r["other"] != other]
                out[cid].append({"other": other, "relation": "depends_on", "note": "融合设计要求对方先集成"})
    for cid in ids:
        beh, also, _ = info[cid]
        for e in bang:
            if e.get("status") not in ("selected", "handed_off"):
                continue
            if e["slot"] in also or beh & set(e.get("also_slots", [])) or e["slot"] in beh:
                out[cid].append(
                    {"other": e["id"], "relation": "sequential", "note": "候选方案里在途的一项动同一模块槽"}
                )
    return out


def order(cands: Sequence[Mapping[str, Any]], placements: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """火序（08 §6）：入位之后按重算的难度与风险重排；先后边、依赖边、火位占用、互斥对、挂起。"""
    items = []
    held: list[dict[str, Any]] = []
    for c in cands:
        if c["id"] not in placements:
            continue
        p = placements[c["id"]]
        if p.get("new_slot"):
            held.append({"candidate": c["id"], "why": "waits_structural", "note": "要先裁决新模块槽（结构修订）"})
            continue
        if p["split"]:
            held.append({"candidate": c["id"], "why": "waits_kernel_split", "note": "有一部分要先拆去内核修订"})
            continue
        d = int(p["difficulty"]["value"])
        r = "R3" if p["split"] else c["risk"]
        pr = formulas.priority(c["value"], c["confidence"], d, r)
        items.append(formulas.Item(c["id"], c["value"], c["confidence"], d, r, pr))
    live = {it.cid for it in items}
    rank = {it.cid: formulas._rank(it) for it in items}
    deps, after, excl = set(), set(), set()
    for cid in sorted(live):
        for rel in placements[cid]["conflicts"]["candidates"]:
            o = rel["other"]
            if o not in live:
                continue
            if rel["relation"] == "depends_on":
                deps.add((o, cid))
            elif rel["relation"] == "sequential":
                a, b = sorted((cid, o), key=lambda k: rank[k])
                after.add((a, b))
            elif rel["relation"] == "exclusive":
                excl.add(tuple(sorted((cid, o), key=lambda k: int(k[1:]))))
    res = formulas.fire_order(items, deps=sorted(deps), after=sorted(after), exclusive=sorted(excl))
    for h in res.held:
        held.append({"candidate": h["candidate"], "why": "exclusive_pending", "note": h["why"]})
    rows = []
    for row in res.order:
        p = placements[row["candidate"]]
        locks = [f"炼档 {lk['dossier']}" for lk in p["conflicts"]["slot_locks"]]
        if locks:
            row["waits_for"] = [*row.get("waits_for", []), *locks]
        rows.append(row)
    for cid in res.cycle:
        held.append({"candidate": cid, "why": "cycle", "note": "先后边成环：建议合成一个模块组或去掉一条边"})
    return {"order": rows, "held": held}


# ---------------------------------------------------------------- 一个候选的入位


@dataclass
class Result:
    placement: dict[str, Any]
    problems: list[str]
    tokens: dict[str, list[int]]
    depends_on: list[str]


def place(
    dan: Dan,
    cand: Mapping[str, Any],
    essence: Mapping[str, Any],
    *,
    rnd: int = 1,
    full: bool = True,
    locks: Sequence[Mapping[str, Any]] = (),
) -> Result:
    """位丹拆原子（至多 3 次，错误交回）→ 确定性骨架 →（正式）主丹写各臂、读数、步骤（至多 3 次，错误交回）。"""
    owners = ownership()
    tokens: dict[str, list[int]] = {"mid": [0, 0], "heavy": [0, 0]}
    base = f"ruwei:{cand['id']}:r{rnd}"
    errors: list[str] = []
    sk: Skeleton | None = None
    for attempt in range(1, ATTEMPTS + 1):
        r = dan.call("placer", f"{base}:place:{attempt}", placer_payload(cand, essence, errors, owners))
        tokens["mid"][0] += r.tokens_in
        tokens["mid"][1] += r.tokens_out
        prop = r.output if isinstance(r.output, dict) else {}
        sk = skeleton(cand, essence, prop, owners=owners, locks=locks)
        if not sk.problems:
            break
        errors = list(sk.problems)
    assert sk is not None
    if not full or sk.problems:
        p = copy.deepcopy(sk.placement)
        finish(p, sk, essence)
        return Result(p, list(sk.problems), tokens, sk.depends_on)
    errors = []
    placement: dict[str, Any] = {}
    problems: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        r = dan.call("main", f"{base}:design:{attempt}", design_payload(sk.placement, essence, errors))
        tokens["heavy"][0] += r.tokens_in
        tokens["heavy"][1] += r.tokens_out
        design = r.output if isinstance(r.output, dict) else {}
        placement, problems = complete(sk, essence, design)
        if not problems:
            break
        errors = list(problems)
    return Result(placement, problems, tokens, sk.depends_on)


def conflict_lines(p: Mapping[str, Any]) -> list[str]:
    """试算报告与人读报告里的冲突一行一条。"""
    lines = [_plain_conflict(c) for c in p["conflicts"]["fires"]]
    lines += [
        f"{k['kernel']}：split_to_kernel" for k in p["conflicts"]["kernel"] if k["resolution"] == "split_to_kernel"
    ]
    return [x[:300] for x in lines]


def likely_outcome(essence: Mapping[str, Any], p: Mapping[str, Any]) -> tuple[str, str]:
    """试算的“可能的结局”（09 §3）：只是预判，不进读数。"""
    fusion = essence["masked"]["fusion"]
    em = fusion["emergent"]
    a1_ok = not str(p.get("arms", {}).get("A1", "")).startswith(INFEASIBLE) and fusion.get("outcome_cap") != "helian"
    if em and all(e.get("why_zero_B") and e.get("why_zero_A1") for e in em) and a1_ok:
        runs = sum(1 for e in em if e.get("measure") == "run")
        if not runs:
            why = f"{'两' if len(em) == 2 else len(em)}条新增指标都有基线与照搬为零的理由，且是结构读数"
        else:
            why = f"{len(em) - runs} 条新增指标是结构读数，{runs} 条要靠运行读数"
        return "promising_huolian", why
    if em or fusion.get("statement"):
        return "at_most_helian", "新增指标不成立或照搬做不出，最多是全面提升"
    return "maybe_binghuo", "写不出任何一项会胜过照搬的指标"


def kernel_areas(p: Mapping[str, Any]) -> list[str]:
    """试算没有实现步骤：按拆出的体质项给可能触到的体质路径。"""
    out: set[str] = set()
    for s in p["split"]:
        out |= set(KERNEL_AREAS.get(s["kernel"], []))
    return sorted(out)
