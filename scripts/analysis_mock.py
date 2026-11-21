"""给前端假后端生成方案分析的样例（web/mock/analyses.json）：用引擎最小版本在验收夹具上真跑，再经 analysis_hub 读出来。

    uv run python scripts/analysis_mock.py

三次运行：丁（代码形态，三个候选、GPL、来源含疑似指令）与乙停在第 1 次确认；甲选完候选、走到第 2 次确认。
模型输出是仓库里录好的回放，所以每次生成的内容逐字节相同（时间戳除外，这里统一改成固定值）。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "fenjue" / "tests" / "engine_fixtures"))

import cases  # noqa: E402
from analysis_hub import AnalysisHub, default_bang  # noqa: E402

from paoding_fenjue.engine.dan import Recorded  # noqa: E402

OUT = ROOT / "web" / "mock" / "analyses.json"
RUNS = [("delta", 1, "2026-11-21T10:38:00Z"), ("beta", 1, "2026-11-21T09:12:00Z"), ("alpha", 2, "2026-11-21T08:47:00Z")]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "analyses"
        for fx, gate, _ in RUNS:
            eng = cases.engine(fx, "code", root / f"p_fixture_{fx}_code", Recorded.load(cases.recording(fx, "code")))
            eng.start(cases.intake(fx, "code"))
            if gate == 2:
                eng.follow_up(cases.g1_block(eng.get("candidates.json")))
        hub = AnalysisHub(root, Path(tmp) / "decisions", default_bang(ROOT))
        at = {f"p_fixture_{fx}_code": ts for fx, _, ts in RUNS}
        listing = hub._list({}, None)
        for it in listing["items"]:
            it["updated_at"] = at[it["run"]]
        listing["items"].sort(key=lambda x: x["updated_at"], reverse=True)
        details, artifacts = {}, {}
        for it in listing["items"]:
            run = it["run"]
            d = hub._detail({"run": run}, None)
            d["updated_at"] = at[run]
            details[run] = d
            artifacts[run] = {
                a["sha256"]: hub._artifact({"run": run, "sha": a["sha256"]}, None)["content"] for a in d["artifacts"]
            }
        doc = {"list": listing, "details": details, "artifacts": artifacts, "bang": hub._bang({}, None)}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"写了 {OUT.relative_to(ROOT)}：{len(details)} 次分析")


if __name__ == "__main__":
    main()
