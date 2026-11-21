"""萃意的八条检验 K1–K8 与产物校验器 V1–V12（docs/design/fenjue/08-algorithms.md §4.3，09 §7）。

校验器是量具，归药鼎：代码在 `paoding_fenjue`，不在引擎火的资产里，引擎的升级改不到它。两道：交付前（工具面的
`check`）与导入炼档时（`lianhua.py import`，E2）用的是同一组函数。

K 检验只对遮蔽视图做；K6 是读数（advisory），其余是硬门（EN8）。V 检验对整份产物做。
"""

from __future__ import annotations

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
        result("V5", _plain(doc.get("plain_summary", ""))),
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
    v5 = _plain(doc.get("plain_summary", "")) + [h for s in masked_strings for h in text.code_structure_hits(s)]
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


def _plain(summary: str) -> list[str]:
    return [f"给人看的摘要里有内部名词 {t}" for t in data.table("vocab")["internal_terms"] if t in summary]


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
