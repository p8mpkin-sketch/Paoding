"""炼化六步的数据操作（焚决 F5，docs/design/fenjue/02-lianhua.md）：一份炼档从识火走到定阶或散火。

这里只有纯函数：输入一份炼档（JSON 形状见 docs/design/fenjue/dossiers/TEMPLATE.json）与参数，返回改过的新炼档；
定阶与散火另返回改过的功法。读写文件、跑 git 与测试的是 scripts/lianhua.py。炼档的 .md 由 render() 从 JSON 生成，
所以下一次吞噬不用手写炼档：每一步的命令把这一步的产出写进 JSON，再重新生成 .md。

每一步只能在上一步之后做（STEP_AFTER）；预登记的读数在入位时写下，之后不能改（03 §4：赛后不许移动球门）。
"""

from __future__ import annotations

import copy
import math
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

# 量具（算“量具改动行数”用，现行设计 9.4）：检验代码、Schema、各张表、验收夹具与录音、体质试炼、评测台、
# 引擎之外的量具、判定函数与本文件、CI 检查。一次炼化对这些路径的改动行数目标也是 0；自炼的炼档非零即验体不过。
GAUGE_PATHS = (
    "fenjue/src/paoding_fenjue/lianhua.py",
    "fenjue/src/paoding_fenjue/readings.py",
    "fenjue/src/paoding_fenjue/engine/checks.py",
    "fenjue/src/paoding_fenjue/engine/schema.py",
    "fenjue/src/paoding_fenjue/engine/schemas/",
    "fenjue/src/paoding_fenjue/engine/tables/",
    "fenjue/tests/engine_fixtures/",
    "docs/design/fenjue/engine/schemas/",
    "tests/fenjue/",
    "scripts/lianhua.py",
    "liangju/",
    "eval/",
    "ci/",
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
ARMS = ("B", "B1", "A1", "F", "A0")  # 本火、同火对照、异火单炼、合火、原形（条件对等时是门，现行设计 4.1）
ORIGINS = ("自炼", "手工", "修订")  # 出身（现行设计 9.1）

# 原形门（现行设计第 4 节）。档号不小于 GATE_FROM 的炼档过这道门，之前的按档号豁免、照设门之前的判法判；
# 设成 None 就是不设门，整个判法回到设门之前。
GATE_FROM: int | None = 2
GATE_STATES = ("可判", "未判")
MARKS = {"未判": "原形门未判", "未过": "原形门未过"}
# 吸收目标维的输入：盲判给出的成对四格计数（前者对后者），键与量具汇总的写法一致
PAIRS = ("F_A0", "F_B", "F_A1", "B_B1")
CELLS = ("两边都过", "只有前者过", "只有后者过", "两边都没过")
PAIR_EXTRA = ("配上对的题次数",)
TRIALS = ("T1", "T2", "T3", "T4", "T5")


class StepError(ValueError):
    """这一步现在做不了：顺序不对、缺东西、或要改已登记的读数。"""


def _need(d: dict[str, Any], step: str) -> dict[str, Any]:
    if d["status"] not in STEP_AFTER[step]:
        raise StepError(f"炼档 {d['dossier']} 在 {d['status']}，{step} 要在 {'/'.join(STEP_AFTER[step])} 之后做")
    return copy.deepcopy(d)


# ---------------------------------------------------------------- ① 识火


def gated(d: dict[str, Any]) -> bool:
    """这份炼档过不过原形门：档号不小于 GATE_FROM 的过；读不成数的档号按过算。"""
    if GATE_FROM is None:
        return False
    try:
        return int(d["dossier"]) >= GATE_FROM
    except (TypeError, ValueError):
        return True


def noise_floor(d: int) -> int:
    """噪声底 m：2 倍的不一致题次数的平方根，向上取整，最小为 1（现行设计 4.6，P7）。"""
    return max(1, math.ceil(2 * math.sqrt(d) - 1e-9))


def gate_mark(d: dict[str, Any]) -> str | None:
    """炼档上公开显示的记号：原形门未判、原形门未过；判过了或不过门的没有记号。"""
    return MARKS.get((d.get("yuanxing") or {}).get("result", ""))


def new(
    no: str, name: str, title: str, today: str, shihuo: dict[str, Any], origin: str | None = None
) -> dict[str, Any]:
    """开一份炼档。shihuo：出处、现象、我们缺什么、是否异火（02 §3）。不是异火的不开档，进普通需求。
    origin：出身（自炼、手工、修订）。"""
    if origin is not None and origin not in ORIGINS:
        raise StepError(f"出身只能是 {'/'.join(ORIGINS)}")
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
        **({"origin": origin} if origin else {}),
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
    yuanxing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """火位与清单草稿、替换谁、各臂是什么、预登记读数（02 §5、03 §4）。读数登记之后不能改。

    yuanxing：原形门的对等声明，{state: 可判|未判, why}。与读数一样在入位时登记、之后不能改；不登记按未判算。

    group：火组的其余成员（12 §2.3），每个 {fire, replaces}；跨火位、行为有变的模式一个火位一团火，一份炼档一起走。"""
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
        if r.get("target") and r["kind"] != "异火":
            raise StepError(f"读数 {r['dim']}：吸收目标维要是异火维")
    declared = (d.get("yuanxing") or {}).get("state")
    if yuanxing is not None:
        state, reason = yuanxing.get("state"), str(yuanxing.get("why") or "")
        if state not in GATE_STATES:
            raise StepError(f"原形门的对等声明只能是 {'/'.join(GATE_STATES)}")
        if declared and (declared, (d["yuanxing"].get("why") or "")) != (state, reason):
            raise StepError("原形门的对等声明已经写下，不能改（跑完之后不许改口）；要换就开下一份炼档")
        if state == "未判" and not reason:
            raise StepError("原形门登记为未判要写原因（不对等在哪里、偏向哪一方）")
        if state == "可判" and not arms.get("A0"):
            raise StepError("原形门登记为可判要写明原形臂 A0 是什么")
        if state == "可判" and not any(r["kind"] == "异火" for r in readings):
            raise StepError("原形门登记为可判要至少登记一个异火维：门就判在异火维上")
    elif declared:
        raise StepError("原形门的对等声明已经写下，重新入位时要原样带上")
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
    d["metrics"]["slots"] = [fire["slot"], *[m["fire"]["slot"] for m in members]]
    if members:
        d["group"] = [{"fire": copy.deepcopy(m["fire"]), "replaces": m.get("replaces")} for m in members]
    if yuanxing is not None:
        d["yuanxing"] = {"state": yuanxing["state"], **({"why": yuanxing["why"]} if yuanxing.get("why") else {})}
    d["status"] = "placed"
    return d


def approve_design(d: dict[str, Any], by: str, date: str, note: str = "") -> dict[str, Any]:
    """前三节是设计 PR：裁决“值不值得炼”之后才进验体（02 §5 末）。"""
    d = _need(d, "approve_design")
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
    gauge_lines: int | None = None,
) -> dict[str, Any]:
    """静态验体的错误、动态验体（T1–T5 各自的结果）、体质改动行数、提交哈希（02 §6）。
    验体不判好坏，只判安全：任一条不过，融火时直接判反噬。

    gauge_lines：量具改动行数（现行设计 9.4），与体质改动行数并列记进炼档。出身是自炼的炼档这一项非零，
    验体不过：被度量的东西不得改度量它的尺子。不给就不记（设这条线之前的炼档）。"""
    d = _need(d, "yanti")
    if set(trials) != set(TRIALS):
        raise StepError(f"动态验体要有 {TRIALS} 五项的结果")
    errors = list(static_errors)
    if gauge_lines and d.get("origin") == "自炼":
        errors.append(f"量具改动行数 {gauge_lines}：自炼的炼档不许动量具，量具的改动单独提、单独裁")
    d["yanti"] = {
        "commit": commit,
        "kernel_lines": kernel_lines,
        **({"gauge_lines": gauge_lines} if gauge_lines is not None else {}),
        "static_errors": errors,
        "trials": {k: dict(trials[k]) for k in TRIALS},
        "passed": not errors and all(t.get("ok") for t in trials.values()),
    }
    d["kernel_lines_changed"] = kernel_lines
    d["metrics"]["kernel_lines"] = kernel_lines
    if gauge_lines is not None:
        d["gauge_lines_changed"] = gauge_lines
        d["metrics"]["gauge_lines"] = gauge_lines
    d["status"] = "trialed"
    return d


