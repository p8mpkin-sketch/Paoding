"""吞噬引擎第二期（docs/design/fenjue/08 §5–§6、09 §2.4–§3、12）：入位、火序、闸点 3、交接包、导入、试算。

验收（11 §4）：三个单例夹具的入位与设计样例一致（替换、分区、并存三种化解，火组，体质影响预判全空，实现步骤
无一落在体质路径）；组合夹具的火序与样例一致；交接包过 V1–V12；导入命令把交接包变成“入位”状态的炼档。
界面约定：给人看的自由文本栏没有内部名词（E-U4）；每次交付带“产物 → Artifact id → sha256”对照表（E-U5）。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "engine_fixtures"))

import cases  # noqa: E402
from script import Script  # noqa: E402

from paoding_fenjue import lianhua as lh  # noqa: E402
from paoding_fenjue import shapes  # noqa: E402
from paoding_fenjue.engine import checks, data, decision, handoff, ruwei, schema  # noqa: E402
from paoding_fenjue.engine.dan import Recorded, Recorder, Reply  # noqa: E402
from paoding_fenjue.engine.run import EngineError, artifact_table, report_dry_run, report_g3, report_handoff  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "docs/design/fenjue/engine/examples"
CASE = {"alpha": "a", "beta": "b", "gamma": "c"}
TERMS = data.table("vocab")["internal_terms"]


def _example(fx: str) -> dict:
    return json.loads((EX / f"case-{CASE[fx]}.expected.json").read_text(encoding="utf-8"))["expected"]


def _run(fx: str, tmp: Path):
    """一路走到交接包：G1 全选、G2 全确认、G3 按 cases.g3_block。返回 (引擎, [每次交付])。"""
    eng = cases.engine(fx, "code", tmp, Recorded.load(cases.recording(fx, "code")))
    out = [eng.start(cases.intake(fx, "code"))]
    out.append(eng.follow_up(cases.g1_block(eng.get("candidates.json"))))
    ids = list(eng.x["picked"])
    out.append(eng.follow_up(cases.g2_block(ids)))
    out.append(eng.follow_up(cases.g3_block(ids, fx)))
    return eng, out


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return {fx: _run(fx, tmp_path_factory.mktemp(fx)) for fx, _ in cases.TO_HANDOFF}


@pytest.fixture(scope="module")
def dry(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dry")
    eng = cases.engine("delta", "code", tmp, Recorded.load(cases.recording("delta", "code", ".dry")), ".dry")
    return eng, eng.start(cases.intake("delta", "code", "dry_run")), tmp


# ---------------------------------------------------------------- 入位：与设计样例一致（11 §4）


@pytest.mark.parametrize("fx", ["alpha", "beta", "gamma"])
def test_placement_matches_the_design_example(runs, fx):
    eng, _ = runs[fx]
    p = eng.get("placement:C1")
    want = _example(fx)["placement"]
    assert [(a["atom"], a["home"], a.get("owner_now")) for a in p["atoms"]] == [
        (a["atom"], a["home"], a.get("owner_now")) for a in want["atoms"]
    ]
    pick = ("id", "slot", "seats", "also_touches", "ports", "lineage", "switch")
    assert {k: p["fire"].get(k) for k in pick} == {k: want["fire"].get(k) for k in pick}
    assert [(g["id"], g["slot"], g["lineage"]["from"], g["ports"]) for g in p["group"]] == [
        (g["id"], g["slot"], g["lineage"]["from"], g["ports"]) for g in want["group"]
    ]
    assert p["replaces"] == want["replaces"]
    assert [
        (c["fire"], c["atom"], c["kind"], c["resolution"], "partition_by" in c) for c in p["conflicts"]["fires"]
    ] == [(c["fire"], c["atom"], c["kind"], c["resolution"], "partition_by" in c) for c in want["conflicts"]["fires"]]
    assert [(k["kernel"], k["resolution"]) for k in p["conflicts"]["kernel"]] == [
        (k["kernel"], k["resolution"]) for k in want["conflicts"]["kernel"]
    ]
    assert p["difficulty"] == want["difficulty"]
    assert p["kernel_forecast"] == [] and p["split"] == [] and p["new_slot"] is None
    assert [r["dim"] for r in p["readings"]] == [r["dim"] for r in want["readings"]]
    assert {r["dim"] for r in p["readings"] if r.get("mandatory")} == {
        r["dim"] for r in want["readings"] if r.get("mandatory")
    }
    assert [(s["slot"], s["where"]) for s in p["steps"]] == [(s["slot"], s["where"]) for s in want["steps"]]
    assert all(c["ok"] for c in p["checks"]), [c for c in p["checks"] if not c["ok"]]
    assert schema.errors(p, "placement") == []


def test_three_typical_resolutions(runs):
    """甲：跨火位成火组、必须替换；乙：参数冲突按道分区；丙：单火位互补并存。"""
    a = runs["alpha"][0].get("placement:C1")
    b = runs["beta"][0].get("placement:C1")
    c = runs["gamma"][0].get("placement:C1")
    assert a["replaces"] == "h1.solo" and [g["id"] for g in a["group"]] == ["h7.result-stages"]
    assert {x["resolution"] for x in a["conflicts"]["fires"]} == {"replace"}
    part = b["conflicts"]["fires"][0]
    assert (part["kind"], part["resolution"], part["partition_by"]) == (
        "parametric",
        "partition",
        "题的道（goal.accept = open）",
    )
    assert b["replaces"] is None
    assert [(x["kind"], x["resolution"]) for x in c["conflicts"]["fires"]] == [("none", "coexist")]


def test_strict_lane_reading_only_when_h1_to_h5_change(runs):
    dims = {fx: {r["dim"] for r in runs[fx][0].get("placement:C1")["readings"]} for fx in ("alpha", "beta", "gamma")}
    assert "严格道事件日志不变" in dims["alpha"] and "严格道事件日志不变" in dims["beta"]
    assert "严格道事件日志不变" not in dims["gamma"]
    for d in dims.values():
        assert {"旧日志逐字节回放", "凭据泄漏数"} <= d


def test_no_step_lands_in_kernel_paths(runs):
    for eng, _ in runs.values():
        for cid in eng.x["confirmed"]:
            p = eng.get(f"placement:{cid}")
            assert ruwei.kernel_forecast(p["steps"]) == []
            assert all(s["kernel_lines"] == 0 for s in p["steps"])


def test_placer_and_design_retries_are_driven_by_deterministic_checks(runs):
    """组合夹具里位丹第一次拆出表外原子、主丹第一次把一步写进体质路径：都被确定性的步骤拦下、交回重做。"""
    keys = set(Recorded.load(cases.recording("delta", "code")).entries)
    assert "ruwei:C1:r1:place:2" in keys and "ruwei:C1:r1:place:3" not in keys
    assert "ruwei:C2:r1:design:2" in keys and "ruwei:C2:r1:design:3" not in keys
    eng, _ = runs["delta"]
    assert eng.x["placement_problems"] == {"C1": [], "C2": [], "C3": []}


# ---------------------------------------------------------------- 火序与闸点 3


def test_combined_order_matches_the_design_example(runs):
    eng, _ = runs["delta"]
    want = json.loads((EX / "case-d.order.expected.json").read_text(encoding="utf-8"))
    got = eng.get("order.json")
    assert [(o["candidate"], o["position"], o["P"], o.get("waits_for")) for o in got["order"]] == [
        (o["candidate"], o["position"], o["P"], o.get("waits_for")) for o in want["order"]
    ]
    assert got["held"] == []
    rel = eng.get("placement:C2")["conflicts"]["candidates"]
    assert [(r["other"], r["relation"]) for r in rel] == [("C3", "sequential")]
    assert eng.get("placement:C1")["conflicts"]["candidates"] == []


def test_gate_3_delivery_lists_placements_and_order(runs):
    eng, ds = runs["delta"]
    g3 = ds[2]
    assert g3.gate == "G3" and g3.outcome == "answered" and g3.passed
    assert set(g3.artifacts) == {"placement:C1", "placement:C2", "placement:C3", "order.json", "report:G3"}
    assert "集成顺序" in g3.answer and "C3" in g3.answer


def test_handoff_document(runs):
    eng, ds = runs["delta"]
    final = ds[3]
    h = eng.get("handoff.json")
    assert eng.state["step"] == "done" and final.gate is None and final.outcome == "answered" and final.passed
    assert schema.errors(h, "handoff") == []
    assert all(c["ok"] for c in h["validator"]), [c for c in h["validator"] if not c["ok"]]
    assert [it["candidate"] for it in h["items"]] == ["C1", "C2"]
    assert h["held"] == [{"candidate": "C3", "why": "slot_locked", "note": h["held"][0]["note"]}]
    assert "C2" in h["held"][0]["note"]
    assert h["g3_follow_up_seq"] == next(g["follow_up_seq"] for g in eng.state["gates"] if g["gate"] == "G3")
    by_op = {(u["op"], u.get("id") or u["entry"]["id"]): u for u in h["bang_updates"]}
    assert by_op[("set_status", "Y-003")]["status"] == "handed_off"
    assert by_op[("add", "Y-007")]["entry"]["status"] == "handed_off"
    assert by_op[("add_run", "Y-002")]["run"]["outcome"].startswith("搁置")
    for it in h["items"]:
        assert it["artifacts"]["essence"] == shapes.digest(it["essence"])
        assert it["artifacts"]["placement"] == shapes.digest(it["placement"])
        assert it["cuiyi"] == handoff.render_cuiyi(it["essence"], "cz")
    lic = h["basis"]["snapshots"][0]["license"]
    assert (lic["status"], lic["reuse"]) == ("strong_copyleft", "idea_only")
    assert "不得打开原码" in final.answer


def test_cuiyi_rendering_rules_reproduce_the_design_handoff():
    """12 §2.2 的渲染规则：设计样例交接包里的八栏就是它的火意按规则渲染出来的（除“遮住出处”一栏的措辞）。"""
    h = json.loads((EX / "case-d.handoff.expected.json").read_text(encoding="utf-8"))
    for it in h["items"]:
        got = handoff.render_cuiyi(it["essence"], "cz")
        assert {k: v for k, v in got.items()} == it["cuiyi"]


def test_gate_3_decisions_are_checked(tmp_path):
    eng = cases.engine("delta", "code", tmp_path, Recorder(Script("delta", "code")))
    eng.start(cases.intake("delta", "code"))
    eng.follow_up(cases.g1_block(eng.get("candidates.json")))
    eng.follow_up(cases.g2_block(list(eng.x["picked"])))
    d = eng.follow_up("【决定 v1】闸点 3\n交实现线：C1，C9\n改：C1.placement.arms.B = x")
    assert d.gate == "G3"
    assert any("没有入位的候选 C9" in n for n in d.needs)
    assert any("没读懂" in n and "改：" in n for n in d.needs)
    d = eng.follow_up("【决定 v1】闸点 3\n交实现线：C1")
    assert d.gate == "G3" and any("还没有决定：C2, C3" in n for n in d.needs)
    d = eng.follow_up("【决定 v1】闸点 3\n退回：C3")
    assert d.gate == "G3" and eng.x["rounds_s5"] == {"C3": 2}
    assert eng._unit("ruwei:C3")["state"] == "done"
    d = eng.follow_up("【决定 v1】闸点 3\n退回：闸点 2")
    assert d.gate == "G2" and eng.x["confirmed"] == []
    eng.follow_up(cases.g2_block(list(eng.x["picked"])))
    d = eng.follow_up("【决定 v1】闸点 3\n交实现线：C1\n搁置：C2（先看结果页）\n排除：C3（不做压缩）")
    h = eng.get("handoff.json")
    assert [it["candidate"] for it in h["items"]] == ["C1"]
    ex = [u for u in h["bang_updates"] if u["op"] == "set_status" and u["id"] == "Y-002"]
    assert ex and ex[0]["status"] == "excluded" and ex[0]["note"] == "不做压缩"
    with pytest.raises(EngineError, match="已停在 done"):
        eng.resume()


def test_gate_3_exclude_needs_a_reason():
    dec = decision.parse("【决定 v1】闸点 3\n排除：C2\n交实现线：C1")
    assert dec["unparsed"] == ["排除：C2"] and dec["to_implementation"] == ["C1"]


# ---------------------------------------------------------------- 确定性的入位步骤（单元）


def _cand(slot="H7", also=()):
    return {"id": "C1", "name": "demo", "title": "演示", "slot": slot, "also_slots": list(also)}


def _essence(emergent=True, conflicts=(), features=()):
    em = [
        {"dim": "演示率", "dir": "up", "why_zero_B": "没有", "why_zero_A1": "没有", "measure": "structural", "gate": 1}
    ]
    return {
        "candidate": "C1",
        "masked": {
            "statement": "演示",
            "mechanism": [
                {
                    "step": 1,
                    "trigger": "t",
                    "input": "i",
                    "transform": "x",
                    "output": "o",
                    "primitives": ["记录"],
                    "features": list(features),
                }
            ],  # fmt: skip
            # 九栏齐全：进归位的提炼结果必须如此（sections.gaps），手写的夹具也不例外
            "premises": [{"id": "p1", "statement": "有记录可读", "holds_here": "yes", "why": "事件账里有"}],
            "costs": [{"id": "c1", "cost": "多存一份记录", "kind": "storage", "here": "would_pay"}],
            "overlaps": [],
            "conflicts": list(conflicts),
            "fusion": {"statement": "演示融合", "emergent": em if emergent else []},
            "split": [],
            "implementations": [
                {"sketch": "逐条记录", "primitives": ["记录"]},
                {"sketch": "攒一批再对照", "primitives": ["记录", "对照"]},
            ],
        },
    }


def _organ():
    return {"class": "感知官", "retire_signal": "r", "enable_when": "开放道", "control_arm": "B"}


def test_atom_table_covers_every_parameter_of_the_gongfa():
    assert ruwei.unmapped() == []
    assert ruwei.atom_of("H1", "forms.*.ends_on") == "session.end"
    assert ruwei.atom_of("H4", "relay_notes") == "ctx.relay_notes"
    assert ruwei.atom_of("H4", "nope") is None


def test_rule_family_decides_the_conflict_kind():
    assert ruwei.conflict_kind("ctx.relay_notes", {"format": "x"}, {"relay_notes": "NOTES.md"}) == "parametric"
    assert ruwei.conflict_kind("ctx.compress", {"max_items": 5}, {"trigger_at_context": 0.7}) == "semantic"
    assert ruwei.conflict_kind("ctx.compress", {"unknown": 1}, {"trigger_at_context": 0.7}) == "semantic"
    assert ruwei.family("view.replay", {"anchor_cap": True}) is None  # 布尔不算整数


def test_kernel_atom_is_split_and_the_candidate_is_held():
    prop = {
        "atoms": [
            {"atom": "report.claim_link", "params": {"show": "x"}, "emergent": True},
            {"atom": "kernel.evidence", "why_other": "要一类新证据"},
        ],  # fmt: skip
        "fire": {"id": "h7.demo-x", "params": {}, "organ": _organ()},
    }
    sk = ruwei.skeleton(_cand(), _essence(), prop)
    assert sk.problems == []
    p = sk.placement
    assert [s["kernel"] for s in p["split"]] == ["T5"]
    assert [(k["kernel"], k["resolution"]) for k in p["conflicts"]["kernel"]] == [("T5", "split_to_kernel")]
    ruwei.finish(p, sk, _essence())
    assert p["difficulty"]["parts"]["kernel_split"] == 1 and p["difficulty"]["value"] == 3
    cand = {**_cand(), "value": 2, "confidence": 1.0, "risk": "R0", "priority": 2.0}
    assert ruwei.order([cand], {"C1": p})["held"] == [
        {"candidate": "C1", "why": "waits_kernel_split", "note": "有一部分要先拆去内核修订"}
    ]
    assert ruwei.kernel_areas(p) == ["graph/src/"]


def test_unknown_atoms_other_without_proposal_and_missing_group_are_problems():
    prop = {"atoms": [{"atom": "report.magic"}, {"atom": "other"}, {"atom": "session.stages", "emergent": True}],
            "fire": {"id": "h1.demo", "seats": ["solve"], "params": {}, "organ": _organ()}}  # fmt: skip
    sk = ruwei.skeleton(_cand("H1"), _essence(), prop)
    text = "；".join(sk.problems)
    assert "没有这个决策原子：report.magic" in text
    assert "other 的原子要写一句为什么" in text and "新火位提议" in text
    prop["atoms"] = [
        {"atom": "session.stages", "emergent": True},
        {"atom": "report.layout", "params": {"group_by": "x"}},
    ]
    sk = ruwei.skeleton(_cand("H1", ["H7"]), _essence(), prop)
    assert any("H7 的行为有变" in x for x in sk.problems)


def test_h1_seat_admits_only_replacement():
    prop = {
        "atoms": [{"atom": "session.end", "params": {"ends_on": "deliver"}, "emergent": True}],
        "fire": {
            "id": "h1.demo",
            "seats": ["solve"],
            "params": {"forms": {"solve": {"tools": ["deliver"]}}},
            "organ": _organ(),
        },  # fmt: skip
        "resolutions": [{"atom": "session.end", "resolution": "partition", "partition_by": "道"}],
    }
    sk = ruwei.skeleton(_cand("H1"), _essence(), prop)
    row = sk.placement["conflicts"]["fires"][0]
    assert (row["fire"], row["kind"], row["resolution"]) == ("h1.solo@2", "parametric", "replace")
    assert "不能分开并存" in row["note"]
    assert sk.placement["replaces"] == "h1.solo"
    assert sk.placement["fire"]["lineage"]["from"] == ["h1.solo"]
    prop["fire"]["seats"] = ["planner"]
    assert any("没有席位 planner" in x for x in ruwei.skeleton(_cand("H1"), _essence(), prop).problems)


def test_disallowed_resolution_and_missing_partition_condition():
    prop = {
        "atoms": [{"atom": "ctx.relay_notes", "params": {"format": "x"}, "emergent": True}],
        "fire": {"id": "h4.demo", "params": {}, "organ": _organ()},
        "resolutions": [{"atom": "ctx.relay_notes", "resolution": "reject"}],
    }
    sk = ruwei.skeleton(_cand("H4"), _essence(), prop)
    assert any("不能用 reject 化解" in x for x in sk.problems)
    prop["resolutions"] = [{"atom": "ctx.relay_notes", "resolution": "partition"}]
    assert any("要写分区条件" in x for x in ruwei.skeleton(_cand("H4"), _essence(), prop).problems)


def test_unresolved_probe_feature_fails_v9():
    prop = {"atoms": [{"atom": "report.claim_link", "params": {"show": "x"}, "emergent": True}],
            "fire": {"id": "h7.demo-y", "params": {}, "organ": _organ()}}  # fmt: skip
    ess = _essence(features=["merge_readings"])
    p = ruwei.skeleton(_cand(), ess, prop).placement
    assert ruwei.kernel_issues(ess, p) == ["机制第 1 步的 merge_readings 碰到 T5，既没化解也没拆出"]
    ess = _essence(features=["merge_readings"], conflicts=[
        {"with": "T5", "kind": "kernel", "statement": "s", "resolution": "fused_away", "how": "分列"}])  # fmt: skip
    p = ruwei.skeleton(_cand(), ess, prop).placement
    assert ruwei.kernel_issues(ess, p) == []


def test_kernel_forecast_uses_path_prefixes():
    steps = [
        {"where": ["graph/src/paoding_graph/views.py"]},
        {"where": ["adapter/（适配层）"]},
        {"where": ["web/src/"]},
    ]
    assert ruwei.kernel_forecast(steps) == sorted(
        ["graph/src/", *[p for p in lh.KERNEL_PATHS if p.startswith("adapter/")]]
    )


def test_relations_exclusive_and_slot_locks_in_the_order():
    def pl(cid, atom, params, slot="H4", locks=()):
        return {"candidate": cid, "atoms": [{"atom": atom, "home": slot, "mechanism_steps": [1], "params": params}],
                "fire": {"slot": slot}, "group": [], "split": [], "new_slot": None, "difficulty": {"value": 1},
                "conflicts": {"candidates": [], "slot_locks": list(locks)}}  # fmt: skip

    ps = {
        "C1": pl("C1", "ctx.compress", {"trigger_at_context": 0.7}),
        "C2": pl("C2", "ctx.compress", {"max_items": 9}),
        "C3": pl("C3", "report.claim_link", {"show": "x"}, "H7", [{"slot": "H7", "dossier": "003"}]),
    }
    rel = ruwei.relations(ps)
    assert [(r["other"], r["relation"]) for r in rel["C1"]] == [("C2", "exclusive")]
    for cid, rows in rel.items():
        ps[cid]["conflicts"]["candidates"] = rows
    cands = [
        {"id": c, "value": v, "confidence": 1.0, "risk": "R0", "priority": float(v)}
        for c, v in (("C1", 4), ("C2", 2), ("C3", 1))
    ]
    o = ruwei.order(cands, ps)
    assert [x["candidate"] for x in o["order"]] == ["C1", "C3"]
    assert o["held"] == [{"candidate": "C2", "why": "exclusive_pending", "note": "互斥待定：与 C1 二选一"}]
    assert o["order"][1]["waits_for"] == ["炼档 003"]


def test_v8_catches_budget_numbers_and_manifest_shape():
    p = copy.deepcopy(
        json.loads((EX / "case-d.handoff.expected.json").read_text(encoding="utf-8"))["items"][0]["placement"]
    )
    assert checks.v8(p) == []
    p["fire"]["params"]["max_usd_milli"] = 5000
    p["fire"]["params"]["note"] = "每次最多 20000 tokens"
    p["fire"]["ports"] = ["M9"]
    errs = checks.v8(p)
    assert any("max_usd_milli" in e for e in errs) and any("token" in e for e in errs) and any("M9" in e for e in errs)


# ---------------------------------------------------------------- 导入（lianhua.py import）


def test_import_turns_the_handoff_into_placed_dossiers(runs):
    eng, _ = runs["delta"]
    h = eng.get("handoff.json")
    assert handoff.check(h) == []
    docs = {}
    for i, it in enumerate(h["items"], 2):
        no = f"{i:03d}"
        d = handoff.to_dossier(it, no, run=h["run"], provenance=it["essence"]["provenance"])
        assert d["status"] == "placed" and d["fire"]["lineage"]["dossier"] == no
        assert d["cuiyi"] == it["cuiyi"] and d["engine"]["artifacts"] == it["artifacts"]
        md = lh.render(d)
        assert "### 冲突报告" in md and "### 实现步骤" in md
        docs[it["candidate"]] = d
    c2 = docs["C2"]
    assert [m["fire"]["id"] for m in c2["group"]] == ["h7.result-stages"]
    assert c2["group"][0]["replaces"] == "h7.result" and c2["metrics"]["slots"] == ["H1", "H7"]
    assert handoff.slot_locks(docs.values()) == {"H7": "002", "H1": "003"}
    bang = {"v": 1, "entries": cases.bang()}
    out = handoff.apply_bang(bang, h["bang_updates"], "2026-11-21", {"C1": "002", "C2": "003"})
    e = {x["id"]: x for x in out["entries"]}
    assert e["Y-003"]["status"] == "handed_off" and e["Y-003"]["dossier"] == "002"
    assert e["Y-007"]["status"] == "handed_off" and e["Y-007"]["dossier"] == "003"
    assert e["Y-002"]["status"] == "identified" and e["Y-002"]["runs"][-1]["outcome"].startswith("搁置")
    with pytest.raises(handoff.ImportRefused, match="已经有 Y-007"):
        handoff.apply_bang(out, h["bang_updates"], "2026-11-21")


def test_import_refuses_tampered_handoff_and_rechecks_the_gongfa(runs):
    eng, _ = runs["delta"]
    h = copy.deepcopy(eng.get("handoff.json"))
    h["items"][0]["placement"]["steps"][0]["where"] = ["graph/src/"]
    errs = handoff.check(h)
    assert any("V3" in e for e in errs) and any("V9" in e for e in errs)
    h = eng.get("handoff.json")
    g = copy.deepcopy(shapes.gongfa())
    g["fires"]["H7"] = []
    assert any("report.layout 的拥有者" in x for x in handoff.recheck(h["items"][1]["placement"], g))
    assert handoff.recheck(h["items"][1]["placement"]) == []


def test_group_installs_and_reverts_together():
    g = {k: v for k, v in shapes.gongfa().items() if k != "digest"}
    d = {
        "dossier": "009", "title": "演示", "status": "readings_ready", "replaces": "h1.solo",
        "fire": {"id": "h1.staged", "ver": 1, "slot": "H1"},
        "group": [{"fire": {"id": "h7.result-stages", "ver": 1, "slot": "H7"}, "replaces": "h7.result"}],
        "verdict": None, "reverts": [], "metrics": {"reverts": 0},
    }  # fmt: skip
    g2, old = lh.install(g, d)
    assert old == "h1.solo@2"
    assert "h1.staged@1" in g2["fires"]["H1"] and g2["fires"]["H7"] == ["h7.result-stages@1"]
    assert g2["holdout"]["H7"] == ["h7.result@1"] and "h1.solo@2" in g2["holdout"]["H1"]
    d, g3 = lh.jue(d, g, "cz", "2026-11-21", "huolian", [])
    d2, g4 = lh.sanhuo(d, g3, "cz", "2026-11-22", "演示")
    assert g4["fires"] == g["fires"] and g4.get("holdout", {}) == g.get("holdout", {})
    assert d2["reverts"][0]["back_to"] == "h1.solo@2"


def test_ruwei_checks_group_members():
    shihuo = {"source": "s", "phenomenon": "p", "gap": "g", "is_fire": "是"}
    d = lh.cuiyi(lh.new("009", "demo", "演示", "2026-11-21", shihuo), {k: "x" for k in lh.CUIYI})
    fire = {"id": "h1.x", "ver": 1, "slot": "H1", "ports": [], "params": {}, "assets": [], "organ": {},
            "lineage": {"dossier": "009", "from": []}, "switch": "fires.H1"}  # fmt: skip
    member = {**fire, "id": "h1.y"}
    reading = [{"dim": "d", "kind": "共有", "dir": "up"}]
    with pytest.raises(lh.StepError, match="另一个火位"):
        lh.ruwei(d, fire, None, {}, reading, group=[{"fire": member, "replaces": None}])
    member = {**fire, "id": "h7.y", "slot": "H7", "lineage": {"dossier": "009", "from": []}}
    with pytest.raises(lh.StepError, match="lineage.from"):
        lh.ruwei(d, fire, None, {}, reading, group=[{"fire": member, "replaces": "h7.result"}])
    out = lh.ruwei(d, fire, None, {}, reading, group=[{"fire": member, "replaces": None}])
    assert out["group"][0]["fire"]["id"] == "h7.y"


@pytest.fixture
def cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("lianhua_cli_import", ROOT / "scripts" / "lianhua.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dossiers = tmp_path / "dossiers"
    shutil.copytree(ROOT / "docs/design/fenjue/dossiers", dossiers)
    for extra in dossiers.glob("[0-9][0-9][0-9]-*"):  # 这里的断言按“仓库里只有记录 001”写的：之后开的记录不带进来
        if not extra.name.startswith("001-"):
            extra.unlink()
    pkg = tmp_path / "pkg"
    shutil.copytree(ROOT / "fenjue/src/paoding_fenjue/fires", pkg / "fires")
    shutil.copy(ROOT / "fenjue/src/paoding_fenjue/gongfa.json", pkg / "gongfa.json")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"v": 1, "entries": cases.bang()}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mod, "DOSSIERS", dossiers)
    monkeypatch.setattr(mod, "PKG", pkg)
    monkeypatch.setattr(mod, "GONGFA", pkg / "gongfa.json")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "BANG", tmp_path / "yihuobang.json")
    monkeypatch.setattr(mod, "BANG_SEED", seed)
    return mod, dossiers, pkg, tmp_path


def test_cli_import_writes_dossiers_manifests_and_the_bang(cli, runs, capsys):
    mod, dossiers, pkg, tmp = cli
    eng, _ = runs["delta"]
    path = tmp / "handoff.json"
    path.write_text(json.dumps(eng.get("handoff.json"), ensure_ascii=False), encoding="utf-8")
    assert mod.main(["import", str(path), "--only", "C1", "--date", "2026-11-21"]) == 0
    d = json.loads((dossiers / "002-dual-proof.json").read_text(encoding="utf-8"))
    assert d["status"] == "placed" and d["engine"]["candidate"] == "C1"
    assert (dossiers / "002-dual-proof.md").read_text(encoding="utf-8") == lh.render(d)
    assert json.loads((pkg / "fires" / "h7.dual-proof.json").read_text(encoding="utf-8"))["lineage"]["dossier"] == "002"
    bang = {e["id"]: e for e in json.loads((tmp / "yihuobang.json").read_text(encoding="utf-8"))["entries"]}
    assert bang["Y-003"]["status"] == "handed_off" and bang["Y-003"]["dossier"] == "002"
    assert "Y-007" not in bang  # --only C1：别的候选的榜更新不写
    # C2 动 H7（火组成员），H7 被 002 占着：不带 --queue 拒导入，带 --queue 只记榜
    with pytest.raises(SystemExit, match="火位被在途炼档占着"):
        mod.main(["import", str(path), "--only", "C2"])
    assert mod.main(["import", str(path), "--only", "C2", "--queue", "--date", "2026-11-21"]) == 0
    assert not list(dossiers.glob("003-*.json"))
    bang = {e["id"]: e for e in json.loads((tmp / "yihuobang.json").read_text(encoding="utf-8"))["entries"]}
    assert bang["Y-007"]["status"] == "handed_off" and "dossier" not in bang["Y-007"]
    assert "排队" in bang["Y-007"]["history"][-1]["note"]
    assert mod.main(["bang", "show"]) == 0
    assert "Y-003" in capsys.readouterr().out


def test_cli_import_refuses_an_invalid_handoff(cli, runs):
    mod, dossiers, _, tmp = cli
    eng, _ = runs["delta"]
    h = copy.deepcopy(eng.get("handoff.json"))
    h["items"][0]["cuiyi"]["yi"] = "改过的一句"
    path = tmp / "bad.json"
    path.write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="V11"):
        mod.main(["import", str(path)])
    assert not list(dossiers.glob("002-*")) and not (tmp / "yihuobang.json").exists()


# ---------------------------------------------------------------- 试算（09 §3）


def test_dry_run_report(dry):
    eng, d, _ = dry
    r = eng.get("dry_run.json")
    want = json.loads((EX / "case-d.dry-run.expected.json").read_text(encoding="utf-8"))
    assert schema.errors(r, "dry-run") == []
    assert eng.state["step"] == "done" and eng.state["gates"] == [] and d.gate is None and d.passed
    assert r["auto_picked"] == ["C1", "C2", "C3"] and r["candidates"]["mode"] == "dry_run"
    pick = (
        "candidate",
        "slot",
        "group_slots",
        "replaces",
        "conflicts",
        "kernel_forecast",
        "difficulty",
        "likely_outcome",
    )
    assert [{k: it.get(k) for k in pick} for it in r["items"]] == [{k: it.get(k) for k in pick} for it in want["items"]]
    assert all(c["ok"] for c in eng.get("dry_run.v"))
    assert all(c["id"] != "K6" for it in r["items"] for c in it["checks"])
    keys = set(Recorded.load(cases.recording("delta", "code", ".dry")).entries)
    assert not any(k.endswith((":extra1", ":extra2", ":blind")) or ":design:" in k for k in keys)
    assert "cuiyi:C1:r1:main:2" in keys  # 指令痕迹（K8）例外：照样重写，金丝雀不进试算报告
    assert set(r["estimate"]["tokens"]) == {"light", "mid", "heavy"} and r["estimate"]["minutes"] > 0
    doc = eng.get("bang_updates.json")
    assert isinstance(doc, dict) and doc["mode"] == "dry_run"  # 登记只收对象（trial-a-2 / c-2 被拒的根因）
    ups = doc["bang_updates"]
    assert {u["status"] for u in ups if u["op"] == "set_status"} == {"dry_run"}
    assert [u["entry"]["status"] for u in ups if u["op"] == "add"] == ["dry_run"]
    assert "预评估" in d.answer and "不能直接交实现线" in d.answer
    # 每项检验的用时只打在人读报告里（读数），不进 dry_run.json 与校验结果
    line = next(x for x in d.answer.splitlines() if x.startswith("检验用时"))
    assert all(f"{k} " in line for k in ("抄写比对", "K4", "V6", "V1")) and "用时" not in json.dumps(
        r, ensure_ascii=False
    )


def test_dry_run_converts_to_formal_without_spending(dry, tmp_path):
    _, _, dry_ws = dry

    class NoDan:
        def call(self, role, key, payload):
            raise AssertionError(f"试算转正式不该调丹：{key}")

    eng = cases.engine("delta", "code", tmp_path, NoDan(), ".formal")
    d = eng.start(cases.intake("delta", "code"), reuse=dry_ws)
    assert d.gate == "G1" and eng.state["mode"] == "formal" and eng.x["reused_from"] == "p_fixture_delta_code.dry"
    doc = eng.get("candidates.json")
    assert doc["mode"] == "formal"
    assert [(c["id"], c["priority"]) for c in doc["candidates"]] == [("C1", 4.0), ("C2", 1.0), ("C3", 1.0)]
    assert eng.state["spent"]["usd_milli"] == 0
    other = cases.engine("alpha", "code", tmp_path / "x", NoDan())
    with pytest.raises(EngineError, match="材料变了"):
        other.start(cases.intake("alpha", "code"), reuse=dry_ws)


# ---------------------------------------------------------------- 界面约定（E-U4、E-U5）


def test_every_delivery_ends_with_the_artifact_table(runs, dry):
    deliveries = [d for _, ds in runs.values() for d in ds] + [dry[1]]
    for d in deliveries:
        assert d.artifacts
        assert d.answer.endswith(artifact_table(d.artifacts).rstrip())
        for name, sha in d.artifacts.items():
            assert f"| {name} | local:{sha[:16]} | {sha} |" in d.answer


def test_artifact_table_uses_the_configured_ids():
    t = artifact_table({"handoff.json": "a" * 64}, lambda name, sha: "art_42")
    assert "| handoff.json | art_42 | " + "a" * 64 + " |" in t


def test_displayed_text_has_no_internal_terms(runs, dry):
    eng, _ = runs["delta"]
    arts = [(eng.get("candidates.json"), "candidates"), (eng.get("handoff.json"), "handoff")]
    for cid in eng.x["confirmed"]:
        arts += [(eng.get(f"essence:{cid}"), "essence"), (eng.get(f"placement:{cid}"), "placement")]
    arts.append((dry[0].get("dry_run.json"), "dry_run"))
    for doc, kind in arts:
        assert checks._plain(checks.displayed(doc, kind)) == [], kind
    reports = [
        report_g3(
            [eng.get(f"placement:{c}") for c in eng.x["confirmed"]], eng.get("order.json"), eng.get("candidates.json")
        ),
        report_handoff(eng.get("handoff.json")),
        report_dry_run(dry[0].get("dry_run.json")),
    ]
    for r in reports:
        assert [t for t in TERMS if t in r] == []


def test_v5_now_covers_every_displayed_field():
    p = json.loads((EX / "case-c.expected.json").read_text(encoding="utf-8"))["expected"]["placement"]
    v5 = checks._plain(checks.displayed(p, "placement"))
    assert any("A′" in x for x in v5) and any("功法" in x for x in v5)
    assert checks._plain(checks.displayed({"plain_summary": "改的是候选方案的排序"}, "candidates")) == []


def test_canaries_never_reach_any_artifact(runs, dry):
    for eng in [*(e for e, _ in runs.values()), dry[0]]:
        blob = " ".join(p.read_text(encoding="utf-8") for p in (eng.ws / "artifacts").glob("*.json"))
        assert not [c for c in cases.CANARIES if c in blob]


def test_placer_payload_never_carries_raw_source(runs):
    """位丹与主丹只看遮蔽视图与表：输入里没有快照原文与外部专名。"""
    rec = json.loads(cases.recording("delta", "code").read_text(encoding="utf-8"))
    for e in rec["entries"] if isinstance(rec, dict) and "entries" in rec else rec:
        if str(e.get("key", "")).startswith("ruwei:"):
            blob = json.dumps(e, ensure_ascii=False)
            assert "mossgate" not in blob


def test_stub_dan_reply_shape():
    assert Reply({"x": 1}, 1, 2).output == {"x": 1}


def test_outcome_is_written_back_to_the_bang(runs):
    """结局回写（12 §5）：收下记已吞噬与品阶，不收记教训，散火记已散火；排队的火位空出来就提示可导入。"""
    eng, _ = runs["delta"]
    h = eng.get("handoff.json")
    bang = handoff.apply_bang({"v": 1, "entries": cases.bang()}, h["bang_updates"], "2026-11-21", {"C1": "002"})
    d = {"dossier": "002", "verdict": {"outcome": "huolian", "jie": 3}, "outcome_why": []}
    out = handoff.writeback(bang, d, "jue", "2026-11-22", "cz")
    assert out is not None
    e = next(x for x in out["entries"] if x.get("dossier") == "002")
    assert e["status"] == "absorbed" and e["jie"] == 3 and e["history"][-1]["note"] == "炼档 002：火莲"
    no = {"dossier": "002", "verdict": {"outcome": "binghuo"}, "outcome_why": ["没有任何一维胜过两个来源"]}
    e = next(x for x in handoff.writeback(bang, no, "jue", "2026-11-22", "cz")["entries"] if x.get("dossier") == "002")
    assert e["status"] == "rejected" and e["lessons"] == ["没有任何一维胜过两个来源"]
    e = next(
        x
        for x in handoff.writeback(out, d, "sanhuo", "2026-11-23", "cz", "演示")["entries"]
        if x.get("dossier") == "002"
    )
    assert e["status"] == "reverted" and e["history"][-1]["note"] == "演示"
    assert handoff.writeback(bang, {**d, "dossier": "099"}, "jue", "2026-11-22", "cz") is None
    # C2 排队（已交实现线、没有档号）：H7 被 002 占着时不提示，002 定论后提示
    in_flight = [{"dossier": "002", "status": "placed", "fire": {"slot": "H7"}}]
    queued = [x["id"] for x in handoff.ready_to_import(bang, in_flight) if not x.get("dossier")]
    assert "Y-007" not in queued
    done = [{**in_flight[0], "status": "adopted"}]
    assert "Y-007" in [x["id"] for x in handoff.ready_to_import(bang, done)]
