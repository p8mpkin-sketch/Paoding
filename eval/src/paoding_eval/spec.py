"""题目规格：评测台怎么开一道题、怎么判对（规格 §8）。

一道题由一份清单（YAML）描述，字段与开题操作一一对应：

    id          题目 id
    title       标题
    statement   题面（Origin 文本，交给模型看）
    answer      期望答案；只用来生成 exact_match 的 sha256 判据，不写进题目镜像也不进产物目录
    scope       授权范围（§3.6.2 的 scope；net 规则的 pattern 是 host:port）
    budget      预算：usd_milli、wall_s、verify_share、bootstrap_share
    env         执行环境：base、baseline_ref
    judges      本题启用的判官 id 列表（M0 只有 exact_match 与 replay）
    prompt      baseline 模式交给 CLI 的用户提示（缺省用 statement）

同一份规格两种模式共用：full 用它开题（图服务里走全栈），baseline 用它生成提示与 exact_match 判据（直连，不入图）。
真实题目的答案由启动题目容器的一方（真实测试方）经清单给出；仓库里不存答案。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


DELIVERY = "交付：取得答案后，把答案原样写进当前工作目录下的 answer.txt（文件里只有答案本身）。"


@dataclass
class ProblemSpec:
    id: str
    title: str
    statement: str
    answer: str
    scope: list[dict] = field(
        default_factory=lambda: [{"resource": "workspace", "pattern": "*", "actions": ["read", "write"], "risk": "r0"}]
    )
    budget: dict = field(
        default_factory=lambda: {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3}
    )
    env: dict = field(default_factory=lambda: {"base": "basic", "baseline_ref": "basic@1"})
    judges: list[str] = field(default_factory=lambda: ["exact_match"])
    prompt: str = ""

    @property
    def goal_prompt(self) -> str:
        """baseline 的用户提示：题面（或清单里给的 prompt），加上交付方式。
        baseline 的判定读工作目录下的 answer.txt，所以交付方式必须写进提示；full 里同一件事由 claim_done 承担。"""
        return (self.prompt or self.statement).rstrip() + "\n\n" + DELIVERY

    def expect(self) -> dict:
        """exact_match 判据：答案的 sha256。答案本身不出现在判据里。"""
        return {"sha256": sha256_hex(self.answer)}

    def open_ops(self) -> list[dict]:
        """开题的两条操作：登记题面 Artifact（input），再开题（Goal 判据为 exact_match）。

        题面 Artifact 用 $0 回指：第 0 条的结果 id 就是它的引用。与 scripts/e2e/drive.py 同形。"""
        statement = self.statement.encode()
        return [
            {
                "op": "register_artifact",
                "body": {
                    "hash": hashlib.sha256(statement).hexdigest(),
                    "size": len(statement),
                    "media_type": "text/plain; charset=utf-8",
                    "class": "input",
                },
            },
            {
                "op": "open_problem",
                "body": {
                    "title": self.title,
                    "origin": {"statement_ref": "$0", "materials": []},
                    "goal": {
                        "statement": self.statement,
                        "check": {"judge_id": "exact_match", "expect": self.expect()},
                        "max_attempts": 3,
                        "accept": "judge",
                    },
                    "scope": self.scope,
                    "budget": self.budget,
                    "env": self.env,
                    "judges": self.judges,
                },
            },
        ]

    def statement_bytes(self) -> bytes:
        return self.statement.encode()


def load(path: str | Path) -> ProblemSpec:
    """从 YAML 清单读一份题目规格。"""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [k for k in ("id", "title", "statement", "answer") if k not in raw]
    if missing:
        raise ValueError(f"{path}：题目清单缺字段 {missing}")
    known = {"id", "title", "statement", "answer", "scope", "budget", "env", "judges", "prompt"}
    extra = set(raw) - known
    if extra:
        raise ValueError(f"{path}：题目清单有未知字段 {sorted(extra)}")
    return ProblemSpec(**raw)


# 干跑用的内建题：算出 6×7 原样提交，与 scripts/e2e/drive.py 的 6×7 题同形同判据。
# baseline 干跑（无 Docker）：假 CLI 把答案写进 answer.txt，本地 exact_match 判定。
# full 干跑（需 Docker）：复用 scripts/e2e 的三份脚本把这道题跑到 solved（与 test-e2e.sh 同一条已验证的路径）。
# 真实题目用 problems.d/ 下的清单。
DRYRUN = ProblemSpec(
    id="dry-compute",
    title="算出 6×7",
    statement="在执行环境里算出 6 乘 7 的结果，把结果原样提交。",
    answer="42",
    judges=["exact_match", "replay"],
)
