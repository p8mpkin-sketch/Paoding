"""批次头：一轮运行开始前与结束后各记一笔，汇总从这里取不由运行本身带出来的那几栏。

    python -m liangju.pici start --batch <批次目录> --id S0-1 --purpose 起点轮 --arms arms.json \
        --config <引擎配置文件> --set-code <题集代号> --set-source 手出 \
        [--plan-hash …] [--runs 2] [--parallel 4] [--watchdog-s …]
    python -m liangju.pici end --batch <批次目录> --config <引擎配置文件>

`arms.json`：`{臂名: {"role": …, "model": …, "version": …, "endpoint": …, "sampling": {…}, "metering": …,
"price_table": …}}`。`role` 取 benhuo（本火）、tonghuo（同火对照）、hehuo（合火）、yihuo（异火单炼）、
yuanxing（原形）。任何一条臂的模型栏空着，`start` 拒绝登记。

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

from liangju.common import Refused, read_json, sha, write_json

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("benhuo", "tonghuo", "hehuo", "yihuo", "yuanxing")
PURPOSES = ("起点轮", "中期旗帜", "判定")
ARM_FIELDS = ("role", "model", "version", "endpoint", "metering", "price_table")


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


def start(a: argparse.Namespace) -> int:
    arms = read_json(Path(a.arms))
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
        "plan_hash": a.plan_hash or "无",
        "question_set": {"code": a.set_code, "source": a.set_source},
        "runs_per_question": int(a.runs),
        "parallel": int(a.parallel),
        "watchdog_s": float(a.watchdog_s) if a.watchdog_s else None,
        "arms": arms,
        "unequal": [],
        "yuanxing_gate": "可判" if any(x["role"] == "yuanxing" for x in arms.values()) else "未判：这一批没有跑原形臂",
        "caps": {"per_question_usd_milli": None, "total_usd_milli": None},
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
    for name in ("batch", "id", "purpose", "arms", "config", "set-code", "set-source"):
        s.add_argument(f"--{name}", required=True)
    s.add_argument("--plan-hash")
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
