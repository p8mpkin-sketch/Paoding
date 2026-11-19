"""pd kaiti：一句话开题（设计 docs/design/kaiti；迁移表第一期：只有确认道）。

    pd kaiti "<原文>" [--answer <答案> | --answer-file f] [--file 原文文件] [--draft-file 草案.json]
                     [--profile 档案名] [--settings 设置.json] [--priors 先验表.yaml] [--yes]

- 原文 → 前置抽取（答案剪出）→ 起草（模型只指认区间）→ 校验 vet → 确认卡 → 人回车 → 开题批次。
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
    parse_draft,
    placeholder_priors,
    render_card,
    vet,
    write_answer,
)


def add_parser(sp: Any) -> None:
    k = sp.add_parser("kaiti", help="一句话开题（确认道）")
    k.add_argument("text", nargs="?", help="原文；不给则读 --file 或标准输入")
    k.add_argument("--file")
    k.add_argument("--answer")
    k.add_argument("--answer-file")
    k.add_argument("--draft-file")
    k.add_argument("--profile")
    k.add_argument("--settings")
    k.add_argument("--priors")
    k.add_argument("--yes", action="store_true")


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
            d = draft(ext, has_answer, model, name)
    except (DraftError, ValueError, OSError) as e:
        err = str(e)
    v = vet(ext, answer, d, intake, settings, priors, zero_confirm=False, nonce=str(time.time_ns()), draft_error=err)
    w(render_card(v))
    if v.lane == "refuse":
        return 3
    if not a.yes and read("按回车开题，输入 n 放弃：").strip().lower() in ("n", "no", "否"):
        w("[人] 已放弃，没有开题\n")
        return 1
    ref = write_answer(Path(a.home) / "vault", v.secret) if v.secret is not None else None
    ops = batch(v, local.blobs.put, ref)
    out = local.submit(v.pid, f"pd-kaiti:{v.pid}", ops)
    if not out["ok"]:
        bad = [r for r in out["results"] if not r.get("ok")]
        w("[证据] 开题被拒：" + "；".join(f"{r.get('code')}：{r.get('detail', '')}" for r in bad) + "\n")
        return 1
    w(f"[证据] 已开题 {v.pid}（确认道）\n")
    return 0
