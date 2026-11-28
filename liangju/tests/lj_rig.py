"""测试用的假模型与搭批次的小工具。假模型按提示词认出是哪一段，回答由测试给的三个函数定。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # 量具不是安装的包：从仓库根导入
    sys.path.insert(0, str(ROOT))

from liangju import mangpan, tici  # noqa: E402
from liangju.common import write_json  # noqa: E402
from liangju.model import ToolCall, Turn  # noqa: E402


def parts(user: str) -> dict[str, str]:
    out, key = {}, None
    for line in user.splitlines():
        m = re.fullmatch(r"【(.+)】", line)
        if m:
            key = m.group(1)
            out[key] = ""
        elif key is not None:
            out[key] += line + "\n"
    return {k: v.strip("\n") for k, v in out.items()}


class Fake:
    def __init__(self, tidy, read, check, lookups: int = 0) -> None:
        self.fn = {"zhengli": tidy, "pandu": read, "hedui": check}
        self.lookups = lookups  # 核对时先调几次工具
        self.seen: list[tuple[str, str]] = []
        self.tools_seen: list[str] = []

    def chat(self, system, messages, tools=None):
        stage = next(k for k, v in mangpan.prompts().items() if v == system)
        user = messages[0]["text"]
        if stage == "hedui":
            done = sum(1 for m in messages if m["role"] == "assistant")
            self.tools_seen += [m["text"] for m in messages[-1:] if m["role"] == "tool"]
            if done < self.lookups:
                call = ToolCall(f"c{done}", "search", {"pattern": "MAX_BATCH"})
                return Turn("", [call], {"input": 5, "cached_input": 0, "output": 1}, "fake-judge")
        if len(messages) == 1:
            self.seen.append((stage, user))
        doc = self.fn[stage](parts(user))
        return Turn(
            json.dumps(doc, ensure_ascii=False), [], {"input": 10, "cached_input": 0, "output": 2}, "fake-judge"
        )


def lines_as_claims(p: dict[str, str]) -> dict[str, Any]:
    """整理：回答的每一行 `n: 文字` 归到子问 n，整行文字是逐字片段。"""
    n = len(p["子问清单"].splitlines())
    rows = [{"n": i, "claims": []} for i in range(1, n + 1)]
    for line in p["回答原文"].splitlines():
        m = re.fullmatch(r"(\d+): (.+)", line)
        if m and int(m.group(1)) <= n:
            rows[int(m.group(1)) - 1]["claims"].append({"quote": m.group(2), "cite": ""})
    return {"subquestions": rows}


def by_marks(p: dict[str, str]) -> dict[str, Any]:
    """判读：子问下面没有结论 → 没答到；有一条带「一半」→ 部分答到；否则答到。"""
    rows = []
    for i, block in enumerate(re.split(r"子问 \d+ 的结论：\n", p["摘出的结论"])[1:], 1):
        v = "missing" if "没有摘出结论" in block else "partial" if "一半" in block else "answered"
        mech = "" if v == "answered" else "问了两件事，只答了 half_done 的前一件"
        rows.append({"n": i, "verdict": v, "premise_false": False, "reason": "r", "mechanism": mech})
    return {"subquestions": rows}


def by_words(p: dict[str, str]) -> dict[str, Any]:
    """核对：片段里有「错」→ 被否定；有「虚」→ 找不到依据；否则成立。"""
    q = p["结论的逐字片段"]
    v = "refuted" if "错" in q else "no_basis" if "虚" in q else "holds"
    mech = "" if v == "holds" else "把缺省值说成了另一个数"
    return {"verdict": v, "path": "" if v == "no_basis" else "relay/config.py", "lines": [3, 3], "mechanism": mech}


def simple() -> Fake:
    return Fake(lines_as_claims, by_marks, by_words)


CANARY = mangpan.HERE / "canary"
ARMS = {
    "B": {
        "role": "benhuo",
        "model": "arm-model",
        "version": "1",
        "endpoint": "代理",
        "metering": "预算账",
        "price_table": "t1",
    },
    "B2": {
        "role": "tonghuo",
        "model": "arm-model",
        "version": "1",
        "endpoint": "代理",
        "metering": "预算账",
        "price_table": "t1",
    },
}
SAMPLES = ("missing-a", "missing-b", "wrong-a", "wrong-b", "premise-a", "premise-b")  # 三份已知答案，两种文风
JUDGE = {"name": "judge-model", "version": "7", "wire": "openai", "url": "http://x", "key_env": "LIANGJU_TEST_KEY"}


QDOC = {  # make_batch 不另给题目时写出的题集文件
    "v": 1,
    "code": "SET-A",
    "questions": [
        {
            "id": f"q{i}",
            "text": f"题面{i} SENTINEL_QUESTION",
            "subquestions": ["子问甲 SENTINEL_SUB", "子问乙"],
            "snapshot": str(CANARY / "snapshot"),
            "axes": {"language": "python", "ask": "怎么做"},
        }
        for i in range(1, 4)
    ],
}


def attempt(arm: str, q: str, rep: int, answer: str | None, **kw: Any) -> tici.Attempt:
    base: dict[str, Any] = {
        "status": "finished" if answer is not None else "other",
        "models_seen": ["arm-model"],
        "usage": {"input": 100, "cached_input": 20, "output": 30, "calls": 4},
        "cost_usd_milli": 50,
        "price_table": "t1",
        "metering": "预算账",
        "elapsed_s": 60.0,
        "cap_usd_milli": 100,
        "gongfa": "g" * 8,
        "own": {"route": "question_led", "timeline_stop": False, "engine_items": [], "on_defs": [1, 2]},
    }
    return tici.Attempt(arm=arm, question=q, rep=rep, answer=answer, **{**base, **kw})


def make_batch(tmp: Path, attempts: list[tici.Attempt], questions: list[dict[str, Any]] | None = None, **batch: Any):
    """搭一个批次目录与题集文件，带一份通过的自检记录。回 (批次目录, 题集文件, 盲判模型的登记文件)。"""
    bdir = tmp / "batch"
    doc = {
        "v": 1,
        "id": "T-1",
        "date": "2026-11-27",
        "purpose": "起点轮",
        "plan_hash": "无",
        "question_set": {"code": "SET-A", "source": "手出"},
        "runs_per_question": 2,
        "parallel": 4,
        "watchdog_s": None,
        "arms": ARMS,
        "unequal": [],
        "yuanxing_gate": "未判：这一批没有跑原形臂",
        "caps": {"per_question_usd_milli": None, "total_usd_milli": None},
        "start": {"commit": "c1", "dirty": False, "config_digest": "d1"},
        "end": {"commit": "c1", "dirty": False, "config_digest": "d1"},
        "converted_to_dev": 0,
        "added_questions": 0,
        "set_judged_times": 0,
        "reused": [],
        "reconciliation": {},
    }
    write_json(bdir / "batch.json", {**doc, **batch})
    for a in attempts:
        tici.save(bdir, a)
    qs = questions or QDOC["questions"]
    qpath = tmp / "questions.json"
    write_json(qpath, {"v": 1, "code": "SET-A", "questions": qs})
    write_json(
        bdir / "selfcheck.json",
        {
            "ok": True,
            "model": "judge-model",
            "version": "7",
            **mangpan.version(),
            "results": {name: {"ok": True, "seconds": 30.0} for name in SAMPLES},
            "seconds_max": 30.0,
        },
    )
    jpath = tmp / "judge.json"
    write_json(jpath, JUDGE)
    return bdir, qpath, jpath
