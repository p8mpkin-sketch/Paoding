"""批次头：一轮运行开始前与结束后各记一笔，汇总从这里取不由运行本身带出来的那几栏。

    python -m liangju.pici start --batch <批次目录> --id S0-1 --purpose 起点轮 --arms arms.json \
        --config <引擎配置文件> --set-code <题集代号> --set-source 手出 [--runs 2] [--parallel 4] [--watchdog-s …]
    python -m liangju.pici start --batch <批次目录> --id P-1 --purpose 判定 --plan <试火计划文件> \
        --questions <题集文件> --config <引擎配置文件>
    python -m liangju.pici digest --questions <题集文件>
    python -m liangju.pici end --batch <批次目录> --config <引擎配置文件>

`arms.json`：`{臂名: {"role": …, "model": …, "version": …, "endpoint": …, "sampling": {…}, "metering": …,
"price_table": …}}`。`role` 取 benhuo（本火）、tonghuo（同火对照）、hehuo（合火）、yihuo（异火单炼）、
yuanxing（原形）。任何一条臂的模型栏空着，`start` 拒绝登记。

带 `--plan` 时，计划的哈希、逐臂一栏、盲判一栏（模型、版本、三段提示词的版本、抽样量、每题次的盲判时限）、花费
上限、看门狗的时限、题集的代号、来源与每题跑几次都从计划文件里取，不另抄一份；题集文件的摘要与题数对着计划核。
凡是登记时已经知道的都在登记时核对（见 `from_plan`），对不上就不登记。这时 `--arms`、`--set-code`、`--set-source`、
`--runs` 可以不给；给了就与计划逐项核对。带计划的批次现在只认五个臂名（B、B1、A1、F、A0）。
没有计划的批次（起点轮）用 `--arms` 登记，盲判一栏是空的，时限写「无」。

`start` 与 `end` 各记一次仓库的提交号、工作区是否干净、配置文件的摘要；两次不一样，汇总里「运行期间代码与配置是否
改动过」就是「是」。
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from liangju import mangpan
from liangju.common import Refused, read_json, sha, write_json

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("benhuo", "tonghuo", "hehuo", "yihuo", "yuanxing")
PURPOSES = ("起点轮", "中期旗帜", "判定")
ARM_FIELDS = ("role", "model", "version", "endpoint", "metering", "price_table")
# 带计划的批次：臂名与栏名都用试火计划的（`paoding_fenjue/shihuo.py`），角色由臂名定
PLAN_ROLES = {"B": "benhuo", "B1": "tonghuo", "A1": "yihuo", "F": "hehuo", "A0": "yuanxing"}
PLAN_ARM_FIELDS = ("model", "version", "endpoint", "sampling", "meter", "price_table")


def stamp(config: Path, repo: Path = ROOT) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "config_digest": sha(config.read_bytes()),
    }


def check_arms(arms: dict[str, Any]) -> None:
    if not arms:
        raise Refused("一条臂都没有登记")
    for name, a in arms.items():
        missing = [k for k in ARM_FIELDS if not str(a.get(k) or "").strip()]
        if missing:
            raise Refused(f"臂 {name} 缺 {missing}：每条臂都要钉住模型，栏空着不登记")
        if a["role"] not in ROLES:
            raise Refused(f"臂 {name} 的 role 只取 {ROLES}")


def _plan_arms(plan: dict[str, Any]) -> dict[str, Any]:
    """计划里逐臂那一栏，换成批次头的样子：各栏原样照搬，只添上由臂名定的角色。"""
    arms = plan.get("arms")
    if not isinstance(arms, dict) or not arms:
        raise Refused("计划里没有逐臂一栏")
    out: dict[str, Any] = {}
    for name, a in arms.items():
        if name not in PLAN_ROLES:
            raise Refused(f"计划里的臂 {name} 不认识：臂名只取 {tuple(PLAN_ROLES)}")
        a = a if isinstance(a, dict) else {}
        missing = [k for k in PLAN_ARM_FIELDS if k not in a or (k != "sampling" and not str(a[k] or "").strip())]
        if missing or not isinstance(a.get("sampling"), dict):
            raise Refused(f"计划里 {name} 臂缺 {missing or ['sampling']}：每条臂都要钉住模型，栏空着不登记")
        out[name] = {"role": PLAN_ROLES[name], **{k: a[k] for k in ("what", *PLAN_ARM_FIELDS) if k in a}}
    return out


def _same_arms(given: Any, planned: dict[str, Any]) -> None:
    """另给了一份臂的登记时，与计划逐项核对：一边有一边没有，或六栏里任何一项不同，都拒绝。"""
    given = given if isinstance(given, dict) else {}
    if set(given) != set(planned):
        raise Refused(f"要登记的臂 {sorted(given)} 与计划里逐臂一栏 {sorted(planned)} 不一致")
    for name in sorted(planned):
        g = given[name] if isinstance(given[name], dict) else {}
        diff = [k for k in PLAN_ARM_FIELDS if k not in g or g[k] != planned[name][k]]
        if diff:
            raise Refused(f"{name} 臂的 {diff} 与计划里登记的不同：臂以计划为准，计划登记之后不改")


def _cap(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def set_digest(questions: Any) -> tuple[str, int]:
    """题集的摘要与题数。摘要是题集文件内容（键排序、紧凑分隔的 JSON）的 sha256，与汇总里「题集摘要」是同一个数；
    试火计划的题集一栏里 `digest` 填的就是它（`python -m liangju.pici digest --questions <题集文件>`）。"""
    rows = questions.get("questions") if isinstance(questions, dict) else None
    if not isinstance(rows, list) or not rows:
        raise Refused("题集文件里没有题")
    return sha(questions), len(rows)


def _plan_set(plan: dict[str, Any], questions: Any, given: dict[str, Any]) -> dict[str, Any]:
    """题集的代号、来源、每题跑几次从计划里取；另给了就逐项核对。题集文件的摘要与题数也在这里对着计划核。"""
    raw = plan.get("questions")
    q: dict[str, Any] = raw if isinstance(raw, dict) else {}
    runs = q.get("runs")
    if any(not str(q.get(k) or "").strip() for k in ("set", "source", "digest")):
        raise Refused("计划里题集一栏不全：要有代号、来源与摘要")
    if isinstance(runs, bool) or not isinstance(runs, int) or runs <= 0:
        raise Refused("计划里没有写每条臂每道题跑几次")
    names = {"code": ("题集代号", q["set"]), "source": ("题集来源", q["source"]), "runs": ("每题跑的次数", runs)}
    for key, (zh, want) in names.items():
        got = given.get(key)
        if got is not None and str(got) != str(want):
            raise Refused(f"{zh}（{got}）与计划里登记的（{want}）不同：以计划为准，计划登记之后不改")
    if questions is None:
        raise Refused("带计划登记批次要给题集文件（--questions）：题集的摘要与题数在登记时对着计划核")
    digest, count = set_digest(questions)
    if digest != q["digest"]:
        raise Refused("题集文件的摘要与计划里登记的不同：这不是计划登记的那一套题")
    if count != q.get("count"):
        raise Refused(f"题集文件里有 {count} 道题，计划登记的是 {q.get('count')} 道")
    return {"question_set": {"code": q["set"], "source": q["source"], "digest": digest, "count": count}, "runs": runs}


def from_plan(
    plan: Any, arms: Any = None, questions: Any = None, given: dict[str, Any] | None = None
) -> dict[str, Any]:
    """带计划登记批次。凡是登记时已经知道的，都在这里核对，不等到花了钱再拒绝：

    - 计划盲判一栏里三段的版本与抽样量，要与现在磁盘上的尺子相同；
    - 花费上限两栏都要有，并且是正整数；看门狗的时限要有，并且是正数；
    - 逐臂一栏只有计划这一处来源：批次头里的臂从计划里取。另给了一份臂的登记（`arms`）就逐项核对，对不上就拒绝；
    - 盲判的模型与任何一条臂都不同；
    - 题集的代号、来源、每题跑几次从计划里取，另给了（`given`）就逐项核对；题集文件（`questions`）的摘要与题数
      要与计划登记的相同。

    带计划的批次现在只认五个臂名（`PLAN_ROLES`：B、B1、A1、F、A0），与判定函数的五条臂一一对应。第二对（另一个原形）
    来的时候要放开这张表，现在不放。

    跑完才知道的（读回的模型标识、功法摘要、花费合计）留在出记录时核。计划本身合不合规矩（上限是不是按规矩算出的、
    与炼档对不对得上）由登记计划的那一处查。"""
    judge = mangpan.plan_judge(plan)
    wrong = mangpan.ruler_matches(judge)
    if wrong:
        raise Refused(wrong[0])
    caps = plan.get("caps") if isinstance(plan.get("caps"), dict) else {}
    if not _cap(caps.get("per_item_usd_milli")) or not _cap(caps.get("total_usd_milli")):
        raise Refused("计划里的花费上限缺了或不是正数：每题次上限与总上限都要有，登记时就要定下")
    watchdog = plan.get("watchdog_seconds")
    if isinstance(watchdog, bool) or not isinstance(watchdog, int | float) or watchdog <= 0:
        raise Refused("计划里没有看门狗的时限，或不是正数：它在计划里按规矩算出，登记时就要定下")
    planned = _plan_arms(plan)
    if arms is not None:
        _same_arms(arms, planned)
    same = sorted(n for n, a in planned.items() if a["model"] == judge["model"])
    if same:
        raise Refused(f"盲判的模型与 {'、'.join(same)} 臂相同：盲判的模型必须与各臂不同")
    qs = _plan_set(plan, questions, given or {})
    return {
        "question_set": qs["question_set"],
        "runs_per_question": qs["runs"],
        "plan_hash": sha(plan),
        "judge": judge,
        "arms": planned,
        "watchdog_s": float(watchdog),
        "caps": {
            "per_question_usd_milli": caps["per_item_usd_milli"],
            "total_usd_milli": caps["total_usd_milli"],
        },
    }


def start(a: argparse.Namespace) -> int:
    given = read_json(Path(a.arms)) if a.arms else None
    planned = None
    if a.plan:
        said = {"code": a.set_code, "source": a.set_source, "runs": a.runs}
        questions = read_json(Path(a.questions)) if a.questions else None
        planned = from_plan(read_json(Path(a.plan)), given, questions, said)
    if planned:
        arms = planned["arms"]
    elif given is None or not a.set_code or not a.set_source:
        raise Refused("没有计划的批次要用 --arms 登记各臂，并给出题集的代号与来源（--set-code、--set-source）")
    else:
        arms = given
        check_arms(arms)
    if planned and a.watchdog_s:
        raise Refused("带计划的批次，看门狗的时限从计划里取，不另给 --watchdog-s")
    if a.purpose not in PURPOSES:
        raise Refused(f"用途只取 {PURPOSES}")
    out = Path(a.batch) / "batch.json"
    if out.exists():
        raise Refused(f"{out} 已经在了：一个批次只登记一次")
    doc = {
        "v": 1,
        "id": a.id,
        "date": datetime.date.today().isoformat(),
        "purpose": a.purpose,
        "plan_hash": planned["plan_hash"] if planned else "无",
        "judge": planned["judge"] if planned else None,
        "question_set": planned["question_set"] if planned else {"code": a.set_code, "source": a.set_source},
        "runs_per_question": planned["runs_per_question"] if planned else int(a.runs or 2),
        "parallel": int(a.parallel),
        "watchdog_s": planned["watchdog_s"] if planned else (float(a.watchdog_s) if a.watchdog_s else None),
        "arms": arms,
        "unequal": [],
        "yuanxing_gate": "可判" if any(x["role"] == "yuanxing" for x in arms.values()) else "未判：这一批没有跑原形臂",
        "caps": planned["caps"] if planned else {"per_question_usd_milli": None, "total_usd_milli": None},
        "start": stamp(Path(a.config)),
        "end": None,
        "converted_to_dev": 0,
        "added_questions": 0,
        "set_judged_times": 0,
        "reused": [],
        "reconciliation": {},
    }
    write_json(out, doc)
    print(f"批次 {a.id} 已登记：{out}")
    return 0


def end(a: argparse.Namespace) -> int:
    f = Path(a.batch) / "batch.json"
    doc = read_json(f)
    if doc.get("end"):
        raise Refused("这个批次已经记过结束")
    doc["end"] = stamp(Path(a.config))
    write_json(f, doc)
    same = doc["end"] == doc["start"] and not doc["end"]["dirty"]
    print("运行期间代码与配置没有改动" if same else "注意：运行期间代码或配置改动过，汇总里会照实写")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="liangju.pici")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    for name in ("batch", "id", "purpose", "config"):
        s.add_argument(f"--{name}", required=True)
    for name in ("set-code", "set-source", "arms", "plan", "questions", "runs"):
        s.add_argument(f"--{name}")
    s.add_argument("--parallel", default=4)
    s.add_argument("--watchdog-s")
    e = sub.add_parser("end")
    e.add_argument("--batch", required=True)
    e.add_argument("--config", required=True)
    g = sub.add_parser("digest", help="题集的摘要与题数：计划的题集一栏照它填")
    g.add_argument("--questions", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "digest":
            digest, count = set_digest(read_json(Path(a.questions)))
            print(json.dumps({"digest": digest, "count": count}))
            return 0
        return {"start": start, "end": end}[a.cmd](a)
    except Refused as x:
        print(f"拒绝：{x}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
