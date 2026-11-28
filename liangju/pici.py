"""批次头：一轮运行开始前与结束后各记一笔，汇总从这里取不由运行本身带出来的那几栏。

    python -m liangju.pici start --batch <批次目录> --id S0-1 --purpose 起点轮 --arms arms.json \
        --config <引擎配置文件> --set-code <题集代号> --set-source 手出 [--runs 2] [--parallel 4] [--watchdog-s …]
    python -m liangju.pici start --batch <批次目录> --id P-1 --purpose 判定 --plan <试火计划文件> \
        --config <引擎配置文件> --set-code <题集代号> --set-source 生成
    python -m liangju.pici end --batch <批次目录> --config <引擎配置文件>

`arms.json`：`{臂名: {"role": …, "model": …, "version": …, "endpoint": …, "sampling": {…}, "metering": …,
"price_table": …}}`。`role` 取 benhuo（本火）、tonghuo（同火对照）、hehuo（合火）、yihuo（异火单炼）、
yuanxing（原形）。任何一条臂的模型栏空着，`start` 拒绝登记。

带 `--plan` 时，计划的哈希、逐臂一栏、盲判一栏（模型、版本、三段提示词的版本、抽样量、每题次的盲判时限）与花费
上限都从计划文件里取，不另抄一份；凡是登记时已经知道的都在登记时核对（见 `from_plan`），对不上就不登记。这时
`--arms` 可以不给；给了就与计划逐项核对。没有计划的批次（起点轮）用 `--arms` 登记，盲判一栏是空的，时限写「无」。

`start` 与 `end` 各记一次仓库的提交号、工作区是否干净、配置文件的摘要；两次不一样，汇总里「运行期间代码与配置是否
改动过」就是「是」。
"""

from __future__ import annotations

import argparse
import datetime
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


def from_plan(plan: Any, arms: Any = None) -> dict[str, Any]:
    """带计划登记批次。凡是登记时已经知道的，都在这里核对，不等到花了钱再拒绝：

    - 计划盲判一栏里三段的版本与抽样量，要与现在磁盘上的尺子相同；
    - 花费上限两栏都要有，并且是正整数；
    - 逐臂一栏只有计划这一处来源：批次头里的臂从计划里取。另给了一份臂的登记（`arms`）就逐项核对，对不上就拒绝；
    - 盲判的模型与任何一条臂都不同。

    跑完才知道的（读回的模型标识、功法摘要、花费合计）留在出记录时核。计划本身合不合规矩（上限是不是按规矩算出的、
    与炼档对不对得上）由登记计划的那一处查。"""
    judge = mangpan.plan_judge(plan)
    wrong = mangpan.ruler_matches(judge)
    if wrong:
        raise Refused(wrong[0])
    caps = plan.get("caps") if isinstance(plan.get("caps"), dict) else {}
    if not _cap(caps.get("per_item_usd_milli")) or not _cap(caps.get("total_usd_milli")):
        raise Refused("计划里的花费上限缺了或不是正数：每题次上限与总上限都要有，登记时就要定下")
    planned = _plan_arms(plan)
    if arms is not None:
        _same_arms(arms, planned)
    same = sorted(n for n, a in planned.items() if a["model"] == judge["model"])
    if same:
        raise Refused(f"盲判的模型与 {'、'.join(same)} 臂相同：盲判的模型必须与各臂不同")
    return {
        "plan_hash": sha(plan),
        "judge": judge,
        "arms": planned,
        "caps": {
            "per_question_usd_milli": caps["per_item_usd_milli"],
            "total_usd_milli": caps["total_usd_milli"],
        },
    }


def start(a: argparse.Namespace) -> int:
    given = read_json(Path(a.arms)) if a.arms else None
    planned = from_plan(read_json(Path(a.plan)), given) if a.plan else None
    if planned:
        arms = planned["arms"]
    elif given is None:
        raise Refused("没有计划的批次要用 --arms 登记各臂")
    else:
        arms = given
        check_arms(arms)
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
        "question_set": {"code": a.set_code, "source": a.set_source},
        "runs_per_question": int(a.runs),
        "parallel": int(a.parallel),
        "watchdog_s": float(a.watchdog_s) if a.watchdog_s else None,
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
    for name in ("batch", "id", "purpose", "config", "set-code", "set-source"):
        s.add_argument(f"--{name}", required=True)
    s.add_argument("--arms")
    s.add_argument("--plan")
    s.add_argument("--runs", default=2)
    s.add_argument("--parallel", default=4)
    s.add_argument("--watchdog-s")
    e = sub.add_parser("end")
    e.add_argument("--batch", required=True)
    e.add_argument("--config", required=True)
    a = ap.parse_args(argv)
    try:
        return {"start": start, "end": end}[a.cmd](a)
    except Refused as x:
        print(f"拒绝：{x}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
