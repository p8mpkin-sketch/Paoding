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

from . import checks, data
from .dan import Dan

ATTEMPTS = 3
DRAFTS = ("main", "extra1", "extra2")
DRAFT_ZH = {"main": "主稿", "extra1": "萃丹一稿", "extra2": "萃丹二稿"}


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


def _as_essence(cand: Mapping[str, Any], out: Any) -> dict[str, Any]:
    if not isinstance(out, dict):
        return {"v": 1, "candidate": cand["id"], "masked": {}, "provenance": cand["provenance"]}
    return {
        "v": 1,
        "candidate": cand["id"],
        "masked": out.get("masked", {}),
        "provenance": copy.deepcopy(cand["provenance"]),
        "field_refs": out.get("field_refs", {}),
        "plain_summary": str(out.get("plain_summary", ""))[:600],
    }


@dataclass
class Result:
    essence: dict[str, Any]
    passed: bool
    tokens: dict[str, list[int]]


def distill(
    dan: Dan,
    cand: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
    ctx: checks.Context,
    *,
    rnd: int = 1,
) -> Result:
    """一个候选的萃意（第 1–10 步）。`rnd` 是第几轮（cz 在闸点 2 退回重做时加一），进丹调用的键。"""
    obs = evidence(cand, observations)
    tokens: dict[str, list[int]] = {"heavy": [0, 0], "mid": [0, 0]}

    def ask(role: str, key: str, errors: Sequence[str]) -> Draft:
        r = dan.call(role, key, _payload(cand, obs, role, errors))
        tier = "mid" if role == "blind" else "heavy"
        tokens[tier][0] += r.tokens_in
        tokens[tier][1] += r.tokens_out
        body = _as_essence(cand, r.output)
        return Draft(key, body, checks.k_checks(body, ctx, None))

    base = f"cuiyi:{cand['id']}:r{rnd}"
    errors: list[str] = []
    main: Draft | None = None
    for attempt in range(1, ATTEMPTS + 1):
        main = ask("main", f"{base}:main:{attempt}", errors)
        main.name = "main"
        if main.ok:
            break
        errors = [f"{c['id']}：{c.get('detail', '')}" for c in main.checks if not c["ok"] and not c.get("advisory")]
    assert main is not None
    extras = []
    for name in DRAFTS[1:]:
        d = ask("extra", f"{base}:{name}", [])
        d.name = name
        extras.append(d)
    drafts = [main, *extras]
    passing = [d for d in drafts if d.ok]
    pool = passing or [main]
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
    return Result(ess, checks.hard_ok(ess["checks"]), tokens)


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
