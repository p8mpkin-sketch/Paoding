"""重录夹具的丹输出：`uv run python fenjue/tests/engine_fixtures/record.py`。

用 script.py 扮演模型，按 cases.py 的定义把 13 次识火（代码形态的四次走到闸点 2）跑一遍，边跑边录，
写进 recorded/<夹具>.<形态>.json。夹具或引擎的丹输入变了，CI 会报“录音过期”，就重录一次并审 diff。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cases  # noqa: E402
from script import Script  # noqa: E402

from paoding_fenjue.engine.dan import Recorder  # noqa: E402


def main() -> int:
    cases.RECORDED.mkdir(exist_ok=True)
    for fx, form in cases.RUNS:
        rec = Recorder(Script(fx, form))
        with tempfile.TemporaryDirectory() as tmp:
            eng = cases.engine(fx, form, Path(tmp), rec)
            d = eng.start(cases.intake(fx, form))
            print(f"{fx}.{form}: {d.gate} {[c['name'] for c in eng.get('candidates.json')['candidates']]}")
            if (fx, form) in cases.TO_GATE_2:
                d = eng.follow_up(cases.g1_block(eng.get("candidates.json")))
                print(f"  {d.gate} passed={d.passed} needs={d.needs}")
                ids = list(eng.x["picked"])
                d = eng.follow_up(cases.g2_block(ids))
                print(f"  -> {eng.state['step']}")
        rec.dump(cases.recording(fx, form))
    print(json.dumps({"recorded": len(cases.RUNS)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
