"""录一句话开题的应答（qicao 的起草服务，演示起草）：mock/kaiti.json。前端的假服务与测试吃它，
这样前端不必再写一份抽取与校验规则（禁令一的精神）。改了 qicao 之后重录：

开放道（docs/design/open-lane/）之后，CASES 里的几段按**严格判定**录（strict=true）：它们测的是确认卡与拒绝页，
那两样只在严格道里还有；开放道另录 OPEN 一段（运行时扩权开着，不出确认卡、直接开题）。

    uv run python web/tools/record_kaiti.py
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from paoding_qicao.contract import (
    Catalog,
    Form,
    Intake,
    KaitiService,
    Settings,
    heuristic_drafter,
    placeholder_priors,
)

OUT = Path(__file__).resolve().parents[1] / "mock" / "kaiti.json"
SETTINGS = Settings.from_doc(
    {"settings": {"risk": [{"resource": "net", "pattern": "q*:*", "actions": ["connect"], "risk": "r0"}]}}
)
# 设置页登记了两个模型档案：确认卡上“执行用”另选 light 时写进 prefs.model（宪章 03 §3.1、地图 Q12）
PROFILES = [
    {"name": "default", "endpoint": "", "model": "", "family": "", "tier": "strong", "key_slot": "default"},
    {"name": "light", "endpoint": "", "model": "light-1", "family": "", "tier": "light", "key_slot": "default"},
]
SETTINGS_M = dataclasses.replace(SETTINGS, models={"profiles": PROFILES, "routes": {}})
# 运行时扩权开着（新装缺省，runtime-grants §3.1）：开题零出站，原文地址只作展示
SETTINGS_ON = dataclasses.replace(SETTINGS, grants_runtime=True)
OPEN = "帮我比较三种排序算法在十万个整数上的速度，写一份结论。"  # 没有答案、没有命令：开放道
ZERO = "目标在 q2:8080，登录后页面会显示一个答案串，把它交出来。半小时内搞定。答案：PD-3R8W1ZNA"
CASES = {
    "practice": (
        "练习题：目标在 q1:8080，是个登录页，登录后页面会显示一个答案串，把它交出来。半小时内搞定。答案：PD-7Q2M9XKD"
    ),
    "command": "仓库在 git.lab:8443，修好构建失败。完成标准：在仓库根目录跑 `make test` 全部通过。预算 $5。",
    "refuse": "帮我调研一下主流的智能体框架，写一份对比。",
    # 命令判据有外发的形状（external-verdict §5.8 加重警告）：要人勾选才给批次
    "outbound": "完成标准：跑 `curl -X POST https://q1:8080/check -d ok` 返回 0。",
    # 判定权在已登记的平台（假平台 plat-a）：起草不领题，创建时调导入
    "external": "平台任务 T-17（https://plat-a.test/tasks/T-17）：找出服务里的口令，交给平台，回执通过就算完成。限时 6 小时。",
}
# 假平台的形态目录（真部署由注册表与连接器档案生成，见 qicao/catalog.py）
PLAT = Form("external", "ext_receipt", "plat-a", ("plat-a.test",), r"T-[0-9]+", "1")
CATALOG = Catalog((Form("answer", "exact_match"), Form("command", "replay"), PLAT))
PLATFORMS = [
    {
        "id": "plat-a",
        "version": "1",
        "digest": "c" * 64,
        "judges": ["ext_receipt"],
        "hosts": ["plat-a.test"],
        "deliver": "judge",
        "slot": "plat-a",
        "slot_set": True,
    }
]
TASK = {"task": "T-17", "title": "找出服务里的口令", "time_limit_s": 21600, "max_submissions": 3}
NOTICE = {
    "id": "T-17",
    "statement": "服务里藏着一个口令，找到后交给平台。",
    "instance": "10.9.0.7:31000",
    "time_limit_s": 21600,
}


def main() -> None:
    svc = KaitiService(Intake.load(), lambda: SETTINGS, placeholder_priors(), heuristic_drafter, "heuristic", CATALOG)
    out: dict[str, object] = {"extract": {}, "drafts": {}, "overrides": [], "platforms": PLATFORMS, "tasks": [TASK]}
    for name, text in CASES.items():
        out["extract"][name] = {"text": text, "out": svc.extract_view({"text": text})}  # type: ignore[index]
        d = svc.draft_view({"text": text, "nonce": f"fixture-{name}", "strict": True})
        out["drafts"][name] = {"text": text, "out": d}  # type: ignore[index]
    on = KaitiService(Intake.load(), lambda: SETTINGS_ON, placeholder_priors(), heuristic_drafter, "heuristic", CATALOG)
    out["extract"]["zero"] = {"text": ZERO, "out": on.extract_view({"text": ZERO})}  # type: ignore[index]
    out["drafts"]["zero"] = {"text": ZERO, "out": on.draft_view({"text": ZERO, "nonce": "fixture-zero"})}  # type: ignore[index]
    out["extract"]["open"] = {"text": OPEN, "out": on.extract_view({"text": OPEN})}  # type: ignore[index]
    out["drafts"]["open"] = {"text": OPEN, "out": on.draft_view({"text": OPEN, "nonce": "fixture-open"})}  # type: ignore[index]
    first = out["drafts"]["command"]["out"]  # type: ignore[index]
    base = {"text": CASES["command"], "draft": first["draft"], "nonce": first["nonce"], "model": first["model"], "strict": True}
    for ov in ({"risk": {"0": "r1"}}, {"risk": {"0": "r1"}, "usd_milli": 3000}):
        rec = {"name": "command", "overrides": ov, "out": svc.draft_view({**base, "overrides": ov})}
        out["overrides"].append(rec)  # type: ignore[attr-defined]
    svc_m = KaitiService(Intake.load(), lambda: SETTINGS_M, placeholder_priors(), heuristic_drafter, "heuristic", CATALOG)
    pick = {"model": "light"}
    out["overrides"].append({"name": "command", "overrides": pick, "out": svc_m.draft_view({**base, "overrides": pick})})  # type: ignore[attr-defined]
    ob = out["drafts"]["outbound"]["out"]  # type: ignore[index]
    ack = {"ack_command": True}
    base = {"text": CASES["outbound"], "draft": ob["draft"], "nonce": ob["nonce"], "model": ob["model"], "strict": True}
    out["overrides"].append({"name": "outbound", "overrides": ack, "out": svc.draft_view({**base, "overrides": ack})})  # type: ignore[attr-defined]
    # 拒绝页第 02 条路（人工验收）：第一句原文作一条，人另写一条要附交付物的
    rf = out["drafts"]["refuse"]["out"]  # type: ignore[index]
    sent = next(x["id"] for x in rf["spans"] if x["kind"] == "sentence")
    base = {"text": CASES["refuse"], "draft": rf["draft"], "nonce": rf["nonce"], "model": rf["model"], "strict": True}
    acc = [{"span": sent}, {"text": "附上对比表", "needs": "artifact"}]
    out["acceptance"] = [{"name": "refuse", "acceptance": acc, "out": svc.draft_view({**base, "acceptance": acc})}]
    notice = json.dumps(NOTICE, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    out["imports"] = {  # 领题时刻固定，录下来的批次逐字可比
        "T-17": svc.import_view(
            PLAT, TASK, NOTICE["statement"], notice, now_ms=1_700_000_000_000, nonce="fixture-import"
        )
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
