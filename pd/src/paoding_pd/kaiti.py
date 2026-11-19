"""pd kaiti：一句话开题（设计 docs/design/kaiti；开放道见 docs/design/open-lane/）。

    pd kaiti "<原文>" [--answer <答案> | --answer-file f] [--file 原文文件] [--draft-file 草案.json]
                     [--profile 档案名] [--settings 设置.json] [--priors 先验表.yaml] [--strict] [--yes]

- 原文 → 前置抽取（答案剪出）→ 起草（模型只指认区间）→ 校验 vet → 确认卡 → 人回车 → 开题批次。
- 没有答案、检查命令（或命令只作自检项）、已登记平台的题进开放道：不出确认卡，直接开题（开题零出站时）。
  --strict 选严格判定：判不了就不开。设置里 lanes.open=false 时同样回到判据先行。
- 起草模型经端点代理：地址 PD_DRAFT_URL，"开题"账户的任务令牌 PD_DRAFT_TOKEN（不是模型密钥，不写进任何文件）；
  模型名取设置层的起草档案（--profile 或 models.routes.draft），没有档案时取 PD_DRAFT_MODEL。
  --draft-file 直接给一份草案（离线读数、无模型时用），同样要过 vet。
- 一期零确认开关不放行（cz 2026-11-19）：练习道候选也要人确认。答案写进本机保密库（<home>/vault），批次里只有 VaultRef。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from paoding_qicao.contract import (
    DraftError,
    Intake,
    MessagesClient,
    ModelPort,
    Settings,
    TablePriors,
    batch,
    draft,
    installed_catalog,
    override,
    parse_draft,
    placeholder_priors,
    render_card,
    vet,
    write_answer,
)


def add_parser(sp: Any) -> None:
    k = sp.add_parser("kaiti", help="一句话开题：判不了的进开放道直接开始，有答案或选了 --strict 的走严格道")
    k.add_argument("text", nargs="?", help="原文；不给则读 --file 或标准输入")
    k.add_argument("--file")
    k.add_argument("--answer")
    k.add_argument("--answer-file")
    k.add_argument("--draft-file")
    k.add_argument("--profile")
    k.add_argument("--settings")
    k.add_argument("--priors")
    k.add_argument("--yes", action="store_true")
    k.add_argument("--strict", action="store_true", help="严格判定：没有答案、检查命令或已登记平台就不开题")
    k.add_argument(
        "--yes-command",
        action="store_true",
        help="命令判据有外发的形状时，确认这条命令只检查、不提交（记进出处账，来源记人）",
    )


def _doc(path: str | None) -> Any:
    if not path:
        return {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def cmd_kaiti(local: Any, a: Any, w: Any, read: Any, model: ModelPort | None = None) -> int:
    raw = a.text if a.text is not None else (Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read())
    answer = a.answer
    if a.answer_file:
        answer = Path(a.answer_file).read_text(encoding="utf-8")
    intake = Intake.load()
    settings = Settings.from_doc(_doc(a.settings))
    priors = TablePriors.load(a.priors) if a.priors else placeholder_priors()
    ext = intake.extract(raw)
    catalog = installed_catalog()  # 判据形态目录：注册表与连接器档案驱动（external-verdict §5.8）
    has_answer = bool((answer or "").strip()) or bool(ext.answers)

    d, err = None, ""
    try:
        if a.draft_file:
            d = parse_draft(json.loads(Path(a.draft_file).read_text(encoding="utf-8")), ext, "draft-file")
        else:
            prof = settings.draft_profile(a.profile)
            name = str(prof["name"]) if prof else ""
            if model is None:
                url, token = os.environ.get("PD_DRAFT_URL", ""), os.environ.get("PD_DRAFT_TOKEN", "")
                mname = str(prof["model"]) if prof else os.environ.get("PD_DRAFT_MODEL", "")
                if not (url and token and mname):
                    w("[人] 没有起草模型：设 PD_DRAFT_URL、PD_DRAFT_TOKEN 与起草档案（或 PD_DRAFT_MODEL）")
                    w("，或用 --draft-file\n")
                    return 2
                model = MessagesClient(url, token, mname)
            d = draft(ext, has_answer, model, name, kinds=catalog.kinds())
    except (DraftError, ValueError, OSError) as e:
        err = str(e)
    v = vet(
        ext,
        answer,
        d,
        intake,
        settings,
        priors,
        zero_confirm=False,
        nonce=str(time.time_ns()),
        draft_error=err,
        catalog=catalog,
        strict=bool(getattr(a, "strict", False)),
    )
    if v.needs_ack == "command" and getattr(a, "yes_command", False):
        v = override(v, {"ack_command": True}, settings)
    w(render_card(v))
    if v.lane == "refuse":
        if settings.lanes_open and any(n.code == "no_criterion" for n in v.notes):
            w("[人] 不加 --strict 就按开放道去做：智能体自己找答案，交付时带证据\n")
        w("[人] 还有一条路：判定权在外部平台的任务，先登记这个平台（judgebox/connectors.d），再 pd connector import\n")
        return 3
    if v.external is not None:
        w(
            f"[人] 判定权在平台 {v.external['connector']}：用 pd connector import {v.external['connector']} "
            f"{v.external['task']} 领题开题（要运行中的全栈：平台凭据在它的钥匙环里）\n"
        )
        return 3
    if v.needs_ack == "command":
        w("[人] 这条命令有外发的形状：确认它只检查、不提交，再加 --yes-command 重跑\n")
        return 3
    # 开放道不出确认卡（open-lane §3.1 第 3 点）：开题零出站，花费有硬顶，直接开始
    if v.lane != "open" and not a.yes and read("按回车开题，输入 n 放弃：").strip().lower() in ("n", "no", "否"):
        w("[人] 已放弃，没有开题\n")
        return 1
    ref = write_answer(Path(a.home) / "vault", v.secret) if v.secret is not None else None
    ops = batch(v, local.blobs.put, ref)
    out = local.submit(v.pid, f"pd-kaiti:{v.pid}", ops)
    if not out["ok"]:
        bad = [r for r in out["results"] if not r.get("ok")]
        w("[证据] 开题被拒：" + "；".join(f"{r.get('code')}：{r.get('detail', '')}" for r in bad) + "\n")
        return 1
    if v.lane == "open":
        w(f"[证据] 已开题 {v.pid}（开放道）：pd status {v.pid} 看进展与交付，pd close {v.pid} 关题\n")
    else:
        w(f"[证据] 已开题 {v.pid}（确认道）\n")
    return 0
