"""评测读数（规格 §8，审计 P0-1）。一条配置一次运行一条记录；记录是量具的产物，只读不驱动行为。

记录的字段固定（真实测试方据此对账）：

    mode        运行模式：baseline（单 CLI 直连）| full（全栈流程）
    problem     题目 id
    run         同一配置的第几次（从 1 起）
    model       模型名（价目表里的那个名字）
    duration_s  墙钟秒数
    terminal    终态：solved | unsolved | failed
    cost_usd    这次运行经端点代理计量的花费（美元）；红线 5：两种模式同仓同代理同计量
    events      full 取本题事件数；baseline 取 CLI 的回合数（没有事件日志，回合数是对应的读数）
    log_dir     这次运行的产物目录：runs/<时间戳>-<模式>-<题目>-<次>/

产物目录里有 record.json（本记录），加上各模式自己的原始输出（full 是全栈日志与事件转储，
baseline 是 CLI 的 stream-json 与工作区）。期望答案与密钥从不写进记录。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODES = ("baseline", "full", "bk", "bn")  # bk、bn：瘦基线的等成本重试与共享笔记两臂（arms.py）
TERMINALS = ("solved", "unsolved", "failed")


def stamp() -> str:
    """产物目录名里的时间戳：UTC，形如 20261118T104542Z（文件名安全，按字典序即按时间序）。"""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class Record:
    mode: str
    problem: str
    run: int
    model: str
    duration_s: float
    terminal: str
    cost_usd: float
    events: int
    log_dir: str

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode 取 {MODES} 之一，不是 {self.mode!r}")
        if self.terminal not in TERMINALS:
            raise ValueError(f"terminal 取 {TERMINALS} 之一，不是 {self.terminal!r}")

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_s"] = round(self.duration_s, 2)
        d["cost_usd"] = round(self.cost_usd, 6)
        return d

    def write(self, run_dir: Path) -> Path:
        """把记录写进 <run_dir>/record.json，返回该文件路径。"""
        run_dir.mkdir(parents=True, exist_ok=True)
        out = run_dir / "record.json"
        out.write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return out


def run_dirname(mode: str, problem: str, run: int, ts: str) -> str:
    """产物目录名：<时间戳>-<模式>-<题目>-<次>。"""
    return f"{ts}-{mode}-{problem}-{run}"


def log_dir_field(out_root: Path, name: str) -> str:
    """记录里的 log_dir：<产物根目录名>/<目录名>/。产物根缺省就是 runs/，于是形如 runs/<…>/。"""
    return f"{out_root.name}/{name}/"
