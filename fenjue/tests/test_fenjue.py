"""功法清单的静态验体（焚决 F2，docs/design/fenjue/02-lianhua.md §6.1）：形状、经脉越界、入库四问、资产寻址、摘要。"""

import copy
import hashlib
from pathlib import Path

import pytest

from paoding_fenjue import shapes
from paoding_fenjue.contract import (
    SEATS,
    SLOTS,
    check,
    fire,
    fire_digest,
    fire_ids,
    form,
    gongfa,
    gongfa_digest,
    params,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("fid", fire_ids())
def test_every_fire_passes_the_static_checks(fid):
    assert check(fire(fid)) == []


@pytest.mark.parametrize("fid", fire_ids())
def test_assets_are_content_addressed(fid):
    for a in fire(fid)["assets"]:
        assert hashlib.sha256((ROOT / a["name"]).read_bytes()).hexdigest() == a["sha256"], a["name"]


def test_gongfa_fills_all_eight_slots_and_names_every_seat_with_a_form():
    g = gongfa()
    assert sorted(g["fires"]) == list(SLOTS) and all(g["fires"][s] for s in SLOTS)
    bound = sorted(s for r in g["fires"]["H1"] for s in fire(r.split("@")[0])["seats"])
    assert bound == ["bootstrap", "explore", "reason", "recall", "solve", "verify"]
    assert form("solve")["fire"] == "h1.solo" and form("explore")["fire"] == "h1.triad"
    assert form("verify")["fire"] == "h1.review"  # 复核会话（地图 Q34）：体质修炼 002 给了席位能交的事件，这里是形态
    with pytest.raises(KeyError):
        form("judge")  # 判官不是会话，没有形态
    js = [h["jie"] for h in g["history"]]  # 品阶史只追加：每一步升一阶（收下）或降一阶（散火，带 reverts）
    assert js[0] == 0 and js[-1] == g["jie"]
    for h0, h in zip(g["history"], g["history"][1:], strict=False):
        assert h["jie"] - h0["jie"] == (-1 if "reverts" in h else 1), h


def test_lineage_points_at_real_fires_and_dossiers():
    for fid in fire_ids():
        lin = fire(fid)["lineage"]
        assert all(src in fire_ids() for src in lin["from"]), fid
        if lin.get("dossier"):
            assert list((ROOT / "docs/design/fenjue/dossiers").glob(f"{lin['dossier']}-*.md")), fid
    # 散火目标：h6.activity 留着清单，不在功法里
    active = {r.split("@")[0] for rs in gongfa()["fires"].values() for r in rs}
    assert "h6.activity" not in active and "h6.activity-ledger" in active


def test_digest_moves_with_any_byte_of_any_fire(monkeypatch):
    before = gongfa()["digest"]
    assert before == gongfa_digest(gongfa())
    f = copy.deepcopy(fire("h2.sinan"))
    f["params"]["order"] = list(reversed(f["params"]["order"]))
    assert fire_digest(f) != fire_digest(fire("h2.sinan"))
    monkeypatch.setattr(shapes, "fire", lambda fid: f if fid == "h2.sinan" else fire(fid))
    assert gongfa_digest(gongfa()) != before


def test_overreach_is_caught():
    f = copy.deepcopy(fire("h1.triad"))
    f["params"]["forms"]["reason"]["tools"].append("deliver")  # reason 席位不能交付
    assert any("不能提交 deliver" in e for e in check(f))
    g = copy.deepcopy(fire("h1.solo"))
    g["ports"].remove("M1:deliver")
    assert any("没申请" in e for e in check(g))
    h = copy.deepcopy(fire("h1.solo"))
    h["seats"] = ["solve", "judge"]
    h["params"]["forms"]["judge"] = {"tools": []}
    assert any("新席位是体质修炼" in e for e in check(h))
    k = copy.deepcopy(fire("h3.kb"))
    k["organ"]["class"] = "守门官"
    assert any("守门官" in e for e in check(k))


def test_seat_table_is_the_kernel_one():
    assert "deliver" in SEATS["solve"] and "deliver" not in SEATS["reason"]


def test_params_names_the_fire_when_a_slot_holds_several():
    assert params("H2")["order"][-2:] == ["solve", "verify"]
    assert params("H6", "h6.activity-ledger")["ledger_roles"] == ["solve"]
    with pytest.raises(KeyError):
        params("H6")
