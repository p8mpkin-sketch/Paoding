"""汇总：从盲判的产出与花费记录生成现行设计第 13 节的汇总数。没有需要人填的栏。

    python -m liangju.huizong --batch <批次目录> --questions questions.json

读：`batch.json`（批次头）、`attempts/`（题次记录）、`index.json` 与 `verdicts/`（盲判）、`findings.jsonl`、
`selfcheck.json`、`rejudge.json`、`judge_failures.json`。写：`summary.json` 与 `summary.md`。

汇总里只有计数、比例、代号与摘要。题面、子问、仓库名、文件路径、引用内容、回答原文、发现记录里的那句自由文字与
证据指针、失败的原始输出，都不出现（第 13.9 节；`tests/test_huizong.py` 用哨兵字符串查这一条）。

过线（第 5.3 节）三条都成立才算过：答到（每个子问都判为答到）、属实（抽到的结论没有一条被否定或找不到依据）、
在预算内完成（正常结束，且折算后的花费不超过每题上限）。每题上限取批次头里计划的那个数；没有计划时取这次运行
自己的上限。
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from liangju import mangpan, tici
from liangju.common import Refused, read_json, read_jsonl, sha, write_json

PAIRS = (  # (前者, 后者)：按角色配对，只填这一批里两边都有的
    ("benhuo", "tonghuo"),
    ("hehuo", "yuanxing"),
    ("hehuo", "benhuo"),
    ("hehuo", "yihuo"),
    ("benhuo", "yuanxing"),
)
ROLE_ZH = {"benhuo": "本火", "tonghuo": "同火对照", "hehuo": "合火", "yihuo": "异火单炼", "yuanxing": "原形"}
AXES = {
    "language": "语言",
    "size": "仓库大小",
    "ask": "问法",
    "premise": "前提是否成立",
    "where": "答案在代码还是在配置文档",
}
REASONS = {
    "watchdog": "看门狗超时",
    "over_budget": "超出预算",
    "model_failure": "模型调用失败",
    "unreadable_repo": "读不进仓库",
    "other": "其他",
}
ADVERSE_ZH = {
    "partial": "部分答到",
    "missing": "没答到",
    "refuted": "被原文否定",
    "no_basis": "找不到依据",
    "incomplete": "没完成或超出预算",
}
SMALL = 3  # 某一格少于这么多道题就并进「其他」


def noise_floor(d: int) -> int:
    """噪声底（cz 2026-11-27 定）：2 倍的不一致题次数的平方根，向上取整，最小为 1。"""
    return max(1, math.ceil(2 * math.sqrt(d) - 1e-9))


def _norm(s: str) -> str:
    return "".join(s.split())


class Row:
    """一个题次在汇总里要用的东西。"""

    def __init__(self, a: tici.Attempt, verdict: dict[str, Any] | None, judged: bool, cap: int | None) -> None:
        self.a, self.v, self.judged = a, verdict, judged
        self.answered = bool(verdict and verdict["answered"])
        self.true = bool(verdict and verdict["true"])
        self.within = a.status == "finished" and (cap is None or a.cost_usd_milli <= cap)
        self.passed = self.answered and self.true and self.within


def _engine_marked_negated(rows: list[Row]) -> str:
    """引擎自己标为已核对的结论，被盲判抽样否定的比例（量的是引擎内的核对靠不靠得住）。"""
    hit = bad = 0
    for r in rows:
        if r.v is None or r.a.answer is None:
            continue
        marked = [_norm(it["text"]) for it in r.a.own.get("engine_items", []) if it["verdict"] == "supported"]
        for c in r.v["sampled"]:
            quote = _norm(r.a.answer[c["at"][0] : c["at"][1]])
            if any(m and (m in quote or quote in m) for m in marked):
                hit += 1
                bad += int(c["verdict"] != "holds")
    return f"{bad}/{hit}" if hit else "抽到的结论里没有引擎标为已核对的"


def _prompts_version(verdicts: list[dict[str, Any]], selfcheck: dict[str, Any] | None) -> str:
    """盲判三段的版本，取自记录：每份判的记录里判的时候记下的摘要，与自检记录里的摘要。

    不取汇总这一刻磁盘上的提示词：判完之后提示词改过的话，那个数说的不是这一批。两处记录对不上就照实写。"""
    judged = sorted({str(v.get("prompts") or "记录里没有") for v in verdicts})
    checked = str(selfcheck.get("prompts") or "记录里没有") if selfcheck else None
    if not judged and checked is None:
        return "还没有判，也没有自检记录"
    if len(judged) == 1 and checked in (None, judged[0]):
        return judged[0] + ("" if checked else "（没有自检记录）")
    if not judged:
        return f"{checked}（只有自检记录，还没有判）"
    return f"不一致（判的记录：{'、'.join(judged)}；自检记录：{checked or '没有'}）"


def _arm(name: str, reg: dict[str, Any], rows: list[Row]) -> dict[str, Any]:
    by_q: dict[str, list[Row]] = {}
    for r in rows:
        by_q.setdefault(r.a.question, []).append(r)
    subs = Counter(s["verdict"] for r in rows if r.v for s in r.v["subquestions"])
    sampled = Counter(c["verdict"] for r in rows if r.v for c in r.v["sampled"])
    costs = [r.a.cost_usd_milli for r in rows]
    times = [r.a.elapsed_s for r in rows if r.a.elapsed_s is not None]
    out: dict[str, Any] = {
        "臂": name,
        "角色": ROLE_ZH[reg["role"]],
        "功法摘要": sorted({r.a.gongfa for r in rows if r.a.gongfa}) or ["导出里没有"],
        "题次数": len(rows),
        "过线的题次数": sum(r.passed for r in rows),
        "每次都过线的题数": sum(all(r.passed for r in rs) for rs in by_q.values()),
        "三条各自满足的题次数": {
            "答到": sum(r.answered for r in rows),
            "属实": sum(r.true for r in rows),
            "在预算内完成": sum(r.within for r in rows),
        },
        "子问计数": {
            "答到": subs["answered"],
            "部分答到": subs["partial"],
            "没答到": subs["missing"],
            "其中前提不成立且有证据而算答到的": sum(
                s["premise_false"] for r in rows if r.v for s in r.v["subquestions"]
            ),
        },
        "抽样核对": {
            "抽了": sum(sampled.values()),
            "成立": sampled["holds"],
            "被原文否定": sampled["refuted"],
            "找不到依据": sampled["no_basis"],
        },
        "花费（毫美元，同一张价表折算）": {
            "合计": sum(costs),
            "每题次中位数": statistics.median(costs) if costs else None,
            "每题次最大值": max(costs, default=None),
        },
        "用量": {
            "新输入": sum(r.a.usage["input"] for r in rows),
            "命中缓存的输入": sum(r.a.usage["cached_input"] for r in rows),
            "输出": sum(r.a.usage["output"] for r in rows),
            "调用次数": sum(r.a.usage["calls"] for r in rows),
        },
        "用时（秒）": {
            "每题次中位数": statistics.median(times) if times else None,
            "每题次最大值": max(times, default=None),
        },
        "没完成的题次数": {zh: sum(r.a.status == code for r in rows) for code, zh in REASONS.items()},
        "正常结束而交付里没有回答的题次数": sum(r.a.status == "finished" and r.a.answer is None for r in rows),
        "交出了回答而盲判没做成的题次数": sum(r.a.answer is not None and not r.judged for r in rows),
    }
    if any("route" in r.a.own for r in rows):  # 只有我们自己的臂才有的，只报告，不进门
        defs = Counter(n for r in rows for n in (r.a.own.get("on_defs") or []))
        out["只报告、不进门"] = {
            "因时间线停下的题次数": sum(r.a.own.get("timeline_stop") is True for r in rows),
            "工单": "不适用（工单回路还没有上线）",
            "各项检验的首次通过率": "导出里没有",
            "引擎标为已核对而被盲判抽样否定（否定数/抽到数）": _engine_marked_negated(rows),
            "每个子问引用落在定义体内的条数分布（条数: 子问数）": {str(k): defs[k] for k in sorted(defs)},
        }
    return out


def _pair(first: list[Row], second: list[Row]) -> dict[str, int]:
    a = {r.a.key: r.passed for r in first}
    b = {r.a.key: r.passed for r in second}
    keys = sorted(a.keys() & b.keys())
    return {
        "两边都过": sum(a[k] and b[k] for k in keys),
        "只有前者过": sum(a[k] and not b[k] for k in keys),
        "只有后者过": sum(b[k] and not a[k] for k in keys),
        "两边都没过": sum(not a[k] and not b[k] for k in keys),
        "配上对的题次数": len(keys),
    }


def _axes(questions: dict[str, dict[str, Any]], arms: dict[str, list[Row]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, zh in AXES.items():
        value = {qid: str((q.get("axes") or {}).get(key, "未标")) for qid, q in questions.items()}
        sizes = Counter(value.values())
        cell = {qid: (v if sizes[v] >= SMALL else "其他") for qid, v in value.items()}
        table: dict[str, Any] = {}
        for name, rows in arms.items():
            passed: Counter[str] = Counter()
            total: Counter[str] = Counter()
            for r in rows:
                c = cell.get(r.a.question, "其他")
                total[c] += 1
                passed[c] += int(r.passed)
            table[name] = {c: f"{passed[c]}/{total[c]}" for c in sorted(total)}
        out[zh] = table
    return out


def build(batch_dir: Path, questions_path: Path) -> dict[str, Any]:
    if not (batch_dir / "batch.json").exists():
        raise Refused(f"{batch_dir} 里没有批次头（batch.json）")
    batch = read_json(batch_dir / "batch.json")
    qdoc = read_json(questions_path)
    questions = {str(q["id"]): q for q in qdoc["questions"]}
    attempts = tici.load_all(batch_dir)
    if not attempts:
        raise Refused("这个批次里没有题次记录")
    index = {(i["arm"], i["question"], i["rep"]): i["blind"] for i in read_json(batch_dir / "index.json")}
    plan_cap = (batch.get("caps") or {}).get("per_question_usd_milli")
    arms: dict[str, list[Row]] = {}
    for a in attempts:
        if a.arm not in batch["arms"]:
            raise Refused(f"题次记录里的臂 {a.arm} 没有在批次头登记")
        blind = index.get((a.arm, a.question, a.rep))
        f = batch_dir / "verdicts" / f"{blind}.json"
        v = read_json(f) if blind and f.exists() else None
        arms.setdefault(a.arm, []).append(
            Row(a, v, v is not None, plan_cap if plan_cap is not None else a.cap_usd_milli)
        )
    by_role = {batch["arms"][name]["role"]: name for name in arms}

    registry = []
    for name, reg in batch["arms"].items():
        seen = sorted({m for r in arms.get(name, []) for m in r.a.models_seen})
        registry.append(
            {
                "臂": name,
                "模型": reg["model"],
                "版本标识": reg["version"],
                "端点": reg["endpoint"],
                "采样参数": reg.get("sampling") or {},
                "计量来源": reg["metering"],
                "价表版本": reg["price_table"],
                "运行记录里读回的模型标识与登记一致": bool(seen) and seen == [reg["model"]],
            }
        )

    pairs = {}
    for first, second in PAIRS:
        if first in by_role and second in by_role:
            cells = _pair(arms[by_role[first]], arms[by_role[second]])
            if (first, second) == ("benhuo", "tonghuo"):
                d = cells["只有前者过"] + cells["只有后者过"]
                cells.update({"不一致数 d": d, "噪声底 m": noise_floor(d)})
            pairs[f"{ROLE_ZH[first]}对{ROLE_ZH[second]}"] = cells

    found = read_jsonl(batch_dir / "findings.jsonl")
    sc = read_json(batch_dir / "selfcheck.json") if (batch_dir / "selfcheck.json").exists() else None
    rj = read_json(batch_dir / "rejudge.json") if (batch_dir / "rejudge.json").exists() else None
    fails = read_json(batch_dir / "judge_failures.json") if (batch_dir / "judge_failures.json").exists() else {}
    verdicts = [r.v for rs in arms.values() for r in rs if r.v]
    judge_model = sorted({(r.v["model"], r.v["model_version"]) for rs in arms.values() for r in rs if r.v})
    limit = (batch.get("judge") or {}).get("seconds_per_item")
    timed = [float(v["seconds"]) for v in verdicts if isinstance(v.get("seconds"), int | float)]
    start, end = batch.get("start") or {}, batch.get("end")
    changed = end is None or end != start or bool(start.get("dirty"))
    gongfa = {r.a.gongfa for rs in arms.values() for r in rs}

    return {
        "批次头": {
            "批次号": batch["id"],
            "日期": batch["date"],
            "用途": batch["purpose"],
            "试火计划的哈希": batch["plan_hash"],
            "题集代号": batch["question_set"]["code"],
            "题集摘要": sha(qdoc),
            "题集来源": batch["question_set"]["source"],
            "题数": len(questions),
            "每条臂每道题跑的次数": batch["runs_per_question"],
            "引擎的提交号": start.get("commit"),
            "配置摘要": start.get("config_digest"),
            "功法摘要": sorted(g for g in gongfa if g) or ["导出里没有"],
            "各题次开题时的设置摘要": sorted({r.a.settings for rs in arms.values() for r in rs if r.a.settings})
            or ["导出里没有"],
            "盲判三段的版本": _prompts_version(verdicts, sc),
            "盲判用的模型": [f"{n}（{ver}）" for n, ver in judge_model] or ["还没有判"],
            "每题次的盲判时限（秒）": limit if limit is not None else "无",
            "抽样量": f"每个子问 {mangpan.PER_SUBQ} 条，一份回答至多 {mangpan.PER_ANSWER} 条",
            "归类器的版本": "未就位（第 1 步）",
            "并行路数": batch["parallel"],
            "看门狗的时限（秒）": batch["watchdog_s"] if batch["watchdog_s"] is not None else "没有设",
            "每题上限的来源": "试火计划" if plan_cap is not None else "各次运行自己的上限",
        },
        "逐臂登记": {
            "各臂": registry,
            "不对等的项": batch.get("unequal") or "无",
            "原形门的状态": batch["yuanxing_gate"],
        },
        "每条臂一组": [_arm(name, batch["arms"][name], rows) for name, rows in sorted(arms.items())],
        "成对比较": pairs,
        "按轴分层（过线题次/题次）": _axes(questions, arms),
        "发现与类别": {
            "发现记录数": {zh: sum(r["verdict"] == k for r in found) for k, zh in ADVERSE_ZH.items()}
            | {"合计": len(found)},
            "类别": "归类器未就位：发现记录先存着，第 1 步补算",
        },
        "量具自检": {
            "盲判的自检样本": {k: ("判对" if r["ok"] else "判错") for k, r in sc["results"].items()}
            if sc
            else "没有记录",
            "自检时每个题次的盲判用时（秒）": {k: r.get("seconds", "没有记") for k, r in sc["results"].items()}
            if sc
            else "没有记录",
            "正式判时用时超过时限的回答份数": sum(t > limit for t in timed) if limit is not None else "无（没有时限）",
            "重判一致率": f"{rj['agree']}/{rj['chosen']}（另有 {rj['failed']} 份没做成）" if rj else "没有重判",
            "盲判没做成的回答份数": len(fails),
            "回原文搜索超过时间上限的次数": sum(int(v.get("search_timeouts") or 0) for v in verdicts),
            "导出的用量与服务商账单的对账差异": batch.get("reconciliation") or "未对账",
        },
        "完整性": {
            "运行期间代码与配置是否改动过": "是（或没有记结束）" if changed else "否",
            "各题次的功法摘要是否一致": len(gongfa) == 1,
            "这一批里转成开发题的数量": batch["converted_to_dev"],
            "补进来的新题数量": batch["added_questions"],
            "这套题集已经用于判定的次数": batch["set_judged_times"],
            "复用了哪些臂的结果": batch["reused"] or "无",
        },
    }


def render(doc: Any, depth: int = 0) -> list[str]:
    pad = "  " * depth
    if isinstance(doc, dict):
        out = []
        for k, v in doc.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}- {k}：")
                out += render(v, depth + 1)
            else:
                out.append(f"{pad}- {k}：{_scalar(v)}")
        return out
    if isinstance(doc, list):
        out = []
        for v in doc:
            if isinstance(v, (dict, list)):
                out += render(v, depth) + [""]
            else:
                out.append(f"{pad}- {_scalar(v)}")
        return out
    return [f"{pad}{_scalar(doc)}"]


def _scalar(v: Any) -> str:
    if v is True:
        return "是"
    if v is False:
        return "否"
    if v is None or v == {} or v == []:
        return "无"
    return str(v)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="liangju.huizong")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--questions", required=True)
    a = ap.parse_args(argv)
    try:
        doc = build(Path(a.batch), Path(a.questions))
    except Refused as e:
        print(f"拒绝：{e}", file=sys.stderr)
        return 2
    write_json(Path(a.batch) / "summary.json", doc)
    lines = ["# 试火汇总", ""]
    for title, body in doc.items():
        lines += [f"## {title}", "", *render(body), ""]
    (Path(a.batch) / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"写好了 {Path(a.batch) / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
