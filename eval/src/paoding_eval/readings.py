"""读数的证据链：每次运行的 meta.json，以及把一批运行的原始记录收进仓库（collect）。

record.json 的字段由 cz 定（record.py），这里不动它；运行器提交号、清单摘要、沙箱镜像等放在旁边的 meta.json。
清单摘要去掉了 answer：同一题集的两批读数摘要相同，而摘要本身推不出答案。

collect 只拷 record.json 与 meta.json（两者都不含答案与密钥），每条运行一个文件，另写一张 summary.md。
CLI 的流水、工作区、事件日志这些大件留在 runs/ 里，不入库。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .harness import ROOT
from .record import Record
from .spec import ProblemSpec


def manifest_digest(spec: ProblemSpec) -> str:
    body = {k: v for k, v in asdict(spec).items() if k != "answer"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def runner_commit() -> str:
    p = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True)
    if p.returncode != 0:
        return "unknown"
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True
    ).stdout.strip()
    return p.stdout.strip() + ("-dirty" if dirty else "")


def run_meta(spec: ProblemSpec) -> dict[str, Any]:
    return {"runner_commit": runner_commit(), "manifest": manifest_digest(spec)}


def collect_records(runs: Path, into: Path) -> list[dict[str, Any]]:
    """runs/ 下每个含 record.json 的运行目录 → into/<目录名>.json（{"record": …, "meta": …}），再写 summary.md。"""
    into.mkdir(parents=True, exist_ok=True)
    rows = []
    for rec_path in sorted(runs.glob("*/record.json")):
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        Record(**rec)  # 字段不对就在这里失败，不收进仓库
        meta_path = rec_path.with_name("meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        out = {"record": rec, "meta": meta}
        (into / f"{rec_path.parent.name}.json").write_text(
            json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        rows.append(out)
    (into / "summary.md").write_text(summary(rows), encoding="utf-8")
    return rows


def summary(rows: list[dict[str, Any]]) -> str:
    """按（题目，模式）汇总：解出数 / 次数、平均耗时与成本。只做描述统计，不下结论。"""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["record"]["problem"], r["record"]["mode"]), []).append(r)
    lines = [
        "| 题目 | 模式 | 解出 | 平均耗时（秒） | 平均成本（美元） | 沙箱 | 运行器提交 | 清单摘要 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for (problem, mode), rs in sorted(groups.items()):
        n = len(rs)
        solved = sum(1 for r in rs if r["record"]["terminal"] == "solved")
        dur = sum(r["record"]["duration_s"] for r in rs) / n
        cost = sum(r["record"]["cost_usd"] for r in rs) / n
        metas = {(str(r["meta"].get("runner_commit")), str(r["meta"].get("manifest"))) for r in rs}
        boxed = {bool(r["meta"].get("sandbox")) for r in rs}
        commit = ", ".join(sorted({m[0] for m in metas}))
        manifest = ", ".join(sorted({m[1] for m in metas}))
        lines.append(
            f"| {problem} | {mode} | {solved}/{n} | {dur:.1f} | {cost:.4f} | "
            f"{'是' if boxed == {True} else '否' if boxed == {False} else '混合'} | {commit} | {manifest} |"
        )
    return "\n".join(lines) + "\n"
