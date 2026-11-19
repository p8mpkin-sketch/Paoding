"""离线读数（设计 §10 第 3 条）：零确认放行的依据。用例由测试方提供，不入库。

    python -m paoding_qicao.offline cases.yaml [--settings s.json] [--priors p.yaml]
    （起草模型同 pd kaiti：PD_DRAFT_URL、PD_DRAFT_TOKEN、PD_DRAFT_MODEL）

用例格式（YAML 列表）：
    - text: 原文
      answer: 答案（可选）
      expect: {eligible: true, scope: ["q1:8080"], judge: exact_match}
      draft: {...}   # 可选：直接给草案，不调模型

读数：
- authority_exact：scope 的地址集合与 Goal 判官都与 expect 相同的比例；
- practice_precision：被判为练习道候选的用例里，expect.eligible 为真且权威字段全对的比例。
  放行门槛是 1.0（cz 2026-11-19 裁决 #83 第 2 条附条件）；没有任何候选时为 None。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .draft import Draft, DraftError, MessagesClient, draft, parse_draft
from .extract import Extraction
from .policy import Intake, PriorSource, Settings, TablePriors, placeholder_priors
from .vet import Vetted, vet

Drafter = Callable[[Extraction, bool], Draft]


def _authority(v: Vetted) -> tuple[frozenset[str], str]:
    if v.input is None:
        return frozenset(), ""
    pats = frozenset(r["pattern"] for r in v.input["scope"] if r["resource"] != "workspace")
    return pats, str(v.input["goal"]["check"]["judge_id"])


def score(
    cases: list[dict[str, Any]], drafter: Drafter | None, intake: Intake, settings: Settings, priors: PriorSource
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for i, c in enumerate(cases):
        ext = intake.extract(str(c["text"]))
        answer = c.get("answer")
        d, err = None, ""
        try:
            if "draft" in c:
                d = parse_draft(c["draft"], ext, "case")
            elif drafter is not None:
                d = drafter(ext, bool(answer) or bool(ext.answers))
            else:
                err = "没有草案也没有起草模型"
        except DraftError as e:
            err = str(e)
        v = vet(ext, answer, d, intake, settings, priors, zero_confirm=False, draft_error=err)
        exp = c.get("expect", {})
        pats, judge = _authority(v)
        exact = pats == frozenset(exp.get("scope", [])) and judge == exp.get("judge", "")
        rows.append(
            {
                "case": i,
                "lane": v.lane,
                "eligible": v.eligible,
                "exact": exact,
                "expect_eligible": bool(exp.get("eligible")),
            }
        )
    n = len(rows)
    cands = [r for r in rows if r["eligible"]]
    hits = sum(bool(r["exact"] and r["expect_eligible"]) for r in cands)
    return {
        "n": n,
        "authority_exact": (sum(bool(r["exact"]) for r in rows) / n) if n else None,
        "practice_candidates": len(cands),
        "practice_precision": hits / len(cands) if cands else None,
        "priors": priors.version(),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paoding_qicao.offline")
    ap.add_argument("cases")
    ap.add_argument("--settings")
    ap.add_argument("--priors")
    a = ap.parse_args(argv)
    intake = Intake.load()
    settings = Settings.from_doc(yaml.safe_load(Path(a.settings).read_text(encoding="utf-8")) if a.settings else {})
    priors = TablePriors.load(a.priors) if a.priors else placeholder_priors()
    url, token, model = (os.environ.get(k, "") for k in ("PD_DRAFT_URL", "PD_DRAFT_TOKEN", "PD_DRAFT_MODEL"))
    drafter: Drafter | None = None
    if url and token and model:
        client = MessagesClient(url, token, model)

        def drafter(e: Extraction, has: bool) -> Draft:
            return draft(e, has, client, model)

    cases = yaml.safe_load(Path(a.cases).read_text(encoding="utf-8")) or []
    out = score(cases, drafter, intake, settings, priors)
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
