"""给前端假后端生成方案分析的样例（web/mock/analyses.json）：用引擎最小版本在验收夹具上真跑，再经 analysis_hub 读出来。

    uv run python scripts/analysis_mock.py

五次运行，每种停法一次：丁（代码形态，三个候选、GPL、来源含疑似指令）停在第 1 次确认；甲走到第 2 次确认；
丙走到第 3 次确认；乙三次确认都过、交接完成；丁的预评估一口气走完。
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
# （夹具，走到第几次确认之后停；4 = 交接完成，0 = 预评估，时间戳）
RUNS = [
    ("delta", 1, "2026-11-21T10:38:00Z"),
    ("alpha", 2, "2026-11-21T09:47:00Z"),
    ("gamma", 3, "2026-11-21T09:12:00Z"),
    ("beta", 4, "2026-11-21T08:31:00Z"),
    ("delta", 0, "2026-11-20T17:05:00Z"),
]


def _run(root: Path, fx: str, upto: int) -> str:
    suffix, mode = (".dry", "dry_run") if upto == 0 else ("", "formal")
    name = f"p_fixture_{fx}_code{suffix}"
    eng = cases.engine(fx, "code", root / name, Recorded.load(cases.recording(fx, "code", suffix)), suffix)
    eng.start(cases.intake(fx, "code", mode))
    if upto >= 2:
        eng.follow_up(cases.g1_block(eng.get("candidates.json")))
    ids = list(eng.x.get("picked", []))
    if upto >= 3:
        eng.follow_up(cases.g2_block(ids))
    if upto >= 4:
        eng.follow_up(cases.g3_block(ids, fx))
    return name


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "analyses"
        at = {_run(root, fx, upto): ts for fx, upto, ts in RUNS}
        hub = AnalysisHub(root, Path(tmp) / "decisions", default_bang(ROOT))
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
