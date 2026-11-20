"""零差迁移的常驻回归（焚决 F2，06 §3.3）：提示词、工具形状与司南次序与 F2 之前录下的逐字节相同。
整套剧本的核对较慢，手动跑 `uv run python tests/fenjue/zero_diff.py --check`。"""

import json
from pathlib import Path

from zero_diff import digest, surface

FROZEN = json.loads((Path(__file__).with_name("zerodiff.json")).read_text(encoding="utf-8"))


def test_surface_is_byte_for_byte_what_it_was_before_f2():
    assert digest(surface()) == FROZEN["@surface"]["packages"]


def test_the_frozen_record_covers_sessions_of_both_lanes():
    pkgs = {k.split("::")[0] for k, v in FROZEN.items() if v["n_packages"]}
    assert {"adapter/tests/test_session.py", "adapter/tests/test_solve.py"} <= pkgs
    assert sum(v["n_events"] for v in FROZEN.values()) > 1000
