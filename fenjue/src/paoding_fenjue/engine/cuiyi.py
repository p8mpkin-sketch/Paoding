"""萃意（docs/design/fenjue/08-algorithms.md §4.2）：每个选中的候选出一份火意。

主丹一稿、两颗萃丹各一稿（不看主丹的稿，只看观察与 Schema），三稿都跑 K1–K8 的硬门；过了的里面取与另两稿
“能力维集合 + 新生维集合”的 Jaccard 之和最大的一稿，平局取本质句最短的；分歧点列给 cz。都不过就把错误清单交回
主丹重写，至多 2 次；仍不过，交 cz 时标“未过”及原因。盲审丹只看遮蔽视图（K6，读数）。

确定性的几步（取证、重叠、守门拆分的核对、检验）在这里；机制骨架、前提、代价、融合假设由丹写。
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import checks, data, pills, sections
from .dan import Dan, reading

ATTEMPTS = 3
DRAFTS = ("main", "extra1", "extra2")
DRAFT_ZH = {"main": "主稿", "extra1": "第二稿", "extra2": "第三稿"}  # 给人看的（E-U4）：不用内部名词


def evidence(cand: Mapping[str, Any], observations: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """第 1 步取证：该候选的全部观察；带 suspected_injection 的只在有未标记的观察互证时才参与。"""
    ids = cand["provenance"]["observations"]
    obs = [dict(observations[o]) for o in ids if o in observations]
    clean = [o for o in obs if not o["suspected_injection"]]
    keep = []
    for o in obs:
        if o["suspected_injection"] and not any(set(c.get("dims", [])) & set(o.get("dims", [])) for c in clean):
            continue
        keep.append({k: v for k, v in o.items() if k != "reader"})
    return keep


def overlaps(dims: Sequence[str]) -> list[dict[str, Any]]:
    """第 5 步重叠（确定性）：火意涉及的能力维 ∩ 剖面里生效火的维。"""
    by: dict[str, list[str]] = {}
    for d in dims:
        row = data.dims().get(d)
        if row and row.get("by") and row["level"] > 0:
            by.setdefault(row["by"], []).append(d)
    return [{"fire": f, "dims": sorted(ds)} for f, ds in sorted(by.items())]


def _payload(
    cand: Mapping[str, Any], obs: Sequence[Mapping[str, Any]], role: str, errors: Sequence[str]
) -> dict[str, Any]:
    p: dict[str, Any] = {
        "template": f"cuiyi/{role}/v1",
        "candidate": {k: cand[k] for k in ("id", "name", "title", "slot", "also_slots", "gaps") if k in cand},
        "observations": list(obs),
        "primitives": sorted(data.primitives()),
        "features": sorted(data.features()),
        "overlap_hint": overlaps([g["dim"] for g in cand["gaps"]] + [d for o in obs for d in o.get("dims", [])]),
        "schema": "essence.schema.json#/$defs/masked",
    }
    if errors:
        p["errors"] = list(errors)
    return p


def _elements(masked: Mapping[str, Any]) -> set[str]:
    # 进门时形状不对的栏已经没收（sections.sound）：在的栏都读得动，不在的按空算
    dims = {f"dim:{d}" for o in masked.get("overlaps", []) for d in o.get("dims", [])}
    new = {f"new:{e['dim']}" for e in masked.get("fusion", {}).get("emergent", [])}
    return dims | new


def _jac(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


@dataclass
class Draft:
    name: str
    body: dict[str, Any]
    checks: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return checks.hard_ok(self.checks)


def _as_essence(cand: Mapping[str, Any], out: Any) -> tuple[dict[str, Any], list[str]]:
    """模型的回答 → 火意的壳，外加形状上的问题（空列表即九栏的形状都对）。

    遮蔽视图只收形状对的栏（`sections.sound`）：收下的每一栏后面的检验都读得动；没收下的就是“缺”，由 K1 照实报。"""
    if not isinstance(out, dict):
        return {"v": 1, "candidate": cand["id"], "masked": {}, "provenance": copy.deepcopy(cand["provenance"])}, []
    masked, dropped = sections.sound(out.get("masked"))
    refs = out.get("field_refs")
    body = {
        "v": 1,
        "candidate": cand["id"],
        "masked": masked,
        "provenance": copy.deepcopy(cand["provenance"]),
        "field_refs": refs if isinstance(refs, dict) else {},
        "plain_summary": str(out.get("plain_summary", ""))[:600],
    }
    shape = [sections.shape_error(out, masked), *dropped] if sections.structural(masked) or dropped else []
    return body, shape


@dataclass
class Result:
    essence: dict[str, Any]
    passed: bool
    tokens: dict[str, list[int]]
    reason: str = ""  # 九栏不齐（缺必填栏、类型不对）时给人看的原因：缺什么、收到的是什么；齐全就是空


def gaps_reason(essence: Mapping[str, Any], received: str = "") -> str:
    """九栏不齐时给人看的一句：缺什么，带上模型实际交回的顶层键；齐全就是空串。

    只管结构这一类（`sections.gaps`）。K1 里别的规则没过（用词不在表内、栏目之间对不上）不算“提炼不出”：
    九栏都在、下游读得动，照常往下走，由检验结果自己标“未过”。"""
    detail = sections.describe(essence)
    if not detail:
        return ""
    return (detail[:300] + (f"（收到的顶层键：{received}）" if received else ""))[:400]


def distill(
    dan: Dan,
    cand: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
    ctx: checks.Context,
    *,
    rnd: int = 1,
    dry: bool = False,
) -> Result:
    """一个候选的萃意（第 1–10 步）。`rnd` 是第几轮（cz 在闸点 2 退回重做时加一），进丹调用的键。

    `dry`（试算，09 §3）：只要主稿一稿；K2–K5、K7 照跑，不过只标不重写；K1（结构）、K8（指令痕迹）与内部名词
    不过照样重写——结构不对的稿子下游读不动，不能“只标”。不调萃丹与盲审。

    重写用完仍不过，分两类：九栏不齐（缺必填栏、类型不对）的 `Result.reason` 写明缺什么，调用方按 `sections.gaps`
    不让它进归位；九栏齐全而 K1 的其余规则（用词、栏目之间的一致性）没过的，`reason` 为空，照常进归位，
    检验结果里标着。"""
    obs = evidence(cand, observations)
    tokens: dict[str, list[int]] = {"heavy": [0, 0], "mid": [0, 0]}
    seen: dict[str, str] = {}  # 稿名 → 模型实际交回的顶层键（写原因用）

    def ask(role: str, key: str, name: str, errors: Sequence[str]) -> tuple[Draft, str, list[str]]:
        """问一次。交回（稿子，类别 content / truncated / refused / not_json，要交回给模型的形状问题）。"""
        r = dan.call(role, key, _payload(cand, obs, role, errors))
        tier = "mid" if role == "blind" else "heavy"
        tokens[tier][0] += r.tokens_in
        tokens[tier][1] += r.tokens_out
        with reading(key):
            body, shape = _as_essence(cand, r.output)
            draft = Draft(name, body, checks.k_checks(body, ctx, None))
            seen[name] = sections.received(r.output)
        if isinstance(r.output, dict):
            return draft, "content", shape
        kind, msg = pills.empty_reply(r, f"cuiyi/{role}/v1")
        return draft, kind, [msg]

    base = f"cuiyi:{cand['id']}:r{rnd}"
    errors: list[str] = []
    content_errors: list[str] = []  # 最近一次有内容的稿子没通过的问题；空手而归的下一次也要带上
    main: Draft | None = None
    for attempt in range(1, ATTEMPTS + 1):
        draft, kind, shape = ask("main", f"{base}:main:{attempt}", "main", errors)
        if kind != "content":
            main = main or draft  # 留着上一份有内容的稿子；一份都没有才用这份空的
            if kind == "refused":
                break
            errors = [*content_errors, *shape]
            continue
        main = draft
        # 给人看的栏里的内部名词（V5 的同一张表同一个函数）：写出来就交回重写，不等到校验报“未过”（dry 也一样）
        vocab = checks._plain(checks.displayed(main.body, "essence"))
        if main.ok and not vocab:
            break
        if dry and all(c["ok"] for c in main.checks if c["id"] in ("K1", "K8")) and not vocab:
            break  # 试算只标不重写；例外：结构（K1）、指令痕迹（K8，11 §5 N3）与内部名词，都不能带进产物
        errors = [*shape]
        errors += [f"{c['id']}：{c.get('detail', '')}" for c in main.checks if not c["ok"] and not c.get("advisory")]
        errors += [f"V5：{v}（换成常规的技术词）" for v in vocab]
        content_errors = list(errors)
    assert main is not None
    if dry:
        ess = main.body
        ess["drafts"] = {"n": 1, "chosen": "main", "agreement": 0}
        ess["checks"] = [c for c in main.checks if c["id"] != "K6"]
        ess = {
            k: ess[k]
            for k in ("v", "candidate", "masked", "provenance", "field_refs", "drafts", "checks", "plain_summary")
            if k in ess
        }
        return Result(ess, checks.hard_ok(ess["checks"]), tokens, gaps_reason(ess, seen.get("main", "")))
    extras = []
    for name in DRAFTS[1:]:
        d, _, _ = ask("extra", f"{base}:{name}", name, [])
        extras.append(d)
    drafts = [main, *extras]
    passing = [d for d in drafts if d.ok]
    # 都不过时交主稿（标“未过”）；主稿连九栏都不齐而另有齐的，取齐的那份——不齐的稿子人没法逐栏改
    whole = [d for d in drafts if not sections.gaps(d.body)]
    pool = passing or ([main] if not whole or any(d is main for d in whole) else whole[:1])
    elems = {d.name: _elements(d.body["masked"]) for d in drafts}

    def agreement(d: Draft) -> float:
        return round(sum(_jac(elems[d.name], elems[o.name]) for o in drafts if o.name != d.name), 4)

    chosen = sorted(
        pool, key=lambda d: (-agreement(d), len(d.body["masked"].get("statement", "")), DRAFTS.index(d.name))
    )[0]
    disagreements = []
    for d in drafts:
        if d.name == chosen.name:
            continue
        for x in sorted(elems[chosen.name] - elems[d.name]):
            kind, _, label = x.partition(":")
            disagreements.append(f"{DRAFT_ZH[d.name]}没有“{label}”这一{'新生维' if kind == 'new' else '能力维'}")
        for x in sorted(elems[d.name] - elems[chosen.name]):
            kind, _, label = x.partition(":")
            disagreements.append(f"{DRAFT_ZH[d.name]}多出“{label}”这一{'新生维' if kind == 'new' else '能力维'}")
    guess = None
    if not sections.gaps(chosen.body):  # 九栏不齐的稿子没有可盲审的内容：不花这一次调用，K6 记“未调盲审”
        br = dan.call("blind", f"{base}:blind", {"template": "cuiyi/blind/v1", "masked": chosen.body["masked"]})
        tokens["mid"][0] += br.tokens_in
        tokens["mid"][1] += br.tokens_out
        guess = br.output.get("guess") if isinstance(br.output, dict) else None
    ess = chosen.body
    ess["drafts"] = {"n": len(drafts), "chosen": chosen.name, "agreement": agreement(chosen)}
    if disagreements:
        ess["drafts"]["disagreements"] = [s[:300] for s in disagreements]
    ess["checks"] = checks.k_checks(ess, ctx, str(guess) if guess is not None else None)
    ess = {
        k: ess[k]
        for k in ("v", "candidate", "masked", "provenance", "field_refs", "drafts", "checks", "plain_summary")
        if k in ess
    }
    return Result(ess, checks.hard_ok(ess["checks"]), tokens, gaps_reason(ess, seen.get(chosen.name, "")))


# ---------------------------------------------------------------- 闸点 2 的逐栏修改

_FIELD = re.compile(r"^C[0-9]+\.essence\.(.+)$")


def pointer(dotted: str) -> list[str] | None:
    """`C3.essence.premises.0.why` → `['premises', '0', 'why']`（相对遮蔽视图）；不是火意栏的返回 None。"""
    m = _FIELD.match(dotted)
    return m.group(1).split(".") if m else None


def apply_edit(ess: dict[str, Any], path: Sequence[str], value: str) -> str | None:
    """把 cz 的修改写进遮蔽视图；路径不存在返回错误。只改已有的字符串栏，不凭空加栏。"""
    node: Any = ess["masked"]
    for i, part in enumerate(path):
        last = i == len(path) - 1
        if isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                return f"没有这一栏：{'.'.join(path)}"
            if last:
                if not isinstance(node[int(part)], str):
                    return f"只能改文字栏：{'.'.join(path)}"
                node[int(part)] = value
                return None
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                return f"没有这一栏：{'.'.join(path)}"
            if last:
                if not isinstance(node[part], str):
                    return f"只能改文字栏：{'.'.join(path)}"
                node[part] = value
                return None
            node = node[part]
        else:
            return f"没有这一栏：{'.'.join(path)}"
    return f"没有这一栏：{'.'.join(path)}"


def recheck_after_edit(ess: dict[str, Any], ctx: checks.Context) -> None:
    """cz 改过的火意重跑 K1–K8；不过的照样显示，但人的决定在闸点上高于检验：记 override，一路带进炼档。"""
    old = {c["id"]: c for c in ess["checks"]}
    new = checks.k_checks(ess, ctx, None)
    out = []
    for c in new:
        if c["id"] == "K6":
            out.append(old.get("K6", c))
            continue
        if not c["ok"]:
            c["override"] = f"人改，检验未过：{c['id']}"
        out.append(c)
    ess["checks"] = out
