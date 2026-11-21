"""炼化六步的数据操作（焚决 F5，docs/design/fenjue/02-lianhua.md）：一份炼档从识火走到定阶或散火。

这里只有纯函数：输入一份炼档（JSON 形状见 docs/design/fenjue/dossiers/TEMPLATE.json）与参数，返回改过的新炼档；
定阶与散火另返回改过的功法。读写文件、跑 git 与测试的是 scripts/lianhua.py。炼档的 .md 由 render() 从 JSON 生成，
所以下一次吞噬不用手写炼档：每一步的命令把这一步的产出写进 JSON，再重新生成 .md。

每一步只能在上一步之后做（STEP_AFTER）；预登记的读数在入位时写下，之后不能改（03 §4：赛后不许移动球门）。
"""

from __future__ import annotations

import copy
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
OUTCOMES = {"huolian": "火莲", "helian": "合炼", "binghuo": "并火", "fanshi": "反噬"}
TAKEN = ("huolian", "helian")
ARMS = ("B", "B1", "A1", "F", "A0")  # 本火、同火对照、异火单炼、合火、原形参照（只作参考）
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
) -> dict[str, Any]:
    """火位与清单草稿、替换谁、各臂是什么、预登记读数（02 §5、03 §4）。读数登记之后不能改。

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
) -> dict[str, Any]:
    """静态验体的错误、动态验体（T1–T5 各自的结果）、体质改动行数、提交哈希（02 §6）。
    验体不判好坏，只判安全：任一条不过，融火时直接判反噬。"""
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
    d["kernel_lines_changed"] = kernel_lines
    d["metrics"]["kernel_lines"] = kernel_lines
    d["status"] = "trialed"
    return d


# ---------------------------------------------------------------- ⑤ 融火


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def judge(d: dict[str, Any]) -> tuple[str, list[str]]:
    """按 03 §3 判结局，返回结局与每一维的判（达门槛、不退、胜、退）及理由。"""
    why: list[str] = []
    y = d["yanti"] or {}
    if not y.get("passed"):
        return "fanshi", ["验体没过"]
    has_a1 = bool(d["arms"].get("A1"))
    regress = native_regress = False
    emergent_ok: list[bool] = []
    wins = False
    for r in d["readings"]:
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


def ronghuo(d: dict[str, Any], values: dict[str, dict[str, Any]], jie_now: int) -> dict[str, Any]:
    """填各臂读数（dim → {B, B1, A1, F, A0, m, n}），判结局，提议品阶。没给 m 时用 |B − B′| 作噪声底。"""
    d = _need(d, "ronghuo")
    dims = {r["dim"] for r in d["readings"]}
    unknown = set(values) - dims
    if unknown:
        raise StepError(f"这几维没有预登记：{sorted(unknown)}（赛后不许加维）")
    for r in d["readings"]:
        v = values.get(r["dim"], {})
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
        + (f"；裁决：{OUTCOMES[d['verdict']['outcome']]}" if d.get("verdict") else ""),
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
