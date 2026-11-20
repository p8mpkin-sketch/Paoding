"""炼档流程化（焚决 F5，docs/design/fenjue/06-migration.md §2）：功法里的每团火要么是本火，要么有一份已裁决的炼档。

本火：清单的 lineage.from 为空、也不带 lineage.dossier（焚决之前就有、F2 立名的那批）。
其余每团火（在功法里生效的，或在常设留出里的）都要指向 docs/design/fenjue/dossiers/ 下一份炼档，
那份档已经裁决为火莲或合炼，档里的火与清单的 id、火位一致。模板见 dossiers/TEMPLATE.md。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from paoding_fenjue.shapes import fire, fire_ids, gongfa

ROOT = Path(__file__).resolve().parents[2]
DOSSIERS = ROOT / "docs" / "design" / "fenjue" / "dossiers"
FILES = sorted(p for p in DOSSIERS.glob("[0-9][0-9][0-9]-*.json"))
SECTIONS = ("一、识火", "二、萃意", "三、入位", "四、验体", "五、融火", "六、裁决", "七、散火记录")
KEYS = (
    "dossier",
    "name",
    "title",
    "status",
    "identified",
    "fire",
    "kernel_lines_changed",
    "preregistered",
    "arms",
    "readings",
    "outcome_proposed",
    "jie_proposed",
    "metrics",
    "verdict",
    "reverts",
)
# 识火中 → 设计已裁（前三节过了“值不值得炼”）→ 读数已出 → 已裁决收下 / 不收 → 入功法后散火
STATUSES = ("identified", "design_approved", "readings_ready", "adopted", "rejected", "reverted")
OUTCOMES = ("huolian", "helian", "binghuo", "fanshi")  # 火莲、合炼、并火、反噬
TAKEN = ("huolian", "helian")  # 只有这两种可以入功法（03 §3）
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load(p: Path) -> dict[str, Any]:
    d: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return d


def dossiers() -> dict[str, dict[str, Any]]:
    return {load(p)["dossier"]: load(p) for p in FILES}


def in_gongfa() -> dict[str, str]:
    """功法里的每团火（生效的与常设留出的）→ 所在火位。"""
    g = gongfa()
    refs = [(slot, r) for part in ("fires", "holdout") for slot, rs in (g.get(part) or {}).items() for r in rs]
    return {r.partition("@")[0]: slot for slot, r in refs}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_each_dossier_is_complete(path: Path):
    d = load(path)
    missing = [k for k in KEYS if k not in d]
    assert not missing, f"{path.name} 缺 {missing}（照 TEMPLATE.json）"
    assert path.stem == f"{d['dossier']}-{d['name']}", "文件名是档号加短名"
    md = path.with_suffix(".md")
    assert md.exists(), f"{md.name} 不在：炼档是 .md 与 .json 一对"
    text = md.read_text(encoding="utf-8")
    assert [s for s in SECTIONS if f"## {s}" not in text] == [], "炼档的七节要齐（02 §9）"
    assert d["status"] in STATUSES
    assert DATE.match(d["identified"])
    assert d["outcome_proposed"] in (None, *OUTCOMES)
    assert isinstance(d["kernel_lines_changed"], int) and d["kernel_lines_changed"] >= 0
    f = d["fire"]
    assert f["lineage"].get("dossier") == d["dossier"], "档里的火要记出身：lineage.dossier 是本档"
    v = d["verdict"]
    if d["status"] in ("adopted", "rejected", "reverted"):
        assert isinstance(v, dict), f"{path.name}：状态 {d['status']} 要有第六节的裁决"
        assert v.get("by") and DATE.match(v.get("date", "")), "裁决要写裁决人与日期"
        assert v.get("outcome") in OUTCOMES
    if d["status"] == "adopted":
        assert v["outcome"] in TAKEN, "只有火莲与合炼可以入功法"
        assert isinstance(v.get("jie"), int) and v["jie"] > 0
    if d["status"] == "rejected":
        assert v["outcome"] not in TAKEN
    if d["status"] == "reverted":
        assert d["reverts"], "已散火的要在第七节记下谁、何时、为什么"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_readings_point_at_tests_that_still_exist(path: Path):
    """读数表里的出处是测试名时，那个测试还在（改名、删测试会让它变红，读数就失去了出处）。"""
    for r in load(path)["readings"]:
        node = r.get("test")
        if not node:
            continue
        file, _, name = node.partition("::")
        src = ROOT / file
        assert src.exists(), f"{path.name}：读数 {r['dim']} 的出处 {file} 不在了"
        assert not name or f"def {name}(" in src.read_text(encoding="utf-8"), f"{path.name}：{node} 不在了"


@pytest.mark.parametrize("fid", sorted(in_gongfa()))
def test_every_fire_in_the_gongfa_is_native_or_adopted(fid: str):
    f = fire(fid)
    lin = f["lineage"]
    if not lin["from"] and "dossier" not in lin:
        return  # 本火
    ds = dossiers()
    no = lin.get("dossier")
    assert no in ds, f"{fid} 不是本火（lineage.from={lin['from']}），却没有炼档（lineage.dossier）"
    d = ds[no]
    assert d["status"] == "adopted", f"{fid} 在功法里，它的炼档 {no} 却是 {d['status']}：没裁决的火不能生效"
    assert (d["fire"]["id"], d["fire"]["slot"]) == (fid, in_gongfa()[fid]), f"炼档 {no} 里的火与清单对不上"


def test_fires_that_were_not_taken_are_not_in_the_gongfa():
    live = in_gongfa()
    for no, d in dossiers().items():
        if d["status"] in ("rejected", "reverted"):
            assert d["fire"]["id"] not in live, f"炼档 {no} 不收或已散火，{d['fire']['id']} 却还在功法里"


def test_grade_history_matches_the_verdicts():
    """品阶史里带档号的每一阶，都是那份档裁决的品阶；只追加（test_fenjue 另核 0..jie 连续）。"""
    ds = dossiers()
    for h in gongfa()["history"]:
        if "dossier" in h:
            d = ds.get(h["dossier"])
            assert d is not None and d["status"] == "adopted", f"第 {h['jie']} 阶记的炼档 {h['dossier']} 没有裁决"
            assert d["verdict"]["jie"] == h["jie"]


def test_every_manifest_on_disk_is_accounted_for():
    """包里的每份清单要么在功法里，要么是某份炼档的对照臂或上一团火（lineage.from 里提到它），不留孤儿。"""
    live = set(in_gongfa())
    named = {x for fid in fire_ids() for x in fire(fid)["lineage"]["from"]}
    orphans = [fid for fid in fire_ids() if fid not in live and fid not in named]
    assert orphans == [], f"这几份清单既不在功法里，也不是谁的上一团火：{orphans}"


def test_template_has_every_key_and_section():
    t = load(DOSSIERS / "TEMPLATE.json")
    assert list(t) == list(KEYS)
    text = (DOSSIERS / "TEMPLATE.md").read_text(encoding="utf-8")
    assert all(f"## {s}" in text for s in SECTIONS)
