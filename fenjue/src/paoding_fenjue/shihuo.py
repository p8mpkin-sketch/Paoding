"""试火计划与试火记录的形状（现行设计 4.5、4.6、6.1；03 §4、§5）。纯函数，不读文件、不跑任何东西。

试火计划在设计裁决之前登记进炼档，裁决时记下它的哈希；登记之后不能改。试火记录由试火台写出，判定函数只从
记录读入运行读数：吸收目标维的四格计数在这里由逐题次的结果重算，不听记录自己报的合计。

这个文件是量具（`lianhua.MEASURE_PATHS`）：一次炼化改不到它。它不 import 判定函数，判定函数 import 它。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

# 成对比较（前者:后者）与四格：都过、只有前者过、只有后者过、都不过。单位是题次
PAIRS = ("F:A0", "F:B", "F:A1", "B:B1")
CELLS = ("both", "first", "second", "neither")

RUNS = 2  # 每条臂每道题跑 2 次（N2）
ENDPOINTS = ("proxy", "direct")  # 经我们的端点代理；直接连服务商
METERS = ("ledger", "export")  # 计量来源：我们的预算账；该臂自己导出的用量
ARM_FIELDS = ("what", "model", "version", "endpoint", "sampling", "meter", "price_table")
PURPOSES = ("试跑", "判定")
CAP_TIMES = 3  # 每题花费上限 = 试跑段里本火每题花费中位数的 3 倍（P9）

PLAN_KEYS = ("dossier", "arms", "judge", "questions", "trial_segment", "caps", "seed")
JUDGE_KEYS = ("model", "version", "prompts", "sample", "seconds_per_item")
RECORD_KEYS = ("plan_hash", "purpose", "status", "arms", "questions", "judge", "items", "readings", "cost")


def digest(x: Any) -> str:
    """一份计划或记录的哈希：键排序、紧凑分隔的 JSON 的 sha256。"""
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seed_for(plan_hash: str, question: str, run: int) -> str:
    """盲判抽样的种子：由计划哈希、题号与序号派生，跑之前就定死（5.4）。"""
    return hashlib.sha256(f"{plan_hash}\n{question}\n{run}".encode()).hexdigest()


def _pos(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def _text(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())


def caps_from(median_cost_usd_milli: int, questions: int, arms: int, runs: int = RUNS) -> dict[str, int]:
    """花费上限的机械规矩（P9）：每题上限是中位数的 3 倍，总上限是题数、臂数、次数与每题上限的乘积。"""
    per = CAP_TIMES * median_cost_usd_milli
    return {"per_item_usd_milli": per, "total_usd_milli": per * questions * arms * runs}


def check_plan(plan: Mapping[str, Any], d: Mapping[str, Any]) -> list[str]:
    """一份试火计划能不能登记进炼档 d。返回拒绝的理由；空表即可以登记。"""
    errors: list[str] = []
    lacks = [k for k in PLAN_KEYS if k not in plan]
    extra = sorted(set(plan) - set(PLAN_KEYS))
    if lacks or extra:
        return [f"试火计划的栏不对：缺 {lacks}，多 {extra}"]
    if plan["dossier"] != d["dossier"]:
        errors.append(f"计划写的是炼档 {plan['dossier']}，这一份是 {d['dossier']}")

    arms = plan["arms"] if isinstance(plan["arms"], Mapping) else {}
    registered = {k for k, v in (d.get("arms") or {}).items() if v}
    if set(arms) != registered:
        errors.append(f"计划里的臂 {sorted(arms)} 与入位时登记的臂 {sorted(registered)} 不一致")
    for must in ("B", "B1", "F"):
        if must not in arms:
            errors.append(f"缺 {must} 臂：本火、同火对照、合火必跑")
    for name, a in arms.items():
        a = a if isinstance(a, Mapping) else {}
        for k in ("model", "version"):
            if not _text(a.get(k)):
                errors.append(f"{name} 臂的模型栏空着（{k}）：逐臂写明模型名与版本标识才能登记")
        if a.get("endpoint") not in ENDPOINTS:
            errors.append(f"{name} 臂的端点只取 {ENDPOINTS}")
        if a.get("meter") not in METERS:
            errors.append(f"{name} 臂的计量来源只取 {METERS}")
        if not isinstance(a.get("sampling"), Mapping):
            errors.append(f"{name} 臂要登记采样参数（没有可设的就写空表）")
        for k in ("what", "price_table"):
            if not _text(a.get(k)):
                errors.append(f"{name} 臂缺 {k}")
        if set(a) - set(ARM_FIELDS):
            errors.append(f"{name} 臂多了 {sorted(set(a) - set(ARM_FIELDS))}")
    if len({a.get("price_table") for a in arms.values() if isinstance(a, Mapping)}) > 1:
        errors.append("各臂的价表版本不一致：花费用同一张价表折算")

    judge = plan["judge"] if isinstance(plan["judge"], Mapping) else {}
    if set(judge) - {*JUDGE_KEYS, "limit_given"}:
        errors.append(f"盲判一栏多了 {sorted(set(judge) - {*JUDGE_KEYS, 'limit_given'})}")
    for k in ("model", "version"):
        if not _text(judge.get(k)):
            errors.append(f"盲判的模型栏空着（{k}）")
    if not _text(judge.get("prompts")):
        errors.append("盲判三段的提示词版本要写进计划")
    sample = judge.get("sample")
    if not isinstance(sample, Mapping) or not _pos(sample.get("per_sub")) or not _pos(sample.get("max")):
        errors.append("盲判的抽样量要写明：每个子问抽几条（per_sub）、一份回答至多几条（max）")
    same = sorted(
        n
        for n, a in arms.items()
        if isinstance(a, Mapping) and _text(a.get("model")) and a["model"] == judge.get("model")
    )
    if same:
        errors.append(f"盲判的模型与 {'、'.join(same)} 臂相同：盲判要用与各臂都不同的模型")

    models = {(a.get("model"), a.get("version")) for a in arms.values() if isinstance(a, Mapping)}
    parity = (d.get("parity") or {}).get("class")
    if len(models) > 1 and parity in (None, "equal"):
        errors.append("各臂的模型名与版本不全相同，而入位时没有登记为条件不对等：拒跑")

    q = plan["questions"] if isinstance(plan["questions"], Mapping) else {}
    for k in ("set", "digest", "source"):
        if not _text(q.get(k)):
            errors.append(f"题集缺 {k}（题集只登记代号、摘要与来源，题面不进计划）")
    if not _pos(q.get("count")):
        errors.append("题集要写题数 count")
    if q.get("runs") != RUNS:
        errors.append(f"每条臂每道题跑 {RUNS} 次（runs）")
    if set(q) - {"set", "digest", "source", "count", "runs"}:
        errors.append(f"题集一栏多了 {sorted(set(q) - {'set', 'digest', 'source', 'count', 'runs'})}")

    seg = plan["trial_segment"] if isinstance(plan["trial_segment"], Mapping) else {}
    if not _text(seg.get("batch")) or not _pos(seg.get("median_cost_usd_milli")) or not _pos(seg.get("median_seconds")):
        errors.append("试跑段要写明批次号、本火每题花费的中位数与本火一遍用时的中位数：上限与时限由它们算出")
    elif _pos(q.get("count")) and arms:
        want = caps_from(seg["median_cost_usd_milli"], q["count"], len(arms))
        if plan["caps"] != want:
            errors.append(f"花费上限不是按规矩算出的：应当是 {want}（每题上限取中位数的 {CAP_TIMES} 倍，不手填）")
        limit, given = judge.get("seconds_per_item"), judge.get("limit_given")
        if not _pos(limit):
            errors.append("每题次的盲判时限要写进计划")
        elif limit != seg["median_seconds"]:
            ok = isinstance(given, Mapping) and _text(given.get("by")) and _text(given.get("why"))
            if not ok:
                errors.append(
                    f"每题次的盲判时限应当取试跑段里本火一遍用时的中位数（{seg['median_seconds']} 秒）；"
                    "另给的要写明谁给的、为什么（limit_given）"
                )
    if not _text(plan["seed"]):
        errors.append("计划要有种子：抽样的种子由计划哈希与题号派生")

    targets = [r for r in d.get("readings") or [] if r.get("target")]
    if not targets:
        errors.append("炼档没有登记吸收目标维：门判在目标维上")
    if not parity:
        errors.append("炼档入位时没有登记对等声明")
    if _pos(q.get("count")):
        for r in targets:
            if r.get("n") != q["count"] * RUNS:
                errors.append(f"吸收目标维 {r['dim']} 登记的样本量 {r.get('n')} 不等于题数乘次数 {q['count'] * RUNS}")
    return errors


def check_record(record: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str]:
    """一份试火记录能不能拿来判这份计划。返回拒绝的理由；空表即可以判。"""
    lacks = [k for k in RECORD_KEYS if k not in record]
    extra = sorted(set(record) - {*RECORD_KEYS, "reuse", "note"})
    if lacks or extra:
        return [f"试火记录的栏不对：缺 {lacks}，多 {extra}"]
    errors: list[str] = []
    if record["plan_hash"] != digest(plan):
        errors.append("记录里的计划哈希与登记的计划对不上：这份记录不是照这份计划跑的")
    if record["purpose"] not in PURPOSES:
        errors.append(f"记录的用途只取 {PURPOSES}")
    elif record["purpose"] != "判定":
        errors.append("试跑段的记录只作旗帜，不拿来出结局")
    if record["status"] != "complete":
        errors.append(f"试火没有跑完（{record['status']}）：结局未判，不收")
    for name, a in plan["arms"].items():
        got = (record["arms"] or {}).get(name) or {}
        if (got.get("model"), got.get("version")) != (a["model"], a["version"]):
            errors.append(f"{name} 臂读回的模型标识与计划不符：整条臂不符，试火中止，结局未判")
        if not _text(got.get("digest")):
            errors.append(f"{name} 臂没有记功法摘要或对象版本")
    if set(record["arms"] or {}) - set(plan["arms"]):
        errors.append(f"记录里多了计划没有的臂 {sorted(set(record['arms']) - set(plan['arms']))}")
    q = plan["questions"]
    if {k: (record["questions"] or {}).get(k) for k in ("set", "digest")} != {k: q[k] for k in ("set", "digest")}:
        errors.append("记录里的题集与计划登记的不是同一套")
    j = plan["judge"]
    if {k: (record["judge"] or {}).get(k) for k in ("model", "version", "prompts")} != {
        k: j[k] for k in ("model", "version", "prompts")
    }:
        errors.append("记录里的盲判（模型或三段的版本）与计划登记的不同")

    seen: set[tuple[str, str, int]] = set()
    questions: set[str] = set()
    total = 0
    for it in record["items"]:
        key = (it.get("arm"), it.get("q"), it.get("run"))
        if it.get("arm") not in plan["arms"] or not _text(it.get("q")) or it.get("run") not in range(1, RUNS + 1):
            errors.append(f"题次 {key}：臂、题号或序号不在计划里")
            continue
        if key in seen:
            errors.append(f"题次 {key} 记了两遍")
        seen.add(key)
        questions.add(it["q"])
        cost = it.get("cost_usd_milli")
        if not isinstance(it.get("passed"), bool) or not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
            errors.append(f"题次 {key}：要有盲判的结论 passed 与折算后的花费 cost_usd_milli")
            continue
        if not _text(it.get("task")) or not _text(it.get("log_head")):
            errors.append(f"题次 {key}：要有运行的题号 task 与日志头哈希 log_head（原形臂是导出的哈希）")
        total += cost
    if len(questions) > q["count"]:
        errors.append(f"记录里有 {len(questions)} 道题，计划登记的是 {q['count']} 道")
    booked = (record["cost"] or {}).get("total_usd_milli")
    if booked != total:
        errors.append(f"记录的花费合计 {booked} 与逐题次相加 {total} 不等")
    elif total > plan["caps"]["total_usd_milli"]:
        errors.append("花费超过了计划登记的总上限：账说停时试火就该中止，结局未判")
    if not isinstance(record["readings"], Mapping):
        errors.append("记录的 readings 要是「维 → 各臂读数」的表（目标维之外的各维）")
    return errors


def pairs(record: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """由逐题次的结果重算四格计数。两条臂按「同一道题、同一个序号」配对；只有一边跑了的题次不计。

    一个题次算过，要盲判判过并且折算后的花费不超过计划里每题的上限（过线定义的第三条）。"""
    cap = plan["caps"]["per_item_usd_milli"]
    ok = {(it["arm"], it["q"], it["run"]): bool(it["passed"]) and it["cost_usd_milli"] <= cap for it in record["items"]}
    out: dict[str, dict[str, int]] = {}
    for pair in PAIRS:
        first, second = pair.split(":")
        if first not in plan["arms"] or second not in plan["arms"]:
            continue
        cells = dict.fromkeys(CELLS, 0)
        for arm, q, run in ok:
            if arm != first or (second, q, run) not in ok:
                continue
            a, b = ok[(first, q, run)], ok[(second, q, run)]
            cells["both" if a and b else "first" if a else "second" if b else "neither"] += 1
        out[pair] = cells
    return out


def values(record: Mapping[str, Any], plan: Mapping[str, Any], d: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """把一份记录变成融火要的读数（维 → 值）。目标维只有重算出的四格计数；其余各维取记录里的各臂读数。"""
    out: dict[str, dict[str, Any]] = {}
    counted = pairs(record, plan)
    for r in d["readings"]:
        if r.get("target"):
            out[r["dim"]] = {"pairs": counted}
        elif r["dim"] in record["readings"]:
            out[r["dim"]] = dict(record["readings"][r["dim"]])
    stray = sorted(set(record["readings"]) - {r["dim"] for r in d["readings"] if not r.get("target")})
    if stray:
        raise ValueError(f"记录里这几维没有预登记，或是目标维（目标维不收各臂自己报的数）：{stray}")
    return out
