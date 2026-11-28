"""炼化六步的数据操作（焚决 F5，docs/design/fenjue/02-lianhua.md）：一份炼档从识火走到定阶或散火。

这里只有纯函数：输入一份炼档（JSON 形状见 docs/design/fenjue/dossiers/TEMPLATE.json）与参数，返回改过的新炼档；
定阶与散火另返回改过的功法。读写文件、跑 git 与测试的是 scripts/lianhua.py。炼档的 .md 由 render() 从 JSON 生成，
所以下一次吞噬不用手写炼档：每一步的命令把这一步的产出写进 JSON，再重新生成 .md。

每一步只能在上一步之后做（STEP_AFTER）；预登记的读数在入位时写下，之后不能改（03 §4：赛后不许移动球门）。

判定函数（`judge`）、这个文件本身与炼化命令是量具：一次炼化改不到它们（MEASURE_PATHS）。从 `YUANXING_GATE_FROM`
这个档号起，判定多一道原形门（03 §3.1）：条件对等时合火在异火维上输给原形，结局是「不及原形」，不收。
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from .shapes import FIRE_KEYS, SLOTS

# 体质组件（算“体质改动行数”用，02 §9）：一次吞噬对这些路径的改动行数，目标是 0
KERNEL_PATHS = (
    "judgebox/",
    "qicao/src/",
    "graph/src/",
    "executor/src/",
    "watchdog/src/",
    "adapter/src/paoding_adapter/proxy.py",
    "adapter/src/paoding_adapter/keyring.py",
    "adapter/src/paoding_adapter/creds.py",
)

# 量具（算“量具改动行数”用，03 §3.2）：一次炼化对这些路径的改动行数必须是 0。量具的改动单独提、单独裁，
# 不属于任何一次炼化
MEASURE_PATHS = (
    "liangju/",  # 引擎之外的量具：盲判三段与它的提示词、汇总、表项计数，以后的试火台、归类器、题目生成器
    "fenjue/src/paoding_fenjue/lianhua.py",  # 判定函数与炼化六步
    "fenjue/src/paoding_fenjue/readings.py",  # 进化读数（只显示）
    "scripts/lianhua.py",  # 炼化命令
    "fenjue/src/paoding_fenjue/engine/checks.py",  # 检验代码：萃意的检验与产物校验器
    "fenjue/src/paoding_fenjue/engine/schema.py",
    "fenjue/src/paoding_fenjue/engine/sections.py",
    "fenjue/src/paoding_fenjue/engine/schemas/",  # Schema
    "fenjue/src/paoding_fenjue/engine/tables/",  # 各张表
    "fenjue/tests/engine_fixtures/",  # 验收夹具与录音
    "tests/fenjue/goldens/",
    "ci/check_liangju.py",  # 守这条线的检查本身
)

# 状态：识火 → 萃意 → 入位 → 设计已裁（cz：值得炼）→ 验体 → 融火（读数已出）→ 收下 / 不收 → 入功法后散火
STATUSES = (
    "identified",
    "distilled",
    "placed",
    "design_approved",
    "trialed",
    "readings_ready",
    "adopted",
    "rejected",
    "reverted",
)
STEP_AFTER = {
    "cuiyi": ("identified", "distilled"),
    "ruwei": ("distilled", "placed"),
    "approve_design": ("placed",),
    "yanti": ("design_approved", "trialed"),
    "ronghuo": ("trialed", "readings_ready"),
    "jue": ("readings_ready",),
    "sanhuo": ("adopted",),
}
KINDS = ("共有", "本火", "异火", "新生")
OUTCOMES = {"huolian": "火莲", "helian": "合炼", "buji": "不及原形", "binghuo": "并火", "fanshi": "反噬"}
TAKEN = ("huolian", "helian")
ARMS = ("B", "B1", "A1", "F", "A0")  # 本火、同火对照、异火单炼、合火、原形（过了划线的档号，条件对等时是门）

# 原形门（03 §3.1）。按档号划线：这个档号及以后的炼档按新规则判，之前的不追溯（炼档 001 豁免）。
# 把线调回 None，判定就回到划线之前的行为。
YUANXING_GATE_FROM: str | None = "002"
GATE = {"passed": "原形门已过", "unjudged": "原形门未判", "failed": "原形门未过"}
# 条件对等的三种情形（入位时写明并归类，跑完之后不许改口）：对等；不对等但对我们有利或不偏向任何一方；
# 不对等且对原形有利、无法消除
PARITY = {"equal": "对等", "ours_or_neutral": "不对等：对我们有利或不偏向任何一方", "theirs": "不对等：对原形有利"}
# 吸收目标维的输入：成对比较的四格计数（都过、只有前者过、只有后者过、都不过），单位是题次。
# 四格由盲判的产出与花费记录算出；判定函数在目标维上只读这几栏，不读任何一条臂自己报的数
PAIRS = ("F:A0", "F:B", "F:A1", "B:B1")
CELLS = ("both", "first", "second", "neither")
TARGET_INPUTS = ("dim", "kind", "dir", "target", "pairs", "n")
TRIALS = ("T1", "T2", "T3", "T4", "T5")


class StepError(ValueError):
    """这一步现在做不了：顺序不对、缺东西、或要改已登记的读数。"""


def _need(d: dict[str, Any], step: str) -> dict[str, Any]:
    if d["status"] not in STEP_AFTER[step]:
        raise StepError(f"炼档 {d['dossier']} 在 {d['status']}，{step} 要在 {'/'.join(STEP_AFTER[step])} 之后做")
    return copy.deepcopy(d)


# ---------------------------------------------------------------- ① 识火


def new(no: str, name: str, title: str, today: str, shihuo: dict[str, Any]) -> dict[str, Any]:
    """开一份炼档。shihuo：出处、现象、我们缺什么、是否异火（02 §3）。不是异火的不开档，进普通需求。"""
    for k in ("source", "phenomenon", "gap", "is_fire"):
        if not shihuo.get(k):
            raise StepError(f"识火要写 {k}")
    if shihuo["is_fire"] is not True and not str(shihuo["is_fire"]).startswith("是"):
        raise StepError("不是异火（一种可复用的做法）的不开档：进普通需求，走地图修订规程")
    return {
        "dossier": no,
        "name": name,
        "title": title,
        "status": "identified",
        "identified": today,
        "generated": True,
        "shihuo": dict(shihuo),
        "cuiyi": None,
        "fire": {"lineage": {"dossier": no, "from": []}},
        "replaces": None,
        "kernel_lines_changed": 0,
        "preregistered": "",
        "arms": {},
        "readings": [],
        "yanti": None,
        "outcome_proposed": None,
        "jie_proposed": None,
        "metrics": {"cycle_days": None, "kernel_lines": 0, "slots": [], "trial_cost_usd_milli": None, "reverts": 0},
        "design_verdict": None,
        "verdict": None,
        "reverts": [],
    }


# ---------------------------------------------------------------- ② 萃意

CUIYI = ("yi", "premise", "cost", "overlap", "conflict", "hypothesis", "split", "masked")


def cuiyi(d: dict[str, Any], fields: dict[str, str]) -> dict[str, Any]:
    """火意、前提、代价、重叠、冲突、融合假设、守门性质拆分、遮住出处还成立吗（02 §4）。
    可分几次写，齐了才能入位。"""
    d = _need(d, "cuiyi")
    got = {**(d["cuiyi"] or {}), **{k: v for k, v in fields.items() if v}}
    unknown = set(got) - set(CUIYI)
    if unknown:
        raise StepError(f"萃意没有这几栏：{sorted(unknown)}")
    d["cuiyi"] = got
    d["status"] = "distilled"
    return d


# ---------------------------------------------------------------- ③ 入位


def ruwei(
    d: dict[str, Any],
    fire: dict[str, Any],
    replaces: str | None,
    arms: dict[str, str],
    readings: list[dict[str, Any]],
    preregistered: str = "",
    group: list[dict[str, Any]] | None = None,
    parity: dict[str, str] | None = None,
) -> dict[str, Any]:
    """火位与清单草稿、替换谁、各臂是什么、预登记读数（02 §5、03 §4）。读数登记之后不能改。

    group：火组的其余成员（12 §2.3），每个 {fire, replaces}；跨火位、行为有变的模式一个火位一团火，一份炼档一起走。
    parity：原形臂的条件对等声明 {class, reason}（03 §3.1）。与读数一样，写下之后不能改。"""
    d = _need(d, "ruwei")
    missing = [k for k in CUIYI[:7] if not (d["cuiyi"] or {}).get(k)]
    if missing:
        raise StepError(f"萃意还缺 {missing}：火意没提炼完不入位")
    if d["readings"] and d["readings"] != readings:
        raise StepError("预登记的读数已经写下，不能改（赛后不许移动球门）；要换就开下一份炼档")
    lacks = [k for k in FIRE_KEYS if k not in fire]
    if lacks:
        raise StepError(f"清单草稿缺 {lacks}")
    if fire["slot"] not in SLOTS:
        raise StepError(f"没有火位 {fire['slot']}")
    if fire["lineage"].get("dossier") != d["dossier"]:
        raise StepError("清单的 lineage.dossier 要写本档档号")
    if replaces is not None and replaces not in fire["lineage"]["from"]:
        raise StepError(f"替换的 {replaces} 要写进清单的 lineage.from（散火时指回它）")
    for r in readings:
        if r.get("kind") not in KINDS or r.get("dir") not in ("up", "down") or not r.get("dim"):
            raise StepError(f"读数 {r.get('dim')!r}：要有 dim、kind（{'/'.join(KINDS)}）、dir（up/down）")
        if r["kind"] == "新生" and r.get("gate") is None:
            raise StepError(f"新生维 {r['dim']} 要登记门槛 gate")
    if not readings:
        raise StepError("至少登记一维读数")
    for r in readings:
        if r.get("target"):
            if r["kind"] != "异火":
                raise StepError(f"吸收目标维 {r['dim']} 要是异火维（我们想吸收它的原因）")
            if not isinstance(r.get("n"), int) or isinstance(r.get("n"), bool) or r["n"] <= 0:
                raise StepError(f"吸收目标维 {r['dim']} 要登记样本量 n（每条臂的题次数）")
    declared = {k: v for k, v in (d.get("parity") or {}).items() if k != "waiver"}
    if parity is not None:
        if parity.get("class") not in PARITY:
            raise StepError(f"对等声明的归类只取 {list(PARITY)}")
        if parity["class"] != "equal" and not parity.get("reason"):
            raise StepError("条件不对等要写明原因（入位时写下，跑完之后不许改口）")
        if set(parity) - {"class", "reason"}:
            raise StepError("对等声明只有 class 与 reason 两栏；豁免由 cz 在设计裁决时写")
        if declared and declared != dict(parity):
            raise StepError("对等声明已经写下，不能改；要换就开下一份炼档")
    members = [dict(m) for m in group or []]
    for m in members:
        gf = m.get("fire") or {}
        lacks = [k for k in FIRE_KEYS if k not in gf]
        if lacks:
            raise StepError(f"火组成员 {gf.get('id')} 的清单缺 {lacks}")
        if gf["slot"] not in SLOTS or gf["slot"] == fire["slot"]:
            raise StepError(f"火组成员 {gf['id']} 的火位 {gf['slot']} 要是主火之外的另一个火位")
        if gf["lineage"].get("dossier") != d["dossier"]:
            raise StepError(f"火组成员 {gf['id']} 的 lineage.dossier 要写本档档号")
        if m.get("replaces") is not None and m["replaces"] not in gf["lineage"]["from"]:
            raise StepError(f"火组成员 {gf['id']} 替换的 {m['replaces']} 要写进它的 lineage.from")
    if len({fire["slot"], *[m["fire"]["slot"] for m in members]}) != 1 + len(members):
        raise StepError("火组里一个火位只能有一团火")
    d["fire"] = copy.deepcopy(fire)
    d["replaces"] = replaces
    d["arms"] = dict(arms)
    d["readings"] = [dict(r) for r in readings]
    d["preregistered"] = preregistered or f"本档第三节（{d['dossier']}，入位时登记）"
    if parity is not None and not declared:
        d["parity"] = dict(parity)
    d["metrics"]["slots"] = [fire["slot"], *[m["fire"]["slot"] for m in members]]
    if members:
        d["group"] = [{"fire": copy.deepcopy(m["fire"]), "replaces": m.get("replaces")} for m in members]
    d["status"] = "placed"
    return d


def approve_design(d: dict[str, Any], by: str, date: str, note: str = "", waive_gate: str = "") -> dict[str, Any]:
    """前三节是设计 PR：裁决“值不值得炼”之后才进验体（02 §5 末）。

    waive_gate：条件不对等且对原形有利时，裁决人对这一份炼档单独写下的豁免理由。有了它原形门才降为参考
    （结局最高合炼）；没有的话门照判。"""
    d = _need(d, "approve_design")
    if waive_gate:
        if (d.get("parity") or {}).get("class") != "theirs":
            raise StepError("只有入位时登记为「不对等：对原形有利」的炼档才谈得上豁免原形门")
        d["parity"] = {**d["parity"], "waiver": {"by": by, "date": date, "why": waive_gate}}
    d["design_verdict"] = {"by": by, "date": date, **({"note": note} if note else {})}
    d["status"] = "design_approved"
    return d


# ---------------------------------------------------------------- ④ 验体


def yanti(
    d: dict[str, Any],
    kernel_lines: int,
    static_errors: list[str],
    trials: dict[str, dict[str, Any]],
    commit: str,
    measure_lines: int | None = None,
) -> dict[str, Any]:
    """静态验体的错误、动态验体（T1–T5 各自的结果）、体质改动行数、提交哈希（02 §6）。
    验体不判好坏，只判安全：任一条不过，融火时直接判反噬。

    measure_lines：这次炼化对量具路径（MEASURE_PATHS）的改动行数。过了划线的炼档，这一项非零即验体不过：
    量具的改动单独提、单独裁，不能夹在炼化里。"""
    d = _need(d, "yanti")
    if set(trials) != set(TRIALS):
        raise StepError(f"动态验体要有 {TRIALS} 五项的结果")
    d["yanti"] = {
        "commit": commit,
        "kernel_lines": kernel_lines,
        "static_errors": list(static_errors),
        "trials": {k: dict(trials[k]) for k in TRIALS},
        "passed": not static_errors and all(t.get("ok") for t in trials.values()),
    }
    if measure_lines is not None:
        d["yanti"]["measure_lines"] = measure_lines
        d["measure_lines_changed"] = measure_lines
        d["metrics"]["measure_lines"] = measure_lines
        if gated(d) and measure_lines:
            d["yanti"]["passed"] = False
    d["kernel_lines_changed"] = kernel_lines
    d["metrics"]["kernel_lines"] = kernel_lines
    d["status"] = "trialed"
    return d


# ---------------------------------------------------------------- ⑤ 融火


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def gated(d: Mapping[str, Any]) -> bool:
    """这份炼档归不归原形门管：按档号划线（YUANXING_GATE_FROM）。"""
    return YUANXING_GATE_FROM is not None and str(d["dossier"]) >= YUANXING_GATE_FROM


def noise_floor(discordant: int) -> int:
    """噪声底 m：本火与同火对照结论不一致的题次数 d，取 2 倍的 d 的平方根，向上取整，最小为 1。"""
    return max(1, math.ceil(2 * math.sqrt(discordant)))


def _cells(r: Mapping[str, Any], pair: str) -> dict[str, int] | None:
    c = (r.get("pairs") or {}).get(pair)
    if c is None:
        return None
    ok = isinstance(c, Mapping) and set(c) == set(CELLS)
    if not ok or any(not isinstance(c[k], int) or isinstance(c[k], bool) or c[k] < 0 for k in CELLS):
        raise StepError(f"读数 {r['dim']} 的 {pair}：四格计数要有 {CELLS}，都是不小于 0 的整数")
    return {k: int(c[k]) for k in CELLS}


def _behind(c: Mapping[str, int]) -> int:
    """成对比较里前者（合火）落后多少个题次：只有后者过的，减去只有前者过的。"""
    return c["second"] - c["first"]


def _target(r: dict[str, Any]) -> tuple[bool, bool, dict[str, Any] | None]:
    """吸收目标维：只凭成对比较的四格计数判。回 (退没退, 胜没胜, 对原形的一格判断；没有原形的计数时是 None)。

    这里读的栏就是 TARGET_INPUTS，不读任何一条臂自己报的数。配上对的题次数少于预登记的样本量时，结论只作旗帜：
    不算胜，原形门不判；退步照记。"""
    fb, bb = _cells(r, "F:B"), _cells(r, "B:B1")
    if fb is None or bb is None:
        raise StepError(f"吸收目标维 {r['dim']} 还没有 F:B 与 B:B1 两组成对计数")
    m = noise_floor(bb["first"] + bb["second"])
    short = sum(fb.values()) < int(r.get("n") or 0)
    fa1, fa0 = _cells(r, "F:A1"), _cells(r, "F:A0")
    regress = _behind(fb) > m or (fa1 is not None and _behind(fa1) > m)
    win = not short and -_behind(fb) > m and (fa1 is None or -_behind(fa1) > m)
    r["m"] = m
    r["verdict"] = ("退" if regress else "胜" if win else "不退") + ("（样本不足，只作旗帜）" if short else "")
    if fa0 is None:
        return regress, win, None
    state = "unjudged" if short else "failed" if _behind(fa0) > m else "passed"
    r["yuanxing"] = {"unjudged": "未判", "failed": "未过", "passed": "过"}[state]
    return regress, win, {"dim": r["dim"], "state": state, "behind": _behind(fa0), "m": m, "unit": "个题次"}


def _gate(d: Mapping[str, Any], seen: list[dict[str, Any]], has_target: bool) -> tuple[str, list[str]]:
    """原形门的状态（03 §3.1）：过了、没过、还是没法判。seen 是每个异火维对原形的一格判断。"""
    parity = d.get("parity") or {}
    lost = [
        f"{g['dim']}：合火比原形落后 {g['behind']:g} {g['unit']}，超过噪声底 {g['m']:g}"
        for g in seen
        if g["state"] == "failed"
    ]
    if not d["arms"].get("A0") or not seen:
        return "unjudged", ["原形臂还没有读数（原形适配的条件不具备时就是这样）"]
    if parity.get("class") == "theirs" and parity.get("waiver"):
        w = parity["waiver"]
        return "unjudged", [f"条件不对等且对原形有利，{w['by']} 于 {w['date']} 对本档写下豁免：门降为参考", *lost]
    if lost:
        return "failed", lost
    if not has_target:
        return "unjudged", ["没有登记吸收目标维：门判在目标维上，没有它就没法判"]
    if parity.get("class") not in PARITY:
        return "unjudged", ["入位时没有登记对等声明"]
    if any(g["state"] == "unjudged" for g in seen):
        return "unjudged", ["配上对的题次数少于预登记的样本量：结论只作旗帜"]
    if parity["class"] == "ours_or_neutral":
        return "passed", ["条件不对等（对我们有利或不偏向任何一方）：门照判；胜过原形的话只作旗帜，不作判定"]
    if parity["class"] == "theirs":
        return "passed", ["条件不对等且对原形有利，没有豁免：门照判"]
    return "passed", []


def _judge(d: dict[str, Any], gate: bool) -> tuple[str, list[str]]:
    why: list[str] = []
    y = d["yanti"] or {}
    if not y.get("passed"):
        if gate and y.get("measure_lines"):
            return "fanshi", [f"验体没过：量具改动行数 {y['measure_lines']}，量具的改动要单独提、单独裁"]
        return "fanshi", ["验体没过"]
    has_a1 = bool(d["arms"].get("A1"))
    regress = native_regress = False
    emergent_ok: list[bool] = []
    wins = False
    seen: list[dict[str, Any]] = []  # 每个异火维对原形的一格判断
    has_target = False
    for r in d["readings"]:
        if gate and r.get("target"):
            has_target = True
            back, won, vs = _target(r)
            regress, wins = regress or back, wins or won
            seen += [vs] if vs else []
            continue
        s = 1.0 if r["dir"] == "up" else -1.0
        b, f, a1, m = _num(r.get("B")), _num(r.get("F")), _num(r.get("A1")), _num(r.get("m")) or 0.0
        if f is None:
            raise StepError(f"读数 {r['dim']} 还没有合火臂 F 的值")
        if r["kind"] == "新生":
            ok = s * (f - float(r["gate"])) >= 0 and (b or 0) == 0 and (a1 or 0) == 0
            emergent_ok.append(ok)
            r["verdict"] = "达门槛" if ok else "未达"
            continue
        if b is None:
            raise StepError(f"读数 {r['dim']} 还没有本火臂 B 的值")
        a0 = _num(r.get("A0")) if gate and r["kind"] == "异火" else None
        if a0 is not None:  # 目标维之外的异火维：同样不许低于原形减噪声底
            state = "failed" if s * (f - a0) < -m else "passed"
            r["yuanxing"] = "未过" if state == "failed" else "过"
            seen.append({"dim": r["dim"], "state": state, "behind": s * (a0 - f), "m": m, "unit": ""})
        if s * (f - b) < -m or (r["kind"] == "异火" and a1 is not None and s * (f - a1) < -m):
            r["verdict"] = "退"
            regress = True
            native_regress = native_regress or r["kind"] == "本火"
            continue
        best = max((s * x for x in (b, a1) if x is not None), default=s * b)
        if s * f > best + m:
            r["verdict"] = "胜"
            wins = True
        else:
            r["verdict"] = "不退"
    for r in d["readings"]:
        why.append(f"{r['dim']}（{r['kind']}）：{r['verdict']}")
    if native_regress:
        outcome, why = "fanshi", [*why, "本火维退步：体质是底座，不让步"]
    elif regress:
        outcome, why = "binghuo", [*why, "共有维或异火维退步：不满足“不退”"]
    elif emergent_ok and all(emergent_ok) and has_a1:
        outcome = "huolian"
    else:
        if emergent_ok and all(emergent_ok) and not has_a1:
            why.append("没有异火单炼臂 A′：结局最高合炼（FJ8）")
        if wins or (emergent_ok and all(emergent_ok)):
            outcome = "helian"
        else:
            outcome, why = "binghuo", [*why, "没有任何一维胜过两个来源：收藏不是炼化"]
    if not gate:
        return outcome, why
    state, notes = _gate(d, seen, has_target)
    d["yuanxing_gate"] = {"state": state, "why": notes}
    why = [*why, f"{GATE[state]}" + (f"：{'；'.join(notes)}" if notes else "")]
    if outcome in TAKEN and state == "failed":
        return "buji", [*why, f"本来够得上{OUTCOMES[outcome]}，但移植丢了东西：不及原形，不收"]
    if outcome == "huolian" and state == "unjudged":
        return "helian", [*why, "原形门未判：结局最高合炼"]
    return outcome, why


def canaries() -> list[tuple[str, dict[str, Any], str]]:
    """判定函数的三只金丝雀（03 §3.3）：(名字, 一份合成的炼档, 应当判出的结局)。

    安慰剂：合火与本火完全相同，应判并火。退步：合火被削弱了一项本火能力，应判反噬。封顶：合火在吸收目标维上
    明显弱于原形，应判不及原形；原形适配还没有的时候拿本火充当原形臂，验的是判定与流程。"""
    same = {"both": 30, "first": 3, "second": 3, "neither": 4}  # 两条相同的臂：只有抖动
    ahead = {"both": 24, "first": 12, "second": 1, "neither": 3}  # 前者明显强
    capped = {"both": 24, "first": 1, "second": 12, "neither": 3}  # 前者明显弱

    def make(pairs: dict[str, dict[str, int]], leaks: int) -> dict[str, Any]:
        return {
            "dossier": "canary",
            "arms": {"B": "本火", "B1": "本火再跑一遍", "A1": "异火单炼", "F": "合火", "A0": "原形（替身：本火）"},
            "parity": {"class": "equal"},
            "yanti": {"passed": True},
            "readings": [
                {"dim": "留出题上的过线数", "kind": "异火", "dir": "up", "target": True, "n": 40, "pairs": pairs},
                {"dim": "凭据泄漏数", "kind": "本火", "dir": "down", "B": 0, "A1": 0, "F": leaks, "m": 0},
                {"dim": "每题次花费", "kind": "共有", "dir": "down", "B": 100, "A1": 100, "F": 100, "m": 5},
            ],
        }

    base = {"B:B1": same, "F:B": same, "F:A1": same, "F:A0": same}
    return [
        ("安慰剂", make(base, 0), "binghuo"),
        ("退步", make(base, 1), "fanshi"),
        ("封顶", make({"B:B1": same, "F:B": ahead, "F:A1": ahead, "F:A0": capped}, 0), "buji"),
    ]


def misjudged_canaries() -> list[str]:
    """判错的金丝雀的名字。任何一只判错，这时判出的结局不作数。"""
    return [name for name, d, want in canaries() if _judge(d, gate=True)[0] != want]


def judge(d: dict[str, Any]) -> tuple[str, list[str]]:
    """按 03 §3 判结局，返回结局与每一维的判（达门槛、不退、胜、退）及理由。

    过了划线的炼档多一道原形门（03 §3.1），并且先让三只金丝雀过一遍判定函数：判错了就拒绝出结局。
    划线之前的炼档原样按旧规则判。"""
    if not gated(d):
        return _judge(d, gate=False)
    wrong = misjudged_canaries()
    if wrong:
        raise StepError(f"判定函数的金丝雀判错了（{'、'.join(wrong)}）：这时判出的结局不作数")
    return _judge(d, gate=True)


def ronghuo(d: dict[str, Any], values: dict[str, dict[str, Any]], jie_now: int) -> dict[str, Any]:
    """填各臂读数（dim → {B, B1, A1, F, A0, m, n}），判结局，提议品阶。没给 m 时用 |B − B′| 作噪声底。

    过了划线的炼档，吸收目标维只收成对比较的四格计数（dim → {pairs: {"F:A0": {both, first, second, neither}, …}}）。"""
    d = _need(d, "ronghuo")
    dims = {r["dim"] for r in d["readings"]}
    unknown = set(values) - dims
    if unknown:
        raise StepError(f"这几维没有预登记：{sorted(unknown)}（赛后不许加维）")
    for r in d["readings"]:
        v = values.get(r["dim"], {})
        if gated(d) and r.get("target"):
            bad = set(v) - {"pairs", "note"}
            if bad:
                raise StepError(
                    f"吸收目标维 {r['dim']} 只能填成对比较的四格计数 pairs（与 note），多了 {sorted(bad)}："
                    "它不收任何一条臂自己报的数，样本量 n 与噪声底 m 也不在这里填"
                )
            unknown_pairs = set(v.get("pairs") or {}) - set(PAIRS)
            if unknown_pairs:
                raise StepError(f"吸收目标维 {r['dim']} 的成对比较只有 {PAIRS}，多了 {sorted(unknown_pairs)}")
            r.update(v)
            continue
        bad = set(v) - {*ARMS, "m", "n", "note"}
        if bad:
            raise StepError(f"读数 {r['dim']} 只能填 {ARMS}、m、n、note，多了 {sorted(bad)}")
        r.update(v)
        if "m" not in r and _num(r.get("B")) is not None and _num(r.get("B1")) is not None:
            r["m"] = abs(float(r["B"]) - float(r["B1"]))
    outcome, why = judge(d)
    d["outcome_proposed"] = outcome
    d["outcome_why"] = why
    d["jie_proposed"] = jie_now + 1 if outcome in TAKEN else None
    d["status"] = "readings_ready"
    return d


# ---------------------------------------------------------------- 定阶（cz 裁决）与 ⑥ 散火


def _ref(f: dict[str, Any]) -> str:
    return f"{f['id']}@{f['ver']}"


def members(d: dict[str, Any]) -> list[tuple[dict[str, Any], str | None]]:
    """炼档里的每团火与它替换谁：主火在前，火组成员（12 §2.3）在后。"""
    return [(d["fire"], d["replaces"]), *[(m["fire"], m.get("replaces")) for m in d.get("group") or []]]


def install(g: dict[str, Any], d: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """把炼档里的火装进功法（不动品阶与品阶史）：顶替 replaces 那团，被顶替的进常设留出；火组整组一起装。
    返回 (新功法, 主火顶替的那团 "id@ver")。验体用它造候选功法（体质试炼换上这团火再跑一遍），定阶用它改功法。"""
    g = copy.deepcopy(g)
    first = None
    for i, (f, replaces) in enumerate(members(d)):
        slot = f["slot"]
        refs = list(g["fires"].get(slot, []))
        old = None
        if replaces:
            old = next((r for r in refs if r.partition("@")[0] == replaces), None)
            if old is None:
                raise StepError(f"功法 {slot} 里没有要顶替的 {replaces}")
            refs[refs.index(old)] = _ref(f)
            g.setdefault("holdout", {})[slot] = [*g.get("holdout", {}).get(slot, []), old]
        else:
            refs.append(_ref(f))
        g["fires"][slot] = refs
        if i == 0:
            first = old
    return g, first


def jue(
    d: dict[str, Any],
    g: dict[str, Any],
    by: str,
    date: str,
    outcome: str,
    conditions: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """记第六节的裁决。收下（火莲、合炼）时同时改功法：新火装进火位、顶替的那团进常设留出、品阶加一。
    返回 (炼档, 功法)。g 是功法 JSON（不带算出的摘要）。"""
    d = _need(d, "jue")
    if outcome not in OUTCOMES:
        raise StepError(f"结局只能是 {list(OUTCOMES)}")
    g = copy.deepcopy(g)
    taken = outcome in TAKEN
    jie = g["jie"] + 1 if taken else None
    d["verdict"] = {
        "by": by,
        "date": date,
        "outcome": outcome,
        **({"jie": jie} if jie else {}),
        "conditions": conditions,
    }
    d["status"] = "adopted" if taken else "rejected"
    if not taken:
        return d, g
    g, old = install(g, d)
    g["jie"] = jie
    g["history"] = [
        *g["history"],
        {
            "jie": jie,
            "change": f"{d['title']}（炼档 {d['dossier']}）",
            "dossier": d["dossier"],
            **({"replaces": old} if old else {}),
        },
    ]
    return d, g


def sanhuo(d: dict[str, Any], g: dict[str, Any], by: str, date: str, why: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """散火：火位指回上一团火（留出里的那团回到生效），新火拿掉；火组整组一起散；炼档第七节记一行；
    品阶记一次降阶，原来的升阶记录不抹。"""
    d = _need(d, "sanhuo")
    g = copy.deepcopy(g)
    first = None
    for i, (f, replaces) in enumerate(members(d)):
        slot = f["slot"]
        refs = list(g["fires"].get(slot, []))
        if _ref(f) not in refs:
            raise StepError(f"功法 {slot} 里没有 {_ref(f)}：已经散过了？")
        back = None
        if replaces:
            held = g.get("holdout", {}).get(slot, [])
            back = next((r for r in held if r.partition("@")[0] == replaces), None)
            if back is None:
                raise StepError(f"常设留出里没有 {replaces}：上一团火已删，散不回去")
            g["holdout"][slot] = [r for r in held if r != back]
            if not g["holdout"][slot]:
                del g["holdout"][slot]
            refs[refs.index(_ref(f))] = back
        else:
            refs.remove(_ref(f))
        g["fires"][slot] = refs
        if i == 0:
            first = back
    g["jie"] = g["jie"] - 1
    g["history"] = [
        *g["history"],
        {"jie": g["jie"], "change": f"散火：{d['title']}（炼档 {d['dossier']}）", "reverts": d["dossier"]},
    ]
    d["reverts"] = [*d["reverts"], {"by": by, "date": date, "why": why, **({"back_to": first} if first else {})}]
    d["metrics"]["reverts"] = len(d["reverts"])
    d["status"] = "reverted"
    return d, g


def next_step(d: dict[str, Any]) -> str | None:
    """这份炼档下一步该做什么（给 status 命令用）。"""
    order = ("cuiyi", "ruwei", "approve_design", "yanti", "ronghuo", "jue")
    for step in order:
        if d["status"] == STEP_AFTER[step][0]:
            return step
    return None


# ---------------------------------------------------------------- 生成 .md


def _cell(x: Any) -> str:
    if x is None or x == "":
        return "—"
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return str(x).replace("|", "\\|").replace("\n", " ")


def _engine_sections(d: dict[str, Any]) -> list[str]:
    """由方案分析导入的炼档（有 engine 键）：第三节后加“冲突报告”“实现步骤”两小节（12 §2.4）。"""
    e = d.get("engine")
    if not e:
        return []
    px = e.get("placement_extra", {})
    c = px.get("conflicts", {})
    lines = ["### 冲突报告", "", "| 与谁 | 决定 | 种类 | 化解 | 说明 |", "| --- | --- | --- | --- | --- |"]
    for r in c.get("fires", []):
        note = r.get("note", "") + (f"（分区：{r['partition_by']}）" if r.get("partition_by") else "")
        cells = [r["fire"], r["atom"], r["kind"], r["resolution"], note]
        lines.append("| " + " | ".join(_cell(x) for x in cells) + " |")
    for r in c.get("kernel", []):
        lines.append(f"| {_cell(r['kernel'])} | — | 体质 | {_cell(r['resolution'])} | {_cell(r.get('note'))} |")
    for r in c.get("candidates", []):
        lines.append(f"| {_cell(r['other'])} | — | 候选之间 | {_cell(r['relation'])} | {_cell(r.get('note'))} |")
    for r in c.get("slot_locks", []):
        lines.append(f"| 炼档 {_cell(r['dossier'])} | — | 火位锁 | 排队 | {_cell(r['slot'])} |")
    lines += [
        "",
        f"体质影响预判：{_cell('、'.join(px.get('kernel_forecast') or [])) if px.get('kernel_forecast') else '空'}。",
        "",
    ]
    lines += [
        "### 实现步骤",
        "",
        "| # | 做什么 | 火位 | 在哪 | 测试 | 体质行数 | 验收 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in px.get("steps", []):
        lines.append(
            f"| {s['n']} | {_cell(s['do'])} | {_cell(s['slot'])} | {_cell('、'.join(s['where']))} | "
            f"{_cell('、'.join(s['tests']))} | {s['kernel_lines']} | {_cell(s['accept'])} |"
        )
    lines += [
        "",
        f"来源：方案分析 `{_cell(e.get('run'))}` 的 {_cell(e.get('candidate'))}；"
        "产物 sha256 见炼档 JSON 的 engine.artifacts。",
        "",
    ]
    return lines


def render(d: dict[str, Any]) -> str:
    """炼档的 .md：从 JSON 生成，七节齐全（02 §9）。手改会被下一次命令覆盖，要改就改 JSON 再 render。"""
    s, c = d["shihuo"], d["cuiyi"] or {}
    f = d["fire"]
    lines = [
        f"# 炼档 {d['dossier']}：{d['title']}",
        "",
        f"> 由 `scripts/lianhua.py` 从 [{d['dossier']}-{d['name']}.json](./{d['dossier']}-{d['name']}.json) 生成，"
        "改 JSON 后 `render` 重新生成，不要手改本文件。协议见 [02 炼化](../02-lianhua.md)。",
        ">",
        f"> 状态：{d['status']}"
        + (f"；结局提议：{OUTCOMES[d['outcome_proposed']]}" if d.get("outcome_proposed") else "")
        + (f"；裁决：{OUTCOMES[d['verdict']['outcome']]}" if d.get("verdict") else "")
        + (f"；{GATE[d['yuanxing_gate']['state']]}" if d.get("yuanxing_gate") else ""),
        "",
        "## 一、识火",
        "",
        "| 栏 | 内容 |",
        "| --- | --- |",
        f"| 出处 | {_cell(s.get('source'))} |",
        f"| 现象 | {_cell(s.get('phenomenon'))} |",
        f"| 我们缺什么 | {_cell(s.get('gap'))} |",
        f"| 是否异火 | {_cell(s.get('is_fire'))} |",
        "",
        "## 二、萃意",
        "",
    ]
    names = ("火意", "前提", "代价", "与本火的重叠", "冲突", "融合假设", "守门性质拆分", "遮住出处还成立吗")
    lines += [f"- **{n}**：{_cell(c.get(k))}" for n, k in zip(names, CUIYI, strict=True)]
    lines += ["", "## 三、入位", "", "| 栏 | 内容 |", "| --- | --- |"]
    o = f.get("organ") or {}
    lines += [
        f"| 火位 | {_cell(f.get('slot'))} |",
        f"| 席位 | {_cell(', '.join(f.get('seats', [])) or '不涉及（不是 H1）')} |",
        f"| 经脉 | {_cell(', '.join(f.get('ports', [])))} |",
        f"| 清单 | `{_cell(f.get('id'))}@{_cell(f.get('ver'))}`，lineage.from = {_cell(f['lineage'].get('from'))} |",
        f"| 入库四问 | {_cell(o.get('class'))}；退役信号：{_cell(o.get('retire_signal'))}；"
        f"启用条件：{_cell(o.get('enable_when'))}；对照臂：{_cell(o.get('control_arm'))} |",
        f"| 替换谁 | {_cell(d.get('replaces') and d['replaces'] + '（入功法后进常设留出）') or '并存'} |",
        f"| 预登记读数 | {_cell(d.get('preregistered'))}，见第五节的表（入位时写下，之后不改） |",
    ]
    if d.get("parity"):
        par = d["parity"]
        w = par.get("waiver")
        lines.append(
            f"| 原形臂的条件 | {PARITY[par['class']]}"
            + (f"：{_cell(par.get('reason'))}" if par.get("reason") else "")
            + (f"；{_cell(w['by'])} 于 {w['date']} 写下豁免：{_cell(w['why'])}" if w else "")
            + " |"
        )
    for m in d.get("group") or []:
        gf = m["fire"]
        lines.append(
            f"| 火组成员 | `{_cell(gf.get('id'))}@{_cell(gf.get('ver'))}`（{_cell(gf.get('slot'))}），"
            f"替换 {_cell(m.get('replaces')) if m.get('replaces') else '无（并存）'} |"
        )
    lines.append("")
    lines += _engine_sections(d)
    if d.get("design_verdict"):
        dv = d["design_verdict"]
        lines += [f"设计裁决（值得炼）：{dv['by']}，{dv['date']}{('，' + dv['note']) if dv.get('note') else ''}。", ""]
    y = d.get("yanti")
    lines += ["## 四、验体", ""]
    if y:
        lines += [
            f"- 提交：`{y['commit']}`",
            f"- 体质改动行数：**{y['kernel_lines']}**"
            + ("（非 0：夹带了体质修炼，应拆开）" if y["kernel_lines"] else ""),
            *(
                [
                    f"- 量具改动行数：**{y['measure_lines']}**"
                    + ("（非 0：量具的改动要单独提、单独裁，不能夹在炼化里）" if y["measure_lines"] else "")
                ]
                if "measure_lines" in y
                else []
            ),
            f"- 静态验体：{'全过' if not y['static_errors'] else '；'.join(y['static_errors'])}",
            "",
            "| 体质 | 结果 | 摘要 |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {k} | {'过' if t.get('ok') else '不过'} | {_cell(t.get('summary'))} |" for k, t in y["trials"].items()
        ]
    else:
        lines.append("未做。")
    lines += ["", "## 五、融火", "", "| 臂 | 是什么 |", "| --- | --- |"]
    arm_names = {"B": "B 本火", "B1": "B′ 同火对照", "A1": "A′ 异火单炼", "F": "F 合火", "A0": "A° 原形参照"}
    if gated(d) and d.get("yuanxing_gate"):
        arm_names["A0"] = "A° 原形"
    lines += [f"| {arm_names[k]} | {_cell(v)} |" for k, v in d["arms"].items() if k in arm_names]
    lines += [
        "",
        "| 维 | 类 | 方向 | B | B′ | 噪声底 m | A′ | F | A° | 门槛 | 出处 | 判 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in d["readings"]:
        cells = [r["dim"], r["kind"], "↑" if r["dir"] == "up" else "↓"]
        cells += [_cell(r.get(k)) for k in ("B", "B1", "m", "A1", "F", "A0", "gate")]
        cells += [f"`{r['test']}`" if r.get("test") else "—", _cell(r.get("verdict"))]
        lines.append("| " + " | ".join(str(x) for x in cells) + " |")
    paired = [r for r in d["readings"] if r.get("pairs")]
    if paired:
        lines += [
            "",
            "吸收目标维的成对比较（单位：题次；配对按同一道题、同一个序号）：",
            "",
            "| 维 | 比较 | 都过 | 只有前者过 | 只有后者过 | 都不过 | 噪声底 m | 对原形 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        pair_names = {"F:A0": "F 对 A°", "F:B": "F 对 B", "F:A1": "F 对 A′", "B:B1": "B 对 B′"}
        for r in paired:
            for k in PAIRS:
                c = r["pairs"].get(k)
                if c:
                    cells = [r["dim"], pair_names[k], *[_cell(c.get(x)) for x in CELLS], _cell(r.get("m"))]
                    cells.append(_cell(r.get("yuanxing")) if k == "F:A0" else "—")
                    lines.append("| " + " | ".join(str(x) for x in cells) + " |")
    if d.get("yuanxing_gate"):
        yg = d["yuanxing_gate"]
        lines += ["", f"原形门：**{GATE[yg['state']]}**" + (f"（{'；'.join(yg['why'])}）" if yg["why"] else "") + "。"]
    if d.get("outcome_proposed"):
        lines += ["", f"结局提议：**{OUTCOMES[d['outcome_proposed']]}**；品阶提议：{_cell(d.get('jie_proposed'))}。"]
        lines += [f"- {w}" for w in d.get("outcome_why", [])]
    lines += ["", "## 六、裁决", ""]
    v = d.get("verdict")
    if v:
        lines += [
            "| 项 | 内容 |",
            "| --- | --- |",
            f"| 裁决人 | {_cell(v['by'])} |",
            f"| 日期 | {_cell(v['date'])} |",
            f"| 结局 | {OUTCOMES[v['outcome']]} |",
            f"| 品阶 | {_cell(v.get('jie'))} |",
            f"| 附加条件 | {_cell('；'.join(v.get('conditions') or []))} |",
        ]
    else:
        lines.append("待裁。")
    lines += ["", "## 七、散火记录", ""]
    if d["reverts"]:
        lines += ["| 谁 | 何时 | 为什么 | 指回 |", "| --- | --- | --- | --- |"]
        lines += [f"| {r['by']} | {r['date']} | {_cell(r['why'])} | {_cell(r.get('back_to'))} |" for r in d["reverts"]]
    else:
        lines.append("无。")
    return "\n".join(lines) + "\n"
