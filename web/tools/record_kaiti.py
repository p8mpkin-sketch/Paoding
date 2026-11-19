"""录一句话开题的应答（qicao 的起草服务，演示起草）：mock/kaiti.json。前端的假服务与测试吃它，
这样前端不必再写一份抽取与校验规则（禁令一的精神）。改了 qicao 之后重录：

    uv run python web/tools/record_kaiti.py
"""

from __future__ import annotations

import json
import dataclasses
from pathlib import Path

from paoding_qicao.contract import Intake, KaitiService, Settings, heuristic_drafter, placeholder_priors

OUT = Path(__file__).resolve().parents[1] / "mock" / "kaiti.json"
SETTINGS = Settings.from_doc(
    {"settings": {"risk": [{"resource": "net", "pattern": "q*:*", "actions": ["connect"], "risk": "r0"}]}}
)
# 运行时扩权开着（新装缺省，runtime-grants §3.1）：开题零出站，原文地址只作展示
SETTINGS_ON = dataclasses.replace(SETTINGS, grants_runtime=True)
ZERO = "目标在 q2:8080，登录后页面会显示一个答案串，把它交出来。半小时内搞定。答案：PD-3R8W1ZNA"
CASES = {
    "practice": (
        "练习题：目标在 q1:8080，是个登录页，登录后页面会显示一个答案串，把它交出来。半小时内搞定。答案：PD-7Q2M9XKD"
    ),
    "command": "仓库在 git.lab:8443，修好构建失败。完成标准：在仓库根目录跑 `make test` 全部通过。预算 $5。",
    "refuse": "帮我调研一下主流的智能体框架，写一份对比。",
}


def main() -> None:
    svc = KaitiService(Intake.load(), lambda: SETTINGS, placeholder_priors(), heuristic_drafter, "heuristic")
    out: dict[str, object] = {"extract": {}, "drafts": {}, "overrides": []}
    for name, text in CASES.items():
        out["extract"][name] = {"text": text, "out": svc.extract_view({"text": text})}  # type: ignore[index]
        d = svc.draft_view({"text": text, "nonce": f"fixture-{name}"})
        out["drafts"][name] = {"text": text, "out": d}  # type: ignore[index]
    on = KaitiService(Intake.load(), lambda: SETTINGS_ON, placeholder_priors(), heuristic_drafter, "heuristic")
    out["extract"]["zero"] = {"text": ZERO, "out": on.extract_view({"text": ZERO})}  # type: ignore[index]
    out["drafts"]["zero"] = {"text": ZERO, "out": on.draft_view({"text": ZERO, "nonce": "fixture-zero"})}  # type: ignore[index]
    first = out["drafts"]["command"]["out"]  # type: ignore[index]
    base = {"text": CASES["command"], "draft": first["draft"], "nonce": first["nonce"], "model": first["model"]}
    for ov in ({"risk": {"0": "r1"}}, {"risk": {"0": "r1"}, "usd_milli": 3000}):
        rec = {"name": "command", "overrides": ov, "out": svc.draft_view({**base, "overrides": ov})}
        out["overrides"].append(rec)  # type: ignore[attr-defined]
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
