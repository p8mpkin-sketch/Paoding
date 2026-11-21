"""进化读数在组装根里的接线（GET /v1/evolution，焚决 04 §7）：只读；题按开题时记下的功法分组、分臂。不需要 Docker。"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "e2e"))

from drive import call, open_problem  # noqa: E402
from stack import Stack, StackConfig  # noqa: E402

from paoding_fenjue.contract import for_problem, gongfa  # noqa: E402


@pytest.fixture
def stack(tmp_path):
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none"))
    url = s.http.serve()
    yield s, url
    s.http.close()


def test_evolution_reads_the_gongfa_dossiers_and_the_tasks(stack):
    s, url = stack
    assert open_problem(url, s.human_token, "p1")["ok"]
    out = call(url, "/v1/evolution")
    live = gongfa()
    assert out["current"]["digest"] == live["digest"] and out["as_of"] == s.graph.state["seq"]
    assert out["history"][-1]["dossier"] == "001" and out["outcomes"]["huolian"] >= 1
    [v] = [v for v in out["versions"] if v["digest"] == live["digest"]]
    assert v["tasks"] == 1 and v["open"] == 1 and v["current"]
    [h] = [h for h in out["holdout"] if h["slot"] == "H6"]
    side = "held" if for_problem(s.graph.state["problems"]["p1"]).in_holdout("p1", "H6") else "main"
    assert h[side]["tasks"] == 1 and h["live"]
    with pytest.raises(urllib.error.HTTPError):
        call(url, "/v1/evolution", {"x": 1}, token=s.human_token)  # 只读
