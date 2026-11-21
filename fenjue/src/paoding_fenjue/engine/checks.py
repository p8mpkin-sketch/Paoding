"""萃意的八条检验 K1–K8 与产物校验器 V1–V12（docs/design/fenjue/08-algorithms.md §4.3，09 §7）。

校验器是量具，归药鼎：代码在 `paoding_fenjue`，不在引擎火的资产里，引擎的升级改不到它。两道：交付前（工具面的
`check`）与导入炼档时（`lianhua.py import`，E2）用的是同一组函数。

K 检验只对遮蔽视图做；K6 是读数（advisory），其余是硬门（EN8）。V 检验对整份产物做。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import data, formulas, schema, text

LCS_MAX = 12  # 最长公共片段 < 12 词元〔占位〕
NGRAM_MAX = 0.02  # 8 元组重合率 < 2%〔占位〕


@dataclass
class Context:
    """检验要用的本次运行的材料：外部专名表、快照原文的词元、观察库、许可证、金丝雀。"""

    names: list[str]
    corpus: list[list[str]]
    observations: Mapping[str, Mapping[str, Any]]
    license: Mapping[str, Any]
    canaries: Sequence[str] = ()
    out_of_scope_requests: int = 0
    grams: set[tuple[str, ...]] = field(default_factory=set)

    def __post_init__(self) -> None:
        for seq in self.corpus:
            self.grams |= text.ngrams(seq)


def result(cid: str, problems: Sequence[str], *, advisory: bool = False, ok: bool | None = None) -> dict[str, Any]:
    r: dict[str, Any] = {"id": cid, "ok": (not problems) if ok is None else ok}
    if advisory:
        r["advisory"] = True
    if problems:
        r["detail"] = "；".join(problems)[:600]
    return r


def _copy_problems(strings: Iterable[str], ctx: Context) -> list[str]:
    out = []
    for s in strings:
        toks = text.tokens(s)
        run = max((text.longest_common_run(toks, seq) for seq in ctx.corpus), default=0)
        if run >= LCS_MAX:
            out.append(f"与原文有 {run} 词元的公共片段：{s[:40]}")
        elif text.ngram_overlap(toks, ctx.grams) >= NGRAM_MAX:
            out.append(f"8 元组与原文重合过多：{s[:40]}")
    return out


# ---------------------------------------------------------------- K1–K8


def k_checks(essence: Mapping[str, Any], ctx: Context, blind_guess: str | None) -> list[dict[str, Any]]:
    m = essence.get("masked", {})
    strings = text.free_text(m)
    return [
        result("K1", _k1(m)),
        result("K2", _k2(strings, ctx)),
        result("K3", [h for s in strings for h in text.code_structure_hits(s)]),
        result("K4", _copy_problems(strings, ctx)),
        result("K5", _k5(essence)),
        _k6(blind_guess, ctx),
        result("K7", _k7(m)),
        result("K8", _k8(strings)),
    ]


def _k1(m: Mapping[str, Any]) -> list[str]:
    out = schema.def_errors(m, "essence", "masked")
    if out:
        return out
    prims = data.primitives()
    for s in m["mechanism"]:
        bad = [p for p in s.get("primitives", []) if p not in prims]
        if bad:
            out.append(f"机制第 {s['step']} 步用了原语表之外的词 {bad}")
    for i, impl in enumerate(m["implementations"]):
        bad = [p for p in impl["primitives"] if p not in prims]
        if bad:
            out.append(f"实现草图 {i + 1} 用了原语表之外的词 {bad}")
    feats = {f for s in m["mechanism"] for f in s.get("features", [])}
    kernel_conflicts = {c["with"] for c in m["conflicts"] if c["kind"] == "kernel"}
    split_kernel = {s["kernel"] for s in m["split"]}
    for f in sorted(feats):
        row = data.features()[f]
        if row["kernel"] not in kernel_conflicts:
            out.append(f"特征 {f} 映到 {row['kernel']}，冲突栏里没有对应的体质冲突")
        if row["gate"] and row["kernel"] not in split_kernel:
            out.append(f"特征 {f} 有守门性质，拆分栏里没有 {row['kernel']}")
    for c in m["conflicts"]:
        if c["kind"] == "kernel" and c["resolution"] not in ("fused_away", "split_to_kernel", "reject"):
            out.append(f"与 {c['with']} 的体质冲突没有化解（{c['resolution']}）")
    return out


def _k2(strings: Sequence[str], ctx: Context) -> list[str]:
    generic = [text.fold(n) for n in data.table("generic-names")["names"]]
    hits: set[str] = set()
    for s in strings:
        hits.update(text.name_hits(s, ctx.names))
        hits.update(text.name_hits(s, generic))
    return [f"外部专名 {h}" for h in sorted(hits)]


def _k5(essence: Mapping[str, Any]) -> list[str]:
    m = essence.get("masked", {})
    refs: Mapping[str, Sequence[str]] = essence.get("field_refs", {})
    known = set(essence.get("provenance", {}).get("observations", []))
    out = []
    for key in ("premises", "costs", "conflicts"):
        for i, _ in enumerate(m.get(key, [])):
            ptr = f"/{key}/{i}"
            got = refs.get(ptr, [])
            if not got:
                out.append(f"{ptr} 没有挂观察")
            elif not set(got) <= known:
                out.append(f"{ptr} 挂的观察不在出处里：{sorted(set(got) - known)}")
    for e in m.get("fusion", {}).get("emergent", []):
        if not e.get("why_zero_B", "").strip() or not e.get("why_zero_A1", "").strip():
            out.append(f"新生维 {e.get('dim')} 缺“按构造为零”的理由")
    return out


def _k6(guess: str | None, ctx: Context) -> dict[str, Any]:
    if guess is None:
        return {"id": "K6", "ok": True, "advisory": True, "detail": "未调盲审"}
    hits = text.name_hits(guess, ctx.names)
    if hits:
        return {"id": "K6", "ok": False, "advisory": True, "detail": f"可猜：盲审猜中了 {', '.join(hits)}"}
    return {"id": "K6", "ok": True, "advisory": True, "detail": "盲审未猜中出处"}


def _k7(m: Mapping[str, Any]) -> list[str]:
    impls = m.get("implementations", [])
    if len(impls) < 2:
        return ["实现草图不足两种"]
    sets = [frozenset(i.get("primitives", [])) for i in impls]
    same = [(a + 1, b + 1) for a in range(len(sets)) for b in range(a + 1, len(sets)) if sets[a] == sets[b]]
    return [f"实现草图 {a} 与 {b} 的原语集合相同" for a, b in same]


def _k8(strings: Sequence[str]) -> list[str]:
    out = []
    hidden = set(data.table("injection")["hidden_unicode"])
    for s in strings:
        if any(c in hidden for c in s):
            out.append(f"隐藏字符：{text.without_hidden(s)[:40]}")
        out += [f"指令痕迹 {h}" for h in text.instruction_hits(text.without_hidden(s))]
    return out


def hard_ok(checks: Iterable[Mapping[str, Any]]) -> bool:
    """硬门（除 K6 外）是否全过；cz 坚持过的（override）算过。"""
    return all(c["ok"] or c.get("advisory") or c.get("override") for c in checks)


# ---------------------------------------------------------------- V1–V12


NOT_HERE = "本步不适用（入位与交接之后才有）"


def v_candidates(doc: Mapping[str, Any], ctx: Context) -> list[dict[str, Any]]:
    """候选火清单的校验（闸点 1 交付之前）。"""
    cands = doc.get("candidates", [])
    return [
        result("V1", schema.errors(doc, "candidates")),
        result("V2", _dupes([c["id"] for c in cands])),
        result("V3", _v3_candidates(doc, ctx)),
        result("V4", _v4_candidates(cands, ctx)),
        result("V5", _plain(displayed(doc, "candidates"))),
        result("V6", _copy_problems(_human_strings(doc), ctx) + _fences(doc)),
        result("V7", _v7(doc, ctx)),
        {"id": "V8", "ok": True, "detail": NOT_HERE},
        {"id": "V9", "ok": True, "detail": NOT_HERE},
        {"id": "V10", "ok": True, "detail": NOT_HERE},
        result("V11", []),
        result("V12", _v12(doc, ctx)),
    ]


def v_essence(doc: Mapping[str, Any], ctx: Context, picked: Sequence[str]) -> list[dict[str, Any]]:
    """火意的校验（闸点 2 交付之前）。"""
    masked_strings = text.free_text(doc.get("masked", {}))
    v5 = _plain(displayed(doc, "essence")) + [h for s in masked_strings for h in text.code_structure_hits(s)]
    v5 += [f"外部专名 {h}" for s in masked_strings for h in text.name_hits(s, ctx.names)]
    v5 += [h for s in masked_strings for h in text.instruction_hits(s)]
    return [
        result("V1", schema.errors(doc, "essence")),
        result("V2", _dupes([p["id"] for p in doc.get("masked", {}).get("premises", [])])),
        result(
            "V3",
            [
                f"观察 {o} 不在观察库里"
                for o in doc.get("provenance", {}).get("observations", [])
                if o not in ctx.observations
            ],
        ),
        {"id": "V4", "ok": True, "detail": "火意没有公式栏"},
        result("V5", v5),
        result("V6", _copy_problems(list(text.strings(doc)), ctx) + _fences(doc)),
        result("V7", _v7(doc, ctx)),
        {"id": "V8", "ok": True, "detail": NOT_HERE},
        {"id": "V9", "ok": True, "detail": NOT_HERE},
        {"id": "V10", "ok": True, "detail": NOT_HERE},
        result("V11", [] if doc.get("candidate") in picked else [f"{doc.get('candidate')} 不在闸点 1 选中的候选里"]),
        result("V12", _v12(doc, ctx)),
    ]


def _dupes(ids: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for i in ids:
        if i in seen:
            out.append(f"编号重复 {i}")
        seen.add(i)
    return out


def _v3_candidates(doc: Mapping[str, Any], ctx: Context) -> list[str]:
    out = []
    active = data.active_refs()
    cited: set[str] = set()
    for c in doc.get("candidates", []):
        for g in c["gaps"]:
            if g["type"] != "new_dim" and g["dim"] not in data.dims():
                out.append(f"{c['id']}：能力维 {g['dim']} 不在剖面里")
            if g.get("ours_by") and g["ours_by"] not in active:
                out.append(f"{c['id']}：{g['ours_by']} 不在功法里")
            cited.update(g["observations"])
        cited.update(c["provenance"]["observations"])
    for a in doc.get("already_have", []):
        cited.update(a["observations"])
        if a.get("by") and a["by"] not in active:
            out.append(f"已有不差 {a['dim']}：{a['by']} 不在功法里")
    out += [f"观察 {o} 不在观察库里" for o in sorted(cited) if o not in ctx.observations]
    return out


def _v4_candidates(cands: Sequence[Mapping[str, Any]], ctx: Context) -> list[str]:
    out = []
    for c in cands:
        for g in c["gaps"]:
            again = formulas.gap(g["dim"], g["theirs"])
            if (again["ours"], again["gap"], again["type"]) != (g["ours"], g["gap"], g["type"]):
                out.append(f"{c['id']}.{g['dim']}：差距重算为 {again['type']} {again['gap']}")
        v = formulas.value(c["gaps"])
        obs_by_dim = {
            g["dim"]: [ctx.observations[o] for o in g["observations"] if o in ctx.observations] for g in c["gaps"]
        }
        conf, _ = formulas.confidence([g["dim"] for g in c["gaps"]], obs_by_dim)
        d, _ = formulas.difficulty(c.get("difficulty_parts", {}))
        p = formulas.priority(v, conf, d, c["risk"])
        for name, mine, theirs in (("V", v, c["value"]), ("C", conf, c["confidence"]), ("D", d, c["difficulty"])):
            if abs(mine - theirs) > 1e-9:
                out.append(f"{c['id']}：{name} 重算为 {mine}，产物写的是 {theirs}")
        if abs(p - c["priority"]) > 1e-9:
            out.append(f"{c['id']}：P 重算为 {p}，产物写的是 {c['priority']}")
    ranked = sorted(cands, key=lambda c: (-c["priority"], data.RISK_LEVEL[c["risk"]], c["difficulty"], c["name"]))
    if [c["id"] for c in ranked] != [f"C{i}" for i in range(1, len(cands) + 1)]:
        out.append("候选编号与优先级次序不一致")
    return out


def _plain(strings: str | Iterable[str]) -> list[str]:
    """E-U4：给人看的自由文本栏（不只 plain_summary）不出现内部设计名词，用常规技术词。"""
    rows = [strings] if isinstance(strings, str) else list(strings)
    out = []
    for t in data.table("vocab")["internal_terms"]:
        hit = next((s for s in rows if t in s), None)
        if hit is not None:
            out.append(f"给人看的文字里有内部名词 {t}：{hit[:30]}")
    return out


def displayed(doc: Mapping[str, Any], kind: str) -> list[str]:
    """界面会显示的自由文本栏（engine-ui §4–§5）。受控枚举、编号、清单草稿与炼档八栏不在其中：
    枚举由界面映射，清单与炼档是给实现线看的仓库文件。"""
    out: list[str] = [str(doc.get("plain_summary", ""))]
    if kind == "candidates":
        for c in doc.get("candidates", []):
            sh = c.get("seed", {}).get("shihuo", {})
            out += [c.get("title", ""), c.get("recommend", {}).get("why", ""), c.get("dedupe", {}).get("note", "")]
            out += [str(sh.get(k, "")) for k in ("phenomenon", "gap", "is_fire")]
        for n in doc.get("not_fire", []):
            out += [n.get("what", ""), n.get("why", "")]
    elif kind == "essence":
        out += list(text.free_text(doc.get("masked", {})))
        out += list(doc.get("drafts", {}).get("disagreements", []))
    elif kind == "placement":
        out += [str(v) for v in doc.get("arms", {}).values()]
        for r in doc.get("readings", []):
            out += [str(r.get(k, "")) for k in ("dim", "gate", "run")]
        conf = doc.get("conflicts", {})
        for row in [*conf.get("fires", []), *conf.get("kernel", []), *conf.get("candidates", [])]:
            out += [str(row.get("note", "")), str(row.get("partition_by", ""))]
        for st in doc.get("steps", []):
            out += [st.get("do", ""), st.get("accept", "")]
        out += [s.get("part", "") for s in doc.get("split", [])]
        if doc.get("new_slot"):
            out += [str(v) for k, v in doc["new_slot"].items() if isinstance(v, str)]
    elif kind == "dry_run":
        for it in doc.get("items", []):
            out += [it.get("why", ""), *it.get("conflicts", [])]
            out += list(text.free_text(it.get("essence_draft", {})))
    elif kind == "handoff":
        out += [o.get("why", "") for o in doc.get("order", [])]
        out += [h.get("note", "") for h in doc.get("held", [])]
    return [s for s in out if s]


def _human_strings(doc: Mapping[str, Any]) -> list[str]:
    out = [doc.get("plain_summary", "")]
    for c in doc.get("candidates", []):
        out += list(text.strings(c["seed"])) + [c["title"], c["recommend"]["why"]]
    return [s for s in out if s]


def _fences(doc: Mapping[str, Any]) -> list[str]:
    return ["出现代码围栏"] if any("```" in s for s in text.strings(doc)) else []


def _v7(doc: Mapping[str, Any], ctx: Context) -> list[str]:
    snaps: list[Mapping[str, Any]] = []
    if "basis" in doc:
        snaps += doc["basis"]["snapshots"]
    for c in doc.get("candidates", []):
        snaps += c["provenance"]["snapshots"]
    if "provenance" in doc:
        snaps += doc["provenance"]["snapshots"]
    if not snaps:
        return ["没有出处与许可证状态"]
    want = (ctx.license.get("status"), ctx.license.get("spdx"))
    return [
        f"快照 {s['id']} 的许可证与勘察结果不一致"
        for s in snaps
        if (s["license"]["status"], s["license"].get("spdx")) != want
    ]


def _v12(doc: Mapping[str, Any], ctx: Context) -> list[str]:
    blob = text.fold(" ".join(text.strings(doc)))
    out = [f"产物里出现金丝雀 {c}" for c in ctx.canaries if text.fold(c) in blob]
    if ctx.out_of_scope_requests:
        out.append(f"越出立项来源的扩权申请 {ctx.out_of_scope_requests} 次")
    return out


# ---------------------------------------------------------------- 入位方案与试算报告（V8–V10 在这里才适用）

_BUDGET_KEY = re.compile(r"(usd|milli|budget|token|cost|price|dollar|金额|预算|花费)", re.I)
_BUDGET_VAL = re.compile(r"(\$\s*\d|\d[\d,_]*\s*(tokens?|美元|元|usd)\b)", re.I)


def budget_numbers(obj: Any, path: str = "") -> list[str]:
    """V8 的后半：清单的 params 里不写预算绝对值（金额、token 数一类的键名与数值模式；01 §8）。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if _BUDGET_KEY.search(str(k)) and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(f"params.{here} 是预算绝对值")
            out += budget_numbers(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += budget_numbers(v, f"{path}.{i}")
    elif isinstance(obj, str) and _BUDGET_VAL.search(obj):
        out.append(f"params.{path} 写了金额或 token 数")
    return out


def v8(p: Mapping[str, Any]) -> list[str]:
    from .. import shapes

    out = []
    for f in [p.get("fire", {}), *p.get("group", [])]:
        out += shapes.check(dict(f))
        out += budget_numbers(f.get("params", {}))
    return out


def v9(p: Mapping[str, Any], essence: Mapping[str, Any], *, steps_required: bool = True) -> list[str]:
    from . import ruwei

    out = []
    if p.get("kernel_forecast"):
        out.append(f"体质影响预判不为空：{p['kernel_forecast']}")
    again = ruwei.kernel_forecast(p.get("steps", []))
    if again:
        out.append(f"实现步骤碰到体质路径：{again}")
    if steps_required and not p.get("steps"):
        out.append("没有实现步骤")
    out += [s for s in ruwei.kernel_issues(essence, p)] if "conflicts" in p and "split" in p else []
    return out


def v10(p: Mapping[str, Any], essence: Mapping[str, Any]) -> list[str]:
    from . import ruwei

    out = []
    rows = {r["dim"]: r for r in p.get("readings", [])}
    for e in essence.get("masked", {}).get("fusion", {}).get("emergent", []):
        r = rows.get(e["dim"])
        if r is None or r.get("kind") != "新生":
            out.append(f"新生维 {e['dim']} 没有预登记")
        elif r.get("gate") is None:
            out.append(f"新生维 {e['dim']} 没有门槛")
        if not (e.get("why_zero_B") and e.get("why_zero_A1")):
            out.append(f"新生维 {e['dim']} 缺“按构造为零”的理由")
    for m in ruwei.mandatory_readings(p):
        if m["dim"] not in rows:
            out.append(f"必登的 {m['dim']} 没有登记")
    return out


def _v3_placement(p: Mapping[str, Any]) -> list[str]:
    from .. import shapes

    active = data.active_refs()
    ids = {r.partition("@")[0] for r in active}
    out = [
        f"{a['atom']} 的拥有者 {a['owner_now']} 不在功法里"
        for a in p["atoms"]
        if a.get("owner_now") not in (None, *active)
    ]
    out += [f"冲突对象 {c['fire']} 不在功法里" for c in p["conflicts"]["fires"] if c["fire"] not in active]
    for f in [p["fire"], *p["group"]]:
        out += [f"{f['id']} 顶替的 {x} 不是生效的火" for x in f["lineage"]["from"] if x not in ids]
    if p.get("replaces") and p["replaces"] not in ids:
        out.append(f"替换的 {p['replaces']} 不是生效的火")
    out += [f"{x} 已有同名清单" for x in (p["fire"]["id"], *[g["id"] for g in p["group"]]) if x in shapes.fire_ids()]
    return out


def v_placement(
    p: Mapping[str, Any], essence: Mapping[str, Any], ctx: Context, confirmed: Sequence[str]
) -> list[dict[str, Any]]:
    """入位方案的校验（闸点 3 交付之前，导入时再跑一遍）。"""
    d, _ = formulas.difficulty(p.get("difficulty", {}).get("parts", {}))
    v4 = [] if d == p.get("difficulty", {}).get("value") else [f"难度重算为 {d}"]
    dims = [r["dim"] for r in p.get("readings", [])]
    return [
        result("V1", schema.errors(p, "placement")),
        result("V2", _dupes(dims) + _dupes([str(s["n"]) for s in p.get("steps", [])])),
        result("V3", _v3_placement(p)),
        result("V4", v4),
        result("V5", _plain(displayed(p, "placement"))),
        result("V6", _copy_problems(list(text.strings(p)), ctx) + _fences(p)),
        result("V7", _v7(essence, ctx)),
        result("V8", v8(p)),
        result("V9", v9(p, essence)),
        result("V10", v10(p, essence)),
        result("V11", [] if p.get("candidate") in confirmed else [f"{p.get('candidate')} 没有在闸点 2 确认"]),
        result("V12", _v12(p, ctx)),
    ]


def v_dry_run(doc: Mapping[str, Any], ctx: Context) -> list[dict[str, Any]]:
    """试算报告：全部校验照跑，只标不拦（09 §3）。"""
    picked = set(doc.get("auto_picked", []))
    return [
        result("V1", schema.errors(doc, "dry-run")),
        result("V2", _dupes([it["candidate"] for it in doc.get("items", [])])),
        result("V3", _v3_candidates(doc.get("candidates", {}), ctx)),
        result("V4", _v4_candidates(doc.get("candidates", {}).get("candidates", []), ctx)),
        result("V5", _plain(displayed(doc, "dry_run"))),
        result("V6", _copy_problems([s for it in doc.get("items", []) for s in text.strings(it)], ctx) + _fences(doc)),
        result("V7", _v7(doc.get("candidates", {}), ctx)),
        {"id": "V8", "ok": True, "detail": "试算不写清单草稿"},
        result(
            "V9",
            [
                f"{it['candidate']} 可能触到内核 {it['kernel_forecast']}"
                for it in doc.get("items", [])
                if it["kernel_forecast"]
            ],
        ),
        {"id": "V10", "ok": True, "detail": "试算不预登记读数"},
        result(
            "V11",
            [f"{it['candidate']} 不在自动取的候选里" for it in doc.get("items", []) if it["candidate"] not in picked],
        ),
        result("V12", _v12(doc, ctx)),
    ]