# ---------------------------------------------------------------- ⑤ 融火


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _net(pairs: dict[str, Any], name: str) -> int | None:
    """一对四格计数的净差：只有前者过的题次数减只有后者过的；这一对没填就没有。"""
    cells = pairs.get(name)
    return None if cells is None else int(cells["只有前者过"]) - int(cells["只有后者过"])


def _deltas(r: dict[str, Any]) -> tuple[float | None, float | None, float | None, float]:
    """一维读数上合火相对本火、异火单炼、原形的差（已按方向折成“越大越好”），以及噪声底。

    成对计数的维（吸收目标维）只读 pairs：差是净差，噪声底由本火对同火对照的不一致数算出，
    各臂的标量与手填的 m 一概不看（门的输入只有盲判的产出与花费记录，现行设计 5.5）。"""
    if "pairs" in r:
        pairs = r["pairs"]
        noise = pairs.get("B_B1")
        if noise is None or pairs.get("F_B") is None:
            raise StepError(f"读数 {r['dim']} 还缺成对计数 F_B 或 B_B1")
        m = float(noise_floor(int(noise["只有前者过"]) + int(noise["只有后者过"])))
        vs_b, vs_a1, vs_a0 = _net(pairs, "F_B"), _net(pairs, "F_A1"), _net(pairs, "F_A0")
        return vs_b, vs_a1, vs_a0, m
    s = 1.0 if r["dir"] == "up" else -1.0
    b, f, a1, a0 = _num(r.get("B")), _num(r.get("F")), _num(r.get("A1")), _num(r.get("A0"))
    if f is None:
        raise StepError(f"读数 {r['dim']} 还没有合火臂 F 的值")
    return (
        None if b is None else s * (f - b),
        None if a1 is None else s * (f - a1),
        None if a0 is None else s * (f - a0),
        _num(r.get("m")) or 0.0,
    )


