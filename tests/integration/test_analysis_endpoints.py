"""方案分析界面一期的后端（scripts/analysis_hub.py）：读引擎工作区的端点与第 1 次确认的提交。不需要 Docker。

工作区由引擎最小版本在验收夹具上真跑出来（录好的模型输出回放），所以端点读到的就是引擎真实写下的文件；
提交的决定块再交给同一个引擎续做，证明界面生成、端点收下的原文引擎读得懂。
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "e2e"))
sys.path.insert(0, str(ROOT / "fenjue" / "tests" / "engine_fixtures"))

import cases  # noqa: E402
from drive import call  # noqa: E402
from stack import Stack, StackConfig  # noqa: E402

from paoding_fenjue.engine.dan import Recorded  # noqa: E402

RUN = "p_fixture_alpha_code"


def _engine(ws_root: Path, fx: str = "alpha"):
    return cases.engine(fx, "code", ws_root / f"p_fixture_{fx}_code", Recorded.load(cases.recording(fx, "code")))


@pytest.fixture
def stack(tmp_path):
    root = tmp_path / "analyses"
    for fx in ("alpha", "beta"):
        _engine(root, fx).start(cases.intake(fx, "code"))
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none", analyses_dir=root))
    url = s.http.serve()
    yield s, url, root
    s.http.close()


def _err(url: str, path: str, body=None, token=None) -> tuple[int, dict]:
    with pytest.raises(urllib.error.HTTPError) as e:
        call(url, path, body, token=token)
    return e.value.code, json.loads(e.value.read())


def _block(doc: dict, **over) -> str:
    lines = ["【决定 v1】闸点 1", "选：" + "，".join(c["id"] for c in doc["candidates"])]
    return "\n".join([*lines, *over.get("extra", []), "备注：界面一期测试"])


def test_list_and_detail_read_the_engine_workspace(stack):
    s, url, root = stack
    out = call(url, "/v1/analyses")
    runs = {i["run"]: i for i in out["items"]}
    assert set(runs) == {"p_fixture_alpha_code", "p_fixture_beta_code"}
    a = runs[RUN]
    assert (
        a["step"] == "G1"
        and a["mode"] == "formal"
        and a["waiting"] == {"gate": "G1", "deliver_seq": 1, "submitted": False}
    )
    assert a["candidates"] == 1 and a["license"]["spdx"] == "Apache-2.0" and a["spent_usd_milli"] > 0
    assert out["stage_share"] == {"S3": 0.45, "S4": 0.35, "S5": 0.20}

    d = call(url, f"/v1/analyses/{RUN}")
    state = json.loads((root / RUN / "run.json").read_text(encoding="utf-8"))
    assert d["units"] == state["units"] and d["spent"] == state["spent"] and d["gates"] == state["gates"]
    assert d["candidates_doc"]["candidates"][0]["id"] == "C1"
    assert d["needs"] == ["请在下列候选中挑选（闸点 1）"]
    [rep] = d["reports"]
    assert rep["gate"] == "G1" and rep["text"].startswith("# 方案分析：候选做法")
    assert d["observations"] and all(o["id"].startswith("o") for o in d["observations"])
    kinds = {a["name"]: a["kind"] for a in d["artifacts"]}
    assert kinds["snapshot:s1"] == "material" and kinds["read:H1"] == "exec" and kinds["candidates.json"] == "analysis"
    sha = state["artifacts"]["candidates.json"]
    art = call(url, f"/v1/analyses/{RUN}/artifacts/{sha}")
    assert art["name"] == "candidates.json" and art["content"] == d["candidates_doc"]


def test_reads_refuse_what_is_not_there(stack):
    s, url, _ = stack
    assert _err(url, "/v1/analyses/nope")[0] == 404
    assert _err(url, f"/v1/analyses/{RUN}/artifacts/{'0' * 64}")[0] == 404
    assert _err(url, f"/v1/analyses/{RUN}/artifacts/..%2Frun.json")[0] == 404  # 只认 64 位十六进制


def test_bang_is_read_only(stack):
    s, url, _ = stack
    out = call(url, "/v1/fenjue/bang")
    ids = [e["id"] for e in out["entries"]]
    assert "Y-001" in ids and out["source"].endswith(".json")
    assert _err(url, "/v1/fenjue/bang", {"x": 1}, s.human_token)[0] in (404, 405)


def test_gate_1_decision_is_checked_then_handed_to_the_engine(stack):
    s, url, root = stack
    d = call(url, f"/v1/analyses/{RUN}")
    doc = d["candidates_doc"]
    path = f"/v1/analyses/{RUN}/decision"
    good = {"block": _block(doc), "deliver_seq": 1}

    assert _err(url, path, good, s.tok["sinan"])[0] == 403  # 只认人的令牌
    bad = [
        ({"block": "随便写写", "deliver_seq": 1}, "no_block"),
        ({"block": _block(doc, extra=["选个好的"]), "deliver_seq": 1}, "unparsed"),
        ({"block": _block(doc, extra=["排除：C1"]), "deliver_seq": 1}, "unparsed"),  # 排除没写理由
        ({"block": "【决定 v1】闸点 1\n选：C9", "deliver_seq": 1}, "unknown_candidate"),
        ({"block": "【决定 v1】闸点 1\n选：无", "deliver_seq": 1}, "nothing_picked"),
        ({"block": _block(doc, extra=["排除：C1（重复）"]), "deliver_seq": 1}, "pick_and_exclude"),
        ({"block": _block(doc, extra=["改：C1.risk = R0"]), "deliver_seq": 1}, "bad_edit"),
        ({"block": "【决定 v1】闸点 2\n确认：C1", "deliver_seq": 1}, "wrong_gate"),
        ({**good, "budget_add_usd_milli": -1}, "schema_error"),
    ]
    for body, code in bad:
        status, e = _err(url, path, body, s.human_token)
        assert (status, e["code"]) in ((400, code),), (body, e)
    status, e = _err(url, path, {**good, "deliver_seq": 7}, s.human_token)
    assert (status, e["code"]) == (409, "stale_view")

    block = _block(doc)
    out = call(url, path, {"block": block, "deliver_seq": 1, "budget_add_usd_milli": 500}, s.human_token)
    row = out["submitted"]
    assert row["block"] == block and row["decision"]["pick"] == ["C1"] and row["budget_add_usd_milli"] == 500
    d = call(url, f"/v1/analyses/{RUN}")
    assert d["waiting"]["submitted"] and d["submitted"] == [row]
    status, e = _err(url, path, {"block": block, "deliver_seq": 1}, s.human_token)
    assert (status, e["code"]) == (409, "already_submitted")
    assert json.loads((root / RUN / "run.json").read_text(encoding="utf-8"))["step"] == "G1"  # 端点不改工作区

    # 引擎续做时取走这条：同一份原文，引擎读得懂，走到第 2 次确认
    eng = _engine(root)
    dl = eng.follow_up(row["block"])
    assert dl.gate == "G2"
    d = call(url, f"/v1/analyses/{RUN}")
    assert d["step"] == "G2" and d["submitted"] == [] and d["history"] == [row]
    assert d["essences"][0]["candidate"] == "C1" and [r["gate"] for r in d["reports"]] == ["G1", "G2"]
    assert d["gates"][0]["decision"]["pick"] == ["C1"]
    status, e = _err(url, path, {"block": "【决定 v1】闸点 2\n确认：C1", "deliver_seq": 3}, s.human_token)
    assert (status, e["code"]) == (409, "not_yet")


def test_title_rename_is_accepted(stack):
    s, url, _ = stack
    run = "p_fixture_beta_code"
    doc = call(url, f"/v1/analyses/{run}")["candidates_doc"]
    block = _block(doc, extra=["改：C1.title = 摘要带出处的压缩"])
    row = call(url, f"/v1/analyses/{run}/decision", {"block": block, "deliver_seq": 1}, s.human_token)["submitted"]
    assert row["decision"]["edit"] == [{"pointer": "C1.title", "value": "摘要带出处的压缩"}] and not row["forwarded"]


def test_ui_block_is_what_the_engine_renders():
    """界面 g1Block（web/src/model/analysis.ts）与引擎 decision.render 逐字节相同。

    web/tests/analysis.test.tsx 钉了同一段。"""
    from paoding_fenjue.engine import decision

    ui = "【决定 v1】闸点 1\n选：C1，C2\n排除：C3（已在待办里）\n改：C2.title = 分阶段验收\n备注：先看压缩"
    assert decision.render(decision.parse(ui)) == ui
