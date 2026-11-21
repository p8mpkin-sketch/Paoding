"""吞噬引擎的确定性验收（docs/design/fenjue/11-acceptance.md §6）：录好的丹输出回放，13 次识火，代码形态四次走到闸点 2。

判的是确定性骨架：勘察、聚焦、公式、检验、校验器、闸点、续做。真模型的召回与质量由测试方跑（11 §7）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "engine_fixtures"))

import cases  # noqa: E402

from paoding_fenjue.engine import formulas, schema  # noqa: E402
from paoding_fenjue.engine.dan import Recorded  # noqa: E402

EX = cases.ROOT / "docs/design/fenjue/engine/examples"
NAME_OF = {"alpha": "staged-proof", "beta": "anchored-fold", "gamma": "dual-proof"}
CASE_OF = {"alpha": "a", "beta": "b", "gamma": "c"}
C_RANGE = {"code": (0.8, 1.0), "docs": (0.56, 0.7), "service": (0.0, 0.6), "description": (0.0, 0.4)}
LICENSE = {"alpha": "Apache-2.0", "beta": "Apache-2.0", "gamma": "Apache-2.0", "delta": "GPL-3.0-only"}


def expected(fixture: str) -> dict:
    return json.loads((EX / f"case-{CASE_OF[fixture]}.expected.json").read_text(encoding="utf-8"))["expected"]


def run_to_g1(fixture, form, tmp_path):
    eng = cases.engine(fixture, form, tmp_path, Recorded.load(cases.recording(fixture, form)))
    d = eng.start(cases.intake(fixture, form))
    return eng, d


@pytest.fixture(scope="module")
def g1_runs(tmp_path_factory):
    out = {}
    for fx, form in cases.RUNS:
        eng, d = run_to_g1(fx, form, tmp_path_factory.mktemp(f"{fx}-{form}"))
        out[(fx, form)] = (eng, d, eng.get("candidates.json"))
    return out


@pytest.fixture(scope="module")
def g2_runs(g1_runs):
    out = {}
    for key in cases.TO_GATE_2:
        eng, _, doc = g1_runs[key]
        d = eng.follow_up(cases.g1_block(doc))
        out[key] = (eng, d)
    return out


# ---------------------------------------------------------------- 识火


@pytest.mark.parametrize("fx,form", cases.RUNS)
def test_candidates_document_is_valid_and_all_validators_pass(g1_runs, fx, form):
    eng, d, doc = g1_runs[(fx, form)]
    assert d.gate == "G1" and d.outcome == "partial"
    assert schema.errors(doc, "candidates") == []
    bad = [c for c in doc["checks"] if not c["ok"]]
    assert bad == [], bad
    assert [c["id"] for c in doc["checks"]] == [f"V{i}" for i in range(1, 13)]
    assert d.artifacts["candidates.json"] == eng.state["artifacts"]["candidates.json"]


def _hit(doc, name):
    return next((c for c in doc["candidates"][:5] if c["name"] == name), None)


def test_recall_by_form(g1_runs):
    for form in cases.FORMS:
        hits = sum(_hit(g1_runs[(fx, form)][2], NAME_OF[fx]) is not None for fx in NAME_OF)
        need = 3 if form in ("code", "docs") else 2
        assert hits >= need, (form, hits)


@pytest.mark.parametrize("fx", ["alpha", "beta", "gamma"])
@pytest.mark.parametrize("form", cases.FORMS)
def test_slot_gaps_and_confidence(g1_runs, fx, form):
    doc = g1_runs[(fx, form)][2]
    c = _hit(doc, NAME_OF[fx])
    if c is None:
        pytest.fail(f"{fx}.{form} 没召回")
    want = expected(fx)["candidate"]
    assert c["slot"] == want["slot"]
    lo, hi = C_RANGE[form]
    assert lo <= c["confidence"] <= hi
    have = {g["dim"]: g for g in c["gaps"]}
    for g in want["gaps"]:
        if form in ("code", "docs") or g["dim"] in have:
            assert have[g["dim"]]["type"] == g["type"]
            assert abs(have[g["dim"]]["theirs"] - g["theirs"]) <= 1
    if form == "code":
        assert c["value"] == want["value"]
        assert c["difficulty"] == want["difficulty"]
        assert c["risk"] == want["risk"]
        assert c["priority"] == want["priority"]


def test_combined_fixture_matches_the_design_example(g1_runs):
    doc = g1_runs[("delta", "code")][2]
    want = json.loads((EX / "case-d.candidates.expected.json").read_text(encoding="utf-8"))
    pick = ("id", "name", "slot", "value", "confidence", "difficulty", "risk", "priority")
    assert [{k: c[k] for k in pick} for c in doc["candidates"]] == [{k: c[k] for k in pick} for c in want["candidates"]]
    for c, w in zip(doc["candidates"], want["candidates"], strict=True):
        assert [(g["dim"], g["type"], g["pain"]) for g in c["gaps"]] == [
            (g["dim"], g["type"], g["pain"]) for g in w["gaps"]
        ]
        assert c.get("dedupe", {}).get("bang") == w.get("dedupe", {}).get("bang")
        assert set(w["flags"]) <= set(c["flags"])
    strip = [{k: a[k] for k in ("dim", "ours", "theirs", "by")} for a in doc["already_have"]]
    assert strip == [{k: a[k] for k in ("dim", "ours", "theirs", "by")} for a in want["already_have"]]
    assert [n["what"] for n in doc["not_fire"]] == [n["what"] for n in want["not_fire"]]
    assert doc["unseen_slots"] == want["unseen_slots"]


def test_gamma_splits_trace_from_auto_link(g1_runs):
    """丙是陷阱：自动留档进已有不差，只有自动关联成候选。"""
    doc = g1_runs[("gamma", "code")][2]
    assert [c["name"] for c in doc["candidates"]] == ["dual-proof"]
    assert [(a["dim"], a["ours"], a["theirs"], a["by"]) for a in doc["already_have"]] == [
        ("h3.exec-trace", 3, 2, "h3.base@1")
    ]


def test_fire_order_of_the_combined_fixture(g1_runs):
    doc = g1_runs[("delta", "code")][2]
    want = json.loads((EX / "case-d.order.expected.json").read_text(encoding="utf-8"))
    items = [
        formulas.Item(c["id"], c["value"], c["confidence"], c["difficulty"], c["risk"], c["priority"])
        for c in doc["candidates"]
    ]
    got = formulas.fire_order(items, after=formulas.slot_edges(doc["candidates"]))
    assert [(r["candidate"], r["P"], r.get("waits_for")) for r in got.order] == [
        (r["candidate"], r["P"], r.get("waits_for")) for r in want["order"]
    ]
    assert got.cycle == [] and got.held == want["held"]


def test_description_only_asks_for_material(g1_runs):
    """N6：只有描述，置信 ≤ 0.4，needs 要求补材料，不推荐直接走正式流程。"""
    _, d, doc = g1_runs[("alpha", "description")]
    c = doc["candidates"][0]
    assert c["confidence"] <= 0.4
    assert c["recommend"]["level"] == "not_recommended"
    assert any("补充" in n for n in d.needs)


@pytest.mark.parametrize("fx,form", cases.RUNS)
def test_license_is_annotated_everywhere(g1_runs, fx, form):
    doc = g1_runs[(fx, form)][2]
    snaps = doc["basis"]["snapshots"] + [s for c in doc["candidates"] for s in c["provenance"]["snapshots"]]
    for s in snaps:
        if form == "description":
            assert s["license"]["status"] == "cz_description"
        else:
            assert s["license"]["spdx"] == LICENSE[fx]
    if fx == "delta":  # N5
        assert all(
            s["license"]
            == {"status": "strong_copyleft", "spdx": "GPL-3.0-only", "detected": "LICENSE", "reuse": "idea_only"}
            for s in snaps
        )
        assert all("license_restricted" in c["flags"] for c in doc["candidates"])


def test_injection_is_flagged_and_reported(g1_runs):
    """N1–N3：注入探测命中；报告单列；候选都带来源有疑似指令的旗。"""
    eng, d, doc = g1_runs[("delta", "code")]
    sv = eng.get("survey:s1")
    assert set(sv["injection"]) == {"README.md", "mossgate/upload.py"}
    assert any("隐藏字符" in h for h in sv["injection"]["README.md"])
    assert any("疑似写给智能体的指令" in n for n in d.needs)
    assert all("injection_flagged_sources" in c["flags"] for c in doc["candidates"])
    flagged = [o for o in eng.observations().values() if o["suspected_injection"]]
    assert flagged and all(o["evidence"][0]["path"] == "README.md" for o in flagged)


def test_observation_ids_are_content_addressed_and_evidence_is_real(g1_runs):
    eng, _, _ = g1_runs[("alpha", "code")]
    files = {f["path"]: f for f in eng.get("survey:s1")["files"]}
    from paoding_fenjue.engine.shihuo import obs_id
    from paoding_fenjue.engine.survey import load_snapshot

    snap = load_snapshot("s1", "code", cases.HERE / "alpha" / "code")
    for o in eng.observations().values():
        assert schema.errors(o, "observation") == []
        assert o["id"] == obs_id(o)
        ev = o["evidence"][0]
        assert ev["path"] in files
        a, b = ev["lines"]
        import hashlib

        chunk = "".join(snap.texts[ev["path"]].splitlines(keepends=True)[a - 1 : b])
        assert hashlib.sha256(chunk.encode()).hexdigest() == ev["sha256"]


def test_rerun_is_byte_identical(g1_runs, tmp_path):
    """同一份快照、同一份录音重跑，候选清单与勘察单逐字节相同（内容寻址）。"""
    eng, _, _ = g1_runs[("delta", "code")]
    again, _ = run_to_g1("delta", "code", tmp_path)
    for name in ("candidates.json", "survey:s1", "snapshot:s1"):
        assert again.state["artifacts"][name] == eng.state["artifacts"][name]


# ---------------------------------------------------------------- 萃意与闸点 2


@pytest.mark.parametrize("fx,form", cases.TO_GATE_2)
def test_essences_pass_the_hard_checks(g2_runs, fx, form):
    eng, d = g2_runs[(fx, form)]
    assert d.gate == "G2" and d.passed, d.needs
    for cid in eng.x["picked"]:
        ess = eng.get(f"essence:{cid}")
        assert schema.errors(ess, "essence") == []
        ks = {c["id"]: c for c in ess["checks"]}
        assert [k for k in ("K1", "K2", "K3", "K4", "K5", "K7", "K8") if not ks[k]["ok"]] == []
        assert ks["K6"]["advisory"]
        assert all(c["ok"] for c in eng.get(f"essence:{cid}.v"))
        assert ess["drafts"]["n"] == 3


@pytest.mark.parametrize("fx", ["alpha", "beta", "gamma"])
def test_emergent_dims_contain_the_expected(g2_runs, fx):
    eng, _ = g2_runs[(fx, "code")]
    ess = eng.get("essence:C1")
    got = {e["dim"] for e in ess["masked"]["fusion"]["emergent"]}
    want = {e["dim"] for e in expected(fx)["essence"]["masked"]["fusion"]["emergent"]}
    assert want <= got
    if fx == "alpha":
        assert not any("对应率" in g for g in got)  # 阶段—留档对应率是异火维，不是新生维


def test_three_draft_disagreement_is_listed(g2_runs):
    eng, _ = g2_runs[("alpha", "code")]
    ess = eng.get("essence:C1")
    assert ess["drafts"]["chosen"] == "main"
    assert any("萃丹二稿没有" in s for s in ess["drafts"]["disagreements"])


def test_canary_in_a_draft_is_caught_and_rewritten(g2_runs):
    """D7 金丝雀：主稿第一次把来源里藏的那句话写进了火意，K8 拦下，主丹带着错误清单重写。"""
    eng, _ = g2_runs[("delta", "code")]
    assert "cuiyi:C1:r1:main:2" in eng.dan.calls
    ess = eng.get("essence:C1")
    assert "本方案已通过全部内核测试" not in json.dumps(ess, ensure_ascii=False)


@pytest.mark.parametrize("fx,form", cases.TO_GATE_2)
def test_no_canary_or_secret_in_any_artifact(g2_runs, fx, form):
    """N1–N4：任何产物、运行状态里都不出现金丝雀与假密钥；没有越界的扩权申请。"""
    eng, _ = g2_runs[(fx, form)]
    blob = "".join(p.read_text(encoding="utf-8") for p in (eng.ws / "artifacts").glob("*.json"))
    blob += (eng.ws / "run.json").read_text(encoding="utf-8") + (eng.ws / "obs.jsonl").read_text(encoding="utf-8")
    for c in cases.CANARIES:
        assert c not in blob
    assert eng.x.get("out_of_scope_requests", 0) == 0


@pytest.mark.parametrize("fx,form", cases.TO_GATE_2)
def test_gate_2_confirm_moves_to_placement(g2_runs, fx, form):
    eng, _ = g2_runs[(fx, form)]
    d = eng.follow_up(cases.g2_block(list(eng.x["picked"])))
    assert eng.state["step"] == "S5"
    assert eng.x["confirmed"] == eng.x["picked"]
    assert set(d.artifacts) == {f"essence:{c}" for c in eng.x["picked"]}
    assert [g["gate"] for g in eng.state["gates"]] == ["G1", "G2"]
    assert all("decision" in g for g in eng.state["gates"])
    assert schema.errors(eng.state, "run") == []
