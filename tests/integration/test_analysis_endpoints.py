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
    assert len(d["needs"]) == 1 and d["needs"][0].startswith("请在下列候选中挑选")  # 括号里的说法归引擎
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


def _to(root: Path, fx: str, upto: int, mode: str = "formal", suffix: str = ""):
    """把一次分析走到第 upto 次确认之后（4 = 交接完成；预评估一口气走完）。"""
    eng = cases.engine(
        fx, "code", root / f"p_fixture_{fx}_code{suffix}", Recorded.load(cases.recording(fx, "code", suffix)), suffix
    )
    eng.start(cases.intake(fx, "code", mode))
    if upto >= 2:
        eng.follow_up(cases.g1_block(eng.get("candidates.json")))
    ids = list(eng.x.get("picked", []))
    if upto >= 3:
        eng.follow_up(cases.g2_block(ids))
    last = eng.follow_up(cases.g3_block(ids, fx)) if upto >= 4 else None
    return eng, last


@pytest.fixture
def later(tmp_path):
    """引擎第二期的三种停法：停在第 3 次确认、交接完成、预评估走完。"""
    root = tmp_path / "analyses"
    out = {
        "g3": _to(root, "gamma", 3),
        "done": _to(root, "delta", 4),
        "dry": _to(root, "delta", 0, "dry_run", ".dry"),
    }
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none", analyses_dir=root))
    url = s.http.serve()
    yield s, url, out
    s.http.close()


def test_gate_3_is_read_only_and_shows_the_placements(later):
    from paoding_fenjue.engine import run as engine_run

    s, url, out = later
    eng, _ = out["g3"]
    run = "p_fixture_gamma_code"
    d = call(url, f"/v1/analyses/{run}")
    assert d["step"] == "G3" and d["waiting"] == {"gate": "G3", "deliver_seq": 5, "submitted": False}
    [pl] = d["placements"]
    assert {k: v for k, v in pl.items() if k != "problems"} == eng.get("placement:C1") and pl["problems"] == []
    assert d["order"] == eng.get("order.json") and d["handoff"] is None and d["dry_run"] is None and d["g3"] is None
    assert [(r["kind"], r["deliver_seq"]) for r in d["reports"]] == [("G1", 1), ("G2", 3), ("G3", 5)]
    assert d["reports"][2]["text"] == eng.get("report:G3")["markdown"]
    assert d["words"]["arm"] == engine_run.ARM_ZH and d["words"]["reading_kind"] == engine_run.KIND_ZH
    # 对照 id 与引擎交付末尾那张表（E-U5）是同一个
    table = engine_run.artifact_table(eng.state["artifacts"])
    for a in d["artifacts"]:
        assert f"| {a['name']} | {a['artifact_id']} | {a['sha256']} |" in table
    assert [u["id"] for u in d["units"] if u["step"] == "S5"] == ["ruwei:C1"]
    # 引擎接进内核后，交付时登记过的产物在 registered.json 里有真的 id；没登记过的仍用占位
    sha = eng.state["artifacts"]["order.json"]
    (eng.ws / "registered.json").write_text(json.dumps({sha: "a_42"}), encoding="utf-8")
    ids = {a["name"]: a["artifact_id"] for a in call(url, f"/v1/analyses/{run}")["artifacts"]}
    assert ids["order.json"] == "a_42" and ids["report:G3"].startswith("local:")
    (eng.ws / "registered.json").unlink()
    status, e = _err(
        url, f"/v1/analyses/{run}/decision", {"block": cases.g3_block(["C1"], "gamma"), "deliver_seq": 5}, s.human_token
    )
    assert (status, e["code"]) == (409, "not_yet")
    assert eng.state == json.loads((eng.ws / "run.json").read_text(encoding="utf-8"))  # 端点不改工作区


def test_handoff_done_lists_what_goes_to_implementation(later):
    s, url, out = later
    eng, last = out["done"]
    run = "p_fixture_delta_code"
    row = next(i for i in call(url, "/v1/analyses")["items"] if i["run"] == run)
    assert row["step"] == "done" and row["waiting"] is None and row["mode"] == "formal"
    d = call(url, f"/v1/analyses/{run}")
    h = d["handoff"]
    assert [i["candidate"] for i in h["items"]] == ["C1", "C2"] and h["items"][1]["module"] == "h1.staged"
    assert [x["candidate"] for x in h["held"]] == ["C3"] and all(c["ok"] for c in h["validator"])
    assert len(h["bang_updates"]) == len(eng.get("handoff.json")["bang_updates"]) and not h["library_import"]
    assert d["g3"]["to_implementation"] == ["C1", "C2"] and d["g3"]["hold"] == {"C3": "等 C2 定论后再看"}
    assert [r["kind"] for r in d["reports"]] == ["G1", "G2", "G3", "handoff"]
    assert d["reports"][3]["text"] + _table(last) == last.answer  # 报告就是引擎交付的那一份
    assert d["needs"] == last.needs
    assert [g["decision"]["gate"] for g in d["gates"]] == ["G1", "G2", "G3"]
    kinds = {a["name"]: a["kind"] for a in d["artifacts"]}
    assert kinds["handoff.json"] == "analysis" and kinds["placement:C2"] == "analysis"
    status, e = _err(
        url, f"/v1/analyses/{run}/decision", {"block": "【决定 v1】闸点 1\n选：C1", "deliver_seq": 1}, s.human_token
    )
    assert (status, e["code"]) == (409, "not_at_gate")


def _table(delivery) -> str:
    from paoding_fenjue.engine.run import artifact_table

    return artifact_table(delivery.artifacts)


def test_dry_run_has_one_report_and_no_gates(later):
    s, url, out = later
    eng, _ = out["dry"]
    run = "p_fixture_delta_code.dry"
    d = call(url, f"/v1/analyses/{run}")
    assert d["step"] == "done" and d["mode"] == "dry_run" and d["gates"] == [] and d["waiting"] is None
    r = eng.get("dry_run.json")
    assert d["dry_run"]["auto_picked"] == ["C1", "C2", "C3"] and d["dry_run"]["estimate"] == r["estimate"]
    assert [(i["candidate"], i["likely_outcome"]) for i in d["dry_run"]["items"]] == [
        (i["candidate"], i["likely_outcome"]) for i in r["items"]
    ]
    assert d["dry_run"]["validators"] == eng.get("dry_run.v")
    # 预评估中间没有交付：只列最后那一份，不把没交过的候选清单、核心机制说成交付
    [rep] = d["reports"]
    assert rep["kind"] == "dry_run" and rep["gate"] is None and rep["text"].startswith("# 预评估")
    assert d["needs"] and "不能直接交实现线" in d["needs"][-1] and d["handoff"] is None
    assert len(d["placements"]) == 3
    sha = next(a["sha256"] for a in d["artifacts"] if a["name"] == "dry_run.json")
    assert call(url, f"/v1/analyses/{run}/artifacts/{sha}")["content"] == r


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
