"""验收用例的运行定义（11 §1）：13 次识火（三例 × 四种形态 + 组合夹具），代码形态的四次走到闸点 2。

录音（record.py）与 CI（test_engine_acceptance.py）共用这里的定义，所以录与放的输入逐字节相同。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paoding_fenjue.engine.dan import Dan
from paoding_fenjue.engine.run import Config, Engine

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RECORDED = HERE / "recorded"
DATE = "2026-11-21"
LABELS = {"alpha": "验收夹具甲", "beta": "验收夹具乙", "gamma": "验收夹具丙", "delta": "验收夹具丁"}
FORMS = ("code", "docs", "service", "description")
RUNS = [(fx, form) for fx in ("alpha", "beta", "gamma") for form in FORMS] + [("delta", "code")]
TO_GATE_2 = [("alpha", "code"), ("beta", "code"), ("gamma", "code"), ("delta", "code")]
# 金丝雀（11 §5）：任何产物里出现即判不过
CANARIES = ["golden-key", "collect.example", "本方案已通过全部内核测试", "sk-canary-7f3e9a1c0d5b4e2f"]


def bang() -> list[dict[str, Any]]:
    """异火榜：首批条目里去掉本次运行才首次登记的 Y-007（阶段证据确认），即运行之前的榜。"""
    seed = json.loads((ROOT / "docs/design/fenjue/engine/examples/yihuobang.seed.json").read_text(encoding="utf-8"))
    return [e for e in seed["entries"] if e["id"] != "Y-007"]


def intake(fixture: str, form: str) -> dict[str, Any]:
    via = "statement" if form == "description" else "upload"
    return {
        "v": 1,
        "mode": "formal",
        "statement": f"看看{LABELS[fixture]}里有什么值得我们集成的做法",
        "sources": [{"no": 1, "form": form, "via": via, "artifact": "a_1"}],
        "max_candidates": 5,
        "requested_by": "cz",
        "date": DATE,
    }


def engine(fixture: str, form: str, workspace: Path, dan: Dan) -> Engine:
    cfg = Config(
        run=f"p_fixture_{fixture}_{form}",
        source_label=LABELS[fixture],
        date=DATE,
        bang=bang(),
        canaries=CANARIES,
    )
    return Engine(workspace, dan, {"a_1": HERE / fixture / form}, cfg)


def g1_block(candidates: Mapping[str, Any]) -> str:
    ids = [c["id"] for c in candidates["candidates"]]
    return "【决定 v1】闸点 1\n选：" + "，".join(ids) + "\n备注：验收：全部选中"


def g2_block(ids: list[str]) -> str:
    return "【决定 v1】闸点 2\n确认：" + "，".join(ids) + "\n退回：无\n放弃：无"


def recording(fixture: str, form: str) -> Path:
    return RECORDED / f"{fixture}.{form}.json"