def _base_outcome(d: dict[str, Any]) -> tuple[str, list[str]]:
    """设门之前的判法（03 §3）：只看本火、同火对照、异火单炼、合火四条臂。"""
    why: list[str] = []
    y = d["yanti"] or {}
    if not y.get("passed"):
        return "fanshi", ["验体没过"]
    has_a1 = bool(d["arms"].get("A1"))
    regress = native_regress = False
    emergent_ok: list[bool] = []
    wins = False
    for r in d["readings"]:
        if r["kind"] == "新生":
            s = 1.0 if r["dir"] == "up" else -1.0
            b, f, a1 = _num(r.get("B")), _num(r.get("F")), _num(r.get("A1"))
            if f is None:
                raise StepError(f"读数 {r['dim']} 还没有合火臂 F 的值")
            ok = s * (f - float(r["gate"])) >= 0 and (b or 0) == 0 and (a1 or 0) == 0
            emergent_ok.append(ok)
            r["verdict"] = "达门槛" if ok else "未达"
            continue
        vs_b, vs_a1, _, m = _deltas(r)
        if vs_b is None:
            raise StepError(f"读数 {r['dim']} 还没有本火臂 B 的值")
        if vs_b < -m or (r["kind"] == "异火" and vs_a1 is not None and vs_a1 < -m):
            r["verdict"] = "退"
            regress = True
            native_regress = native_regress or r["kind"] == "本火"
            continue
        if vs_b > m and (vs_a1 is None or vs_a1 > m):
            r["verdict"] = "胜"
            wins = True
        else:
            r["verdict"] = "不退"
    for r in d["readings"]:
        why.append(f"{r['dim']}（{r['kind']}）：{r['verdict']}")
    if native_regress:
        return "fanshi", [*why, "本火维退步：体质是底座，不让步"]
    if regress:
        return "binghuo", [*why, "共有维或异火维退步：不满足“不退”"]
    if emergent_ok and all(emergent_ok) and has_a1:
        return "huolian", why
    if emergent_ok and all(emergent_ok) and not has_a1:
        why.append("没有异火单炼臂 A′：结局最高合炼（FJ8）")
    if wins or (emergent_ok and all(emergent_ok)):
        return "helian", why
    return "binghuo", [*why, "没有任何一维胜过两个来源：收藏不是炼化"]


def judge(d: dict[str, Any]) -> tuple[str, list[str]]:
    """判结局，返回结局与每一维的判及理由。先按 03 §3 判（达门槛、不退、胜、退）；本来够得上火莲或合炼的，
    过门的炼档再过原形门（现行设计 4.3）：

    - 门可判：每个异火维上合火不低于原形减噪声底才收；有一维低了就是“不及原形”，不收。
    - 门未判（入位时登记为未判，或根本没登记）：结局最高合炼，炼档挂“原形门未判”。

    门的结果写进 d["yuanxing"]["result"]（过、未过、未判）。本来就不收的（并火、反噬）不到这道门。"""
    outcome, why = _base_outcome(d)
    if not gated(d):
        return outcome, why
    gate = dict(d.get("yuanxing") or {})
    gate.pop("result", None)
    gate.pop("short", None)
    d["yuanxing"] = gate
    if outcome not in TAKEN:
        return outcome, why
    foreign = [r for r in d["readings"] if r["kind"] == "异火"]
    if gate.get("state") != "可判" or not foreign:
        reason = gate.get("why") or ("没有登记异火维" if gate.get("state") == "可判" else "入位时没有登记原形门")
        gate["result"] = "未判"
        why = [*why, f"原形门未判（{reason}）：结局最高合炼"]
        return "helian", why
    short = []
    for r in foreign:
        _, _, vs_a0, m = _deltas(r)
        if vs_a0 is None:
            raise StepError(f"读数 {r['dim']} 还没有原形臂 A0 的值：原形门登记为可判，每个异火维都要有")
        ok = vs_a0 >= -m
        r["gate_verdict"] = "不低于原形" if ok else "不及原形"
        why = [*why, f"原形门 {r['dim']}：合火比原形 {vs_a0:+g}，噪声底 {m:g}，{r['gate_verdict']}"]
        if not ok:
            short.append({"dim": r["dim"], "by": -vs_a0, "m": m})
    if short:
        gate["result"] = "未过"
        gate["short"] = short
        return "buji", [*why, "对等条件下输给原形：移植丢了东西，不收；可以带着新的萃意再炼"]
    gate["result"] = "过"
    return outcome, why


def _check_pairs(dim: str, pairs: Any) -> None:
    """成对计数的形状：只许 PAIRS 里的几对，每对四个非负整数的格子。多出任何一栏都拒收，
    这样各臂内部的字段（核对标注、工单、细事实）混不进门的输入。"""
    if not isinstance(pairs, dict) or not pairs:
        raise StepError(f"读数 {dim} 的 pairs 要是 {PAIRS} 里的成对计数")
    bad = set(pairs) - set(PAIRS)
    if bad:
        raise StepError(f"读数 {dim} 的成对计数只能有 {PAIRS}，多了 {sorted(bad)}")
    for name, cells in pairs.items():
        if not isinstance(cells, dict) or set(cells) - set(PAIR_EXTRA) != set(CELLS):
            raise StepError(f"读数 {dim} 的 {name} 要恰好有 {CELLS} 四格")
        for k, v in cells.items():
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise StepError(f"读数 {dim} 的 {name}.{k} 要是非负整数")


def ronghuo(d: dict[str, Any], values: dict[str, dict[str, Any]], jie_now: int) -> dict[str, Any]:
    """填各臂读数（dim → {B, B1, A1, F, A0, m, n}），判结局，提议品阶。没给 m 时用 |B − B′| 作噪声底。

    吸收目标维（入位时登记 target 的异火维）在过门的炼档里只收成对计数 pairs（盲判的四格计数），不收标量。"""
    d = _need(d, "ronghuo")
    dims = {r["dim"] for r in d["readings"]}
    unknown = set(values) - dims
    if unknown:
        raise StepError(f"这几维没有预登记：{sorted(unknown)}（赛后不许加维）")
    for r in d["readings"]:
        v = values.get(r["dim"], {})
        bad = set(v) - {*ARMS, "m", "n", "note", "pairs"}
        if bad:
            raise StepError(f"读数 {r['dim']} 只能填 {ARMS}、m、n、note、pairs，多了 {sorted(bad)}")
        if "pairs" in v:
            _check_pairs(r["dim"], v["pairs"])
        if r.get("target") and gated(d) and v:
            if "pairs" not in v or set(v) & {*ARMS, "m"}:
                raise StepError(f"读数 {r['dim']} 是吸收目标维：只收盲判的成对计数 pairs，不收各臂的标量与手填的 m")
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
        + (f"；{gate_mark(d)}" if gate_mark(d) else ""),
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
    if d.get("origin"):
        lines.append(f"| 出身 | {_cell(d['origin'])} |")
    yx = d.get("yuanxing") or {}
    if yx.get("state"):
        lines.append(
            f"| 原形门 | {_cell(yx['state'])}{('：' + _cell(yx['why'])) if yx.get('why') else ''}"
            "（对等声明，入位时写下，之后不改） |"
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
        ]
        if "gauge_lines" in y:
            lines.append(
                f"- 量具改动行数：**{y['gauge_lines']}**"
                + ("（非 0：量具的改动应单独提、单独裁）" if y["gauge_lines"] else "")
            )
        lines += [
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
    if yx.get("state") == "可判":
        arm_names["A0"] = "A° 原形（门）"
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
            "| 维 | 成对 | " + " | ".join(CELLS) + " |",
            "| --- | --- | " + " | ".join(["---"] * len(CELLS)) + " |",
        ]
        pair_names = {"F_A0": "合火对原形", "F_B": "合火对本火", "F_A1": "合火对异火单炼", "B_B1": "本火对同火对照"}
        for r in paired:
            for name in PAIRS:
                if name in r["pairs"]:
                    counts = " | ".join(str(r["pairs"][name][c]) for c in CELLS)
                    lines.append(f"| {_cell(r['dim'])} | {pair_names[name]} | {counts} |")
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
