"""trial-b 第二次重跑暴露的缺陷：试算放行了空的提炼结果，归位收尾时崩（KeyError: 'fusion'），五次接力同处崩。

因果链：模型把提炼结果答成了别的形状（顶层是一步机制的键，不是九栏）→ 试算“只标不重写”放行 → 归位算难度时读
`masked.fusion.emergent` 崩 → 台账把错记在归位单元的回答上、让模型重写，于事无补。

这里守四件事：结构不过试算也重写，交回的错误写明期望的形状与收到的顶层键；重写后仍不过标“提炼不出”，不进归位，
预评估报告里写明；进归位的提炼结果九栏齐全（边界一处把住，逐个删栏去试）；程序出错而错不在解析这一步回答的代码里时，
不让模型重写。红线不变：内核与全部验证器零改动。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "engine_fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cases  # noqa: E402
from test_engine_kernel import ByKey, Host, brief_for  # noqa: E402
from test_engine_phase2 import _cand, _essence, _organ  # noqa: E402

from paoding_fenjue.engine import checks, cuiyi, handoff, kernel, pills, run, ruwei, schema, sections  # noqa: E402
from paoding_fenjue.engine.dan import Reply, ReplyDefect, reading  # noqa: E402
from paoding_fenjue.engine.run import report_g2  # noqa: E402

# trial-b 里模型实际交回的形状：一步机制的键摊在顶层，没有 masked
WRONG = {
    "step": 1,
    "trigger": "收到一次交付",
    "input": "交付与它引用的记录",
    "transform": "逐条比对",
    "output": "一份比对结果",
    "invariant": "不改原记录",
    "primitives": ["对照"],
}
WRONG_KEYS = "input、invariant、output、primitives、step、transform、trigger"
GOOD_PLACE = {
    "atoms": [{"atom": "report.claim_link", "params": {"show": "x"}, "emergent": True}],
    "fire": {"id": "h7.demo-y", "params": {}, "organ": _organ()},
}
GOOD_DESIGN = {
    "arms": {"B": "b", "A1": "a", "F": "f", "B1": "b1"},
    "readings": [{"dim": "演示率", "kind": "新生", "dir": "up", "gate": 1, "test": "t"}],
    "steps": [{"do": "改", "slot": "H7", "where": ["web/src/"], "tests": ["t"], "kernel_lines": 0, "accept": "过"}],
}


class Spy(ByKey):
    def __init__(self, path):
        super().__init__(path)
        self.seen = []

    def call(self, role, key, payload):
        self.seen.append((key, dict(payload)))
        return super().call(role, key, payload)


class Scripted:
    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def call(self, role, key, payload):
        self.seen.append((key, dict(payload)))
        r = self.replies.pop(0)
        return r if isinstance(r, Reply) else Reply(r, 10, 5)


def _dry(tmp_path, dan, **kw):
    brief = brief_for(tmp_path, fx="delta", intake=cases.intake("delta", "code", "dry_run"), **kw)
    host = Host(brief)
    return kernel.Session(tmp_path, brief, dan, host).run(), host


def _wrong(dan, cid: str, attempts: int) -> None:
    """把这个候选的前几次提炼回答换成 trial-b 的那种形状；录好的那一份顺延到后一次。"""
    good = copy.deepcopy(dan.e[f"cuiyi:{cid}:r1:main:1"])
    for i in range(1, attempts + 1):
        dan.e[f"cuiyi:{cid}:r1:main:{i}"] = {**good, "output": copy.deepcopy(WRONG)}
    if attempts < cuiyi.ATTEMPTS:
        dan.e[f"cuiyi:{cid}:r1:main:{attempts + 1}"] = good


def _load(tmp_path, name):
    return json.loads((tmp_path / "analysis" / name).read_text(encoding="utf-8"))


def _artifact(tmp_path, name):
    sha = _load(tmp_path, "run.json")["artifacts"][name]
    return _load(tmp_path, f"artifacts/{sha}.json")


# ---------------------------------------------------------------- 提炼：结构不过，试算也重写


def test_a_wrong_shape_is_sent_back_in_a_dry_run_with_the_expected_shape_and_the_received_keys(tmp_path):
    dan = Spy(cases.recording("delta", "code", ".dry"))
    _wrong(dan, "C2", 1)
    out, host = _dry(tmp_path, dan)
    assert out.status == "delivered" and host.delivered()[0]["outcome"] == "answered"
    errors = dict(dan.seen)["cuiyi:C2:r1:main:2"]["errors"]
    head = errors[0]
    assert "期望的形状" in head and "masked、field_refs、plain_summary" in head
    assert all(s in head for s in sections.SECTIONS) and len(sections.SECTIONS) == 9
    assert f"收到的顶层键：{WRONG_KEYS}" in head
    assert any(e.startswith("K1：") for e in errors)  # 检验的原话也带着
    # 改对之后照常进归位，报告里是一个正常的条目
    report = _artifact(tmp_path, "dry_run.json")
    assert [it["candidate"] for it in report["items"]] == ["C1", "C2", "C3"]
    assert _load(tmp_path, "engine.json").get("undistilled") == {}
    assert "提炼不出" not in (tmp_path / "analysis" / "answer.md").read_text(encoding="utf-8")


def test_still_wrong_after_the_rewrites_is_marked_undistilled_and_never_enters_placement(tmp_path):
    dan = Spy(cases.recording("delta", "code", ".dry"))
    _wrong(dan, "C2", cuiyi.ATTEMPTS)
    out, host = _dry(tmp_path, dan)
    (d,) = host.delivered()
    assert out.status == "delivered" and d["outcome"] == "answered"  # 不崩、不接力：别的候选照常评估
    asked = [k for k, _ in dan.seen]
    assert [k for k in asked if k.startswith("cuiyi:C2:")] == [f"cuiyi:C2:r1:main:{i}" for i in (1, 2, 3)]
    assert not any(k.startswith("ruwei:C2:") for k in asked)  # 不进归位：一次归位调用都不花
    why = _load(tmp_path, "engine.json")["undistilled"]["C2"]
    assert "缺" in why and "fusion" in why and WRONG_KEYS in why
    units = {u["id"]: u for u in _load(tmp_path, "run.json")["units"]}
    assert units["cuiyi:C2"]["state"] == "done" and "提炼不出" in units["cuiyi:C2"]["summary"]
    assert units["ruwei:C2"]["state"] == "failed" and "无法入位" in units["ruwei:C2"]["summary"]
    # 预评估报告里写明：条目里没有它（没有被评估），摘要、正文、待办都说了
    report = _artifact(tmp_path, "dry_run.json")
    assert [it["candidate"] for it in report["items"]] == ["C1", "C3"] and report["auto_picked"] == ["C1", "C2", "C3"]
    assert "3 个做法" in report["plain_summary"] and "2 个有望带来新能力" in report["plain_summary"]
    assert "1 个提炼不出、没有进入归位（C2）" in report["plain_summary"] and "检验未过" not in report["plain_summary"]
    # 结构化的那一栏与报告正文一致：trial-b 的形状是“一栏都没有”
    assert report["not_placed"] == [{"candidate": "C2", "kind": "empty", "why": why[:300]}]
    assert run.partition_problems(report) == []
    answer = (tmp_path / "analysis" / "answer.md").read_text(encoding="utf-8")
    assert "提炼不出，没有进入归位" in answer and f"- C2：{why}" in answer
    assert d["needs"][0].startswith("C2 提炼不出，没有进入归位")
    assert all(c["ok"] for c in _artifact(tmp_path, "dry_run.v"))  # 报告本身仍合 Schema、过校验
    # 榜上只记“这次走到提炼”，不给“预评估过”
    rows = _artifact(tmp_path, "bang_updates.json")["bang_updates"]
    mine = [json.dumps(r, ensure_ascii=False) for r in rows if "提炼不出" in json.dumps(r, ensure_ascii=False)]
    assert len(mine) == 1 and '"reached": "S4"' in mine[0] and "dry_run" not in mine[0].replace('"mode": "dry_run"', "")


# ---------------------------------------------------------------- 两类分开：九栏齐全而 K1 的其余规则没过，不算提炼不出


def _inconsistent(dan, cid: str) -> None:
    """trial-b-5 续跑里 C2 的真实形状：九栏齐全，机制里标了有守门性质的特征，冲突栏与拆分栏里却没有对应的内核项。
    三次都这样（重写没改过来）。"""
    good = copy.deepcopy(dan.e[f"cuiyi:{cid}:r1:main:1"])
    good["output"]["masked"]["mechanism"][0]["features"] = ["write_outside_reducer"]
    for i in range(1, cuiyi.ATTEMPTS + 1):
        dan.e[f"cuiyi:{cid}:r1:main:{i}"] = copy.deepcopy(good)


def test_complete_sections_that_fail_a_consistency_rule_still_enter_placement_and_are_flagged(tmp_path):
    dan = Spy(cases.recording("delta", "code", ".dry"))
    _inconsistent(dan, "C2")
    out, host = _dry(tmp_path, dan)
    (d,) = host.delivered()
    assert out.status == "delivered" and d["outcome"] == "answered"
    asked = [k for k, _ in dan.seen]
    assert [k for k in asked if k.startswith("cuiyi:C2:")] == [f"cuiyi:C2:r1:main:{i}" for i in (1, 2, 3)]  # 照样重写
    assert any(k.startswith("ruwei:C2:") for k in asked)  # 重写仍不过：九栏齐全，照常进归位
    ess = _artifact(tmp_path, "essence:C2")
    (k1,) = [c for c in ess["checks"] if c["id"] == "K1"]
    assert not k1["ok"] and sections.gaps(ess) == []
    assert "特征 write_outside_reducer 映到 T4，冲突栏里没有对应的体质冲突" in k1["detail"]
    assert "特征 write_outside_reducer 有守门性质，拆分栏里没有 T4" in k1["detail"]
    units = {u["id"]: u for u in _load(tmp_path, "run.json")["units"]}
    assert units["ruwei:C2"]["state"] == "done" and "未过" in units["cuiyi:C2"]["summary"]
    assert _load(tmp_path, "engine.json")["undistilled"] == {}
    # 预评估表里有这一行，标明检验未过与原因；别的行是“过”
    report = _artifact(tmp_path, "dry_run.json")
    assert [it["candidate"] for it in report["items"]] == ["C1", "C2", "C3"] and "not_placed" not in report
    assert "1 个检验未过但已做归位评估" in report["plain_summary"]
    answer = (tmp_path / "analysis" / "answer.md").read_text(encoding="utf-8")
    rows = {ln.split(" | ")[0].strip("| "): ln for ln in answer.splitlines() if ln.startswith("| C")}
    assert "检验未过：K1（特征 write_outside_reducer 映到 T4" in rows["C2"] and "拆分栏里没有 T4" in rows["C2"]
    assert rows["C1"].endswith("| 过 |") and rows["C3"].endswith("| 过 |")
    # “提炼不出”“结构仍不对”只用于结构类：这里哪儿都不出现
    said = answer + json.dumps(d["needs"], ensure_ascii=False) + report["plain_summary"]
    assert "提炼不出" not in said and "结构仍不对" not in said and "无法入位" not in said
    (need,) = [n for n in d["needs"] if n.startswith("C2 ")]
    assert need.startswith("C2 检验未过（只标不拦）：K1（特征 write_outside_reducer")
    assert all(c["ok"] for c in _artifact(tmp_path, "dry_run.v"))


def test_the_two_kinds_side_by_side_are_counted_and_worded_separately(tmp_path):
    """一次试算里两类都有（trial-b-5 续跑的样子）：C1 提炼结果是空的，C2 九栏齐全但一致性规则没过。"""
    dan = Spy(cases.recording("delta", "code", ".dry"))
    for i in range(1, cuiyi.ATTEMPTS + 1):  # 真实形状之一：masked 是空对象
        dan.e[f"cuiyi:C1:r1:main:{i}"] = {**dan.e["cuiyi:C1:r1:main:1"], "output": {"masked": {}}}
    _inconsistent(dan, "C2")
    out, host = _dry(tmp_path, dan)
    (d,) = host.delivered()
    report = _artifact(tmp_path, "dry_run.json")
    assert [it["candidate"] for it in report["items"]] == ["C2", "C3"]
    (row,) = report["not_placed"]
    assert row["candidate"] == "C1" and row["kind"] == "empty" and "缺" in row["why"] and "9 栏" in row["why"]
    s = report["plain_summary"]
    assert "自动取了优先级最高的 3 个做法" in s and "1 个检验未过但已做归位评估" in s
    assert "1 个提炼不出、没有进入归位（C1）" in s
    answer = (tmp_path / "analysis" / "answer.md").read_text(encoding="utf-8")
    group = answer[answer.index("**提炼不出，没有进入归位**") :]
    assert "重写之后结构仍不对" in group.splitlines()[0] and f"- C1：{row['why']}" in group and "- C2" not in group
    assert d["needs"][0].startswith("C1 提炼不出，没有进入归位") and d["needs"][1].startswith("C2 检验未过（只标不拦）")
    assert not any("C2" in n and "提炼不出" in n for n in d["needs"])
    assert run.partition_problems(report) == [] and all(c["ok"] for c in _artifact(tmp_path, "dry_run.v"))
    # 榜上：C2 评估过了，记“预评估过”；C1 只记走到提炼
    rows = [json.dumps(r, ensure_ascii=False) for r in _artifact(tmp_path, "bang_updates.json")["bang_updates"]]
    assert sum("提炼不出" in r for r in rows) == 1


def test_a_checkpoint_from_the_old_rule_lets_the_complete_one_into_placement_on_resume(tmp_path):
    """旧判据（K1 没过一律不进）留下的检查点：C2 九栏齐全，却记在 undistilled 里、归位单元是 failed。
    按新判据续做：以产物为准，C2 进归位，旧记录清掉。"""
    dan = Spy(cases.recording("delta", "code", ".dry"))
    _inconsistent(dan, "C2")
    eng = cases.engine("delta", "code", tmp_path, dan, ".dry")
    eng.start(cases.intake("delta", "code", "dry_run"))
    eng.x["undistilled"] = {"C2": "特征 write_outside_reducer 映到 T4，冲突栏里没有对应的体质冲突"}
    eng._mark("ruwei:C2", "S5", "failed", summary="C2：无法入位，提炼不出")
    eng.state["step"] = "S5"
    del eng.state["artifacts"]["dry_run.json"]
    dan.seen.clear()
    d = eng.resume()
    assert eng.x["undistilled"] == {} and eng._unit("ruwei:C2")["state"] == "done"
    assert [it["candidate"] for it in eng.get("dry_run.json")["items"]] == ["C1", "C2", "C3"]
    assert "提炼不出" not in d.answer and any(n.startswith("C2 检验未过") for n in d.needs)


@pytest.mark.parametrize(
    ("masked", "kind"),
    [
        ({}, "empty"),
        ("换一种说法", "empty"),  # masked 不是对象：一栏都没收下
        ({"statement": "只写了一句本质的话"}, "incomplete"),
    ],
)
def test_the_kind_of_not_placed_follows_what_was_received(tmp_path, masked, kind):
    dan = Spy(cases.recording("delta", "code", ".dry"))
    for i in range(1, cuiyi.ATTEMPTS + 1):
        dan.e[f"cuiyi:C3:r1:main:{i}"] = {**dan.e["cuiyi:C3:r1:main:1"], "output": {"masked": masked}}
    _dry(tmp_path, dan)
    report = _artifact(tmp_path, "dry_run.json")
    assert [(r["candidate"], r["kind"]) for r in report["not_placed"]] == [("C3", kind)]
    assert schema.errors(report, "dry-run") == []


# ---------------------------------------------------------------- dry_run.json 的结构化栏：向后兼容与自洽


def test_an_old_dry_run_without_the_new_field_is_still_valid_and_byte_identical(tmp_path):
    """没有“没进归位”的候选时不写这一栏：产物与加这一栏之前相同；旧文件照旧过 Schema 与自洽校验。"""
    dan = Spy(cases.recording("delta", "code", ".dry"))
    _dry(tmp_path, dan)
    report = _artifact(tmp_path, "dry_run.json")
    assert "not_placed" not in report and schema.errors(report, "dry-run") == []
    assert run.partition_problems(report) == []
    ctx = checks.Context(names=[], corpus=[], observations={}, license={})
    before = checks.v_dry_run(report, ctx)
    assert run.with_partition(before, report) == before  # 没有问题时一条都不动
    old = json.loads(
        (cases.ROOT / "docs/design/fenjue/engine/examples/case-d.dry-run.expected.json").read_text("utf-8")
    )
    old = old.get("expected", old)
    assert "not_placed" not in old and schema.errors(old, "dry-run") == [] and run.partition_problems(old) == []


def test_every_auto_picked_candidate_appears_exactly_once():
    def doc(items, out, picked=("C1", "C2", "C3")):
        r = {"auto_picked": list(picked), "items": [{"candidate": c} for c in items]}
        if out is not None:
            r["not_placed"] = [{"candidate": c, "kind": "empty", "why": "缺 9 栏"} for c in out]
        return r

    assert run.partition_problems(doc(["C1", "C3"], ["C2"])) == []
    assert run.partition_problems(doc(["C1", "C2", "C3"], None)) == []
    (twice,) = run.partition_problems(doc(["C1", "C2", "C3"], ["C2"]))
    assert "C2" in twice and "2 次" in twice
    (lost,) = run.partition_problems(doc(["C1", "C3"], None))
    assert "C2" in lost and "既不在" in lost
    (stray,) = run.partition_problems(doc(["C1", "C2", "C3"], ["C9"]))
    assert "C9" in stray and "不是自动取的候选" in stray
    # 并进 V11：原有的问题留着，新问题接在后面，别的条目不动
    vres = [{"id": "V2", "ok": True}, {"id": "V11", "ok": False, "detail": "C7 不在自动取的候选里"}]
    got = run.with_partition(vres, doc(["C1", "C3"], None))
    assert got[0] == {"id": "V2", "ok": True} and not got[1]["ok"]
    assert got[1]["detail"].startswith("C7 不在自动取的候选里；") and "C2" in got[1]["detail"]
    assert vres[1]["detail"] == "C7 不在自动取的候选里"  # 不改传进来的那份


def test_the_schema_accepts_the_new_field_and_rejects_a_malformed_one(tmp_path):
    dan = Spy(cases.recording("delta", "code", ".dry"))
    _wrong(dan, "C2", cuiyi.ATTEMPTS)
    _dry(tmp_path, dan)
    report = _artifact(tmp_path, "dry_run.json")
    assert schema.errors(report, "dry-run") == []
    for bad in (
        {"candidate": "C2", "kind": "别的", "why": "x"},
        {"candidate": "C2", "kind": "empty"},
        {"candidate": "二"},
    ):
        assert schema.errors({**report, "not_placed": [bad]}, "dry-run")
    assert schema.errors({**report, "not_placed": [{**report["not_placed"][0], "extra": 1}]}, "dry-run")


def test_a_cut_off_reply_is_not_reported_as_missing_sections(tmp_path):
    dan = Spy(cases.recording("delta", "code", ".dry"))
    good = copy.deepcopy(dan.e["cuiyi:C2:r1:main:1"])
    cap = pills.MAX_TOKENS["cuiyi/main/v1"]
    dan.e["cuiyi:C2:r1:main:1"] = {**good, "output": None, "tokens_out": cap}
    dan.e["cuiyi:C2:r1:main:2"] = good
    out, _ = _dry(tmp_path, dan)
    assert out.status == "delivered"
    (err,) = dict(dan.seen)["cuiyi:C2:r1:main:2"]["errors"]
    assert "截断" in err and str(cap) in err and "缺 statement" not in err and "期望的形状" not in err
    assert _load(tmp_path, "engine.json").get("undistilled") == {}


def _distill(*replies, dry=True):
    cand = {**_cand(), "gaps": [], "provenance": {"observations": [], "snapshots": []}}
    ctx = checks.Context(names=[], corpus=[], observations={}, license={})
    dan = Scripted(*replies)
    return cuiyi.distill(dan, cand, {}, ctx, dry=dry), dan


def test_a_refusal_is_not_retried_and_the_reason_says_so_not_missing_sections():
    res, dan = _distill(Reply(None, 9, 0, "refusal"))
    assert len(dan.seen) == 1 and not res.passed
    assert sections.gaps(res.essence) and "没有解析出 JSON 对象" in res.reason


def test_a_section_of_the_wrong_type_is_dropped_at_the_door_and_named_in_the_error():
    """`fusion` 写成一句话：以前检验（K5）自己就崩在 `'str' object has no attribute 'get'`。"""
    m = _essence()["masked"]
    bad = {"masked": {**m, "fusion": "合起来更好", "mechanism": [{"trigger": "t"}]}, "plain_summary": "一段话"}
    res, dan = _distill(bad, bad, bad)
    assert len(dan.seen) == cuiyi.ATTEMPTS  # K1 不过：试算也重写到用完
    errors = dan.seen[1][1]["errors"]
    assert "期望的形状" in errors[0] and "还缺：mechanism、fusion" in errors[0]
    assert any("fusion 一栏的形状不对" in e and "/fusion: 应为 object" in e for e in errors)
    assert any("mechanism 一栏的形状不对" in e and "/mechanism/0: 缺 step" in e for e in errors)
    assert "fusion" not in res.essence["masked"] and "statement" in res.essence["masked"]  # 形状对的栏照收
    assert "缺 mechanism、fusion 2 栏" in res.reason


def test_k1_failures_that_are_not_about_the_sections_keep_the_usual_error_without_the_shape_lecture():
    m = {**_essence()["masked"], "statement": "演示一个机制"}
    long = {"masked": {**m, "statement": "长" * 81}, "plain_summary": "一段话"}
    res, dan = _distill(long, {"masked": m, "plain_summary": "一段话"})
    assert [c.get("detail") for c in res.essence["checks"] if c["id"] == "K1"] == [None]
    errors = dan.seen[1][1]["errors"]
    assert any(e.startswith("K1：") and "太长" in e for e in errors) and not any("期望的形状" in e for e in errors)
    assert res.reason == "" and not sections.gaps(res.essence)


# ---------------------------------------------------------------- 边界：进归位的提炼结果九栏齐全


def test_regression_an_essence_without_fusion_is_marked_unplaceable_not_a_crash(tmp_path, monkeypatch):
    """cz 点名的回归：提炼结果缺 fusion → 入位不崩、候选被标为无法入位。提炼这一步自己的把关整个绕开
    （等于旧检查点里留着的那份空结果、或将来哪条路又放行了一份），只看边界。"""
    real = cuiyi.distill

    def leaky(dan, cand, obs, ctx, **kw):
        res = real(dan, cand, obs, ctx, **kw)
        if cand["id"] == "C1":
            del res.essence["masked"]["fusion"]
            res.reason = ""
        return res

    monkeypatch.setattr(cuiyi, "distill", leaky)
    dan = Spy(cases.recording("delta", "code", ".dry"))
    out, host = _dry(tmp_path, dan)
    (d,) = host.delivered()
    assert out.status == "delivered" and d["outcome"] == "answered"
    assert (
        not (tmp_path / "analysis" / "defects.log").exists() and not (tmp_path / "analysis" / "attempts.json").exists()
    )
    assert not any(k.startswith("ruwei:C1:") for k, _ in dan.seen)
    unit = next(u for u in _load(tmp_path, "run.json")["units"] if u["id"] == "ruwei:C1")
    assert unit["state"] == "failed" and "无法入位" in unit["summary"] and "fusion" in unit["summary"]
    assert "缺 fusion 1 栏" in _load(tmp_path, "engine.json")["undistilled"]["C1"]
    assert any("C1 提炼不出" in n and "fusion" in n for n in d["needs"])


def test_placement_refuses_an_incomplete_essence_before_asking_the_model():
    ess = _essence()
    del ess["masked"]["fusion"]
    dan = Scripted()
    with pytest.raises(ruwei.Unplaceable) as e:
        ruwei.place(dan, _cand(), ess, full=False)
    assert dan.seen == [] and e.value.gaps == ["/: 缺 fusion"] and "无法入位" in str(e.value)


def _variants(node, path=()):
    """逐个位置做两种破坏：删掉这个键；把这个值换成另一种类型。"""
    if isinstance(node, dict):
        for k, v in node.items():
            yield (*path, k), "del"
            yield (*path, k), "swap"
            yield from _variants(v, (*path, k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield (*path, i), "swap"
            yield from _variants(v, (*path, i))


def _broken(masked, path, how):
    m = copy.deepcopy(masked)
    node = m
    for p in path[:-1]:
        node = node[p]
    if how == "del":
        del node[path[-1]]
    else:
        node[path[-1]] = 7 if isinstance(node[path[-1]], (str, list, dict)) else "七"
    return m


def _full_essence():
    ess = _essence(conflicts=[{"with": "T2", "kind": "kernel", "statement": "碰到计量", "resolution": "fused_away"}])
    m = ess["masked"]
    m["mechanism"][0].update(invariant="不改原记录")
    m["premises"][0]["replaced_by"] = "用事件账"
    m["costs"][0]["kernel"] = "T3"
    m["overlaps"] = [{"fire": "h7.report@1", "dims": ["d1"], "relation": "partial", "note": "一部分"}]
    m["conflicts"][0].update(how="设计里化解", features=["new_egress"])
    m["fusion"]["outcome_cap"] = "huolian"
    m["fusion"]["emergent"][0]["how"] = "跑测试"
    m["split"] = [{"part": "新的对外连接规则", "kernel": "T2", "to": "待立项"}]
    ctx = checks.Context(names=[], corpus=[], observations={}, license={})
    ess.update(v=1, provenance={"observations": [], "snapshots": []}, plain_summary="一段话")
    ess["drafts"] = {"n": 1, "chosen": "main", "agreement": 0}
    ess["checks"] = checks.k_checks(ess, ctx, None)
    return ess, ctx


def _downstream(ess):
    """cz 列的七处读取（ruwei 216/285/617/1147、handoff 39/115、run 1140）各走一遍。"""
    res = ruwei.place(Scripted(*[GOOD_PLACE] * 3, *[GOOD_DESIGN] * 3), _cand(), ess, full=True)  # 216、285、617
    ruwei.likely_outcome(ess, res.placement)  # 1147
    handoff.render_cuiyi(ess)  # 39
    _bang(ess)  # 115
    report_g2([ess])  # 1140


def _bang(ess):
    cand = {
        "id": "C1",
        "title": "演示",
        "slot": "H7",
        "gaps": [],
        "seed": {"shihuo": {"phenomenon": "识别时看到的现象"}},
        **{k: 1 for k in ("value", "confidence", "difficulty", "risk", "priority")},
    }
    doc = {
        "basis": {"snapshots": [{"license": {"status": "ok"}, "form": "code"}], "gongfa_digest": "x"},
        "candidates": [cand],
    }
    fates = {"C1": ("S4", "", "提炼不出")}
    (row,) = handoff.bang_updates(
        [], doc, run="r", mode="dry_run", date="2026-11-25", fates=fates, essences={"C1": ess}
    )
    return row["entry"]


def test_every_way_of_breaking_the_nine_sections_is_either_caught_at_the_boundary_or_harmless_downstream():
    """守边界的那条：对一份齐全的提炼结果逐个位置删键、换类型。每个变体要么被 `sections.gaps` 认出来
    （于是进不了归位），要么七处读取都读得动。哪天 Schema 加了下游要读的栏、或下游多读了一个可选栏，这里会红。"""
    ess, ctx = _full_essence()
    assert sections.gaps(ess) == []
    _downstream(ess)  # 齐全的那份本身读得动
    caught = passed = 0
    for path, how in _variants(ess["masked"]):
        v = {**ess, "masked": _broken(ess["masked"], path, how)}
        where = f"{how} /{'/'.join(map(str, path))}"
        if sections.gaps(v):
            caught += 1
            with pytest.raises(ruwei.Unplaceable):
                ruwei.place(Scripted(), _cand(), v, full=False)
            assert "提炼不出" in report_g2([v]), where  # 确认点的报告照样出得来，照实写缺什么
            assert _bang(v)["essence"] == "识别时看到的现象" and "fusion" not in _bang(v), where  # 榜上不写半截内容
        else:
            passed += 1
            try:
                _downstream(v)
            except ruwei.Unplaceable:
                raise
            except Exception as e:  # noqa: BLE001  要的就是“哪个变体读不动”
                pytest.fail(f"{where} 过了边界，下游却读不动：{type(e).__name__}: {e}")
        # 进门那一侧：同一个变体当作模型的回答，收下之后检验与校验都读得动（以前 K5、K7 自己会崩）
        body, _ = cuiyi._as_essence({**_cand(), "provenance": ess["provenance"]}, {"masked": v["masked"]})
        body["drafts"], body["checks"] = ess["drafts"], checks.k_checks(body, ctx, None)
        checks.v_essence(body, ctx, ["C1"])
        assert sections.structural(body["masked"]) == [e for e in sections.structural(body["masked"]) if "/: 缺 " in e]
    for s in sections.SECTIONS:  # 九栏逐栏：删掉必被认出
        assert sections.gaps({**ess, "masked": _broken(ess["masked"], (s,), "del")}) == [f"/: 缺 {s}"]
    assert caught > 60 and passed > 5  # 两边都真的走到了


def test_a_handoff_with_an_incomplete_essence_is_reported_not_crashed_on_import(tmp_path):
    from paoding_fenjue.engine.dan import Recorded

    eng = cases.engine("alpha", "code", tmp_path, Recorded.load(cases.recording("alpha", "code")))
    eng.start(cases.intake("alpha", "code"))
    eng.follow_up(cases.g1_block(eng.get("candidates.json")))
    ids = list(eng.x["picked"])
    eng.follow_up(cases.g2_block(ids))
    eng.follow_up(cases.g3_block(ids, "alpha"))
    h = eng.get("handoff.json")
    assert all(c["ok"] for c in handoff.v_handoff(h))
    del h["items"][0]["essence"]["masked"]["fusion"]  # 交接包在外面被改坏了
    res = {c["id"]: c for c in handoff.v_handoff(h)}
    assert not res["V11"]["ok"] and "火意缺栏目" in res["V11"]["detail"] and "fusion" in res["V11"]["detail"]


# ---------------------------------------------------------------- 正式模式：确认点上拦住


def test_formal_an_incomplete_essence_is_shown_as_undistilled_and_cannot_be_confirmed(tmp_path):
    dan = Spy(cases.recording("delta", "code"))
    bad = {**dan.e["cuiyi:C3:r1:main:1"], "output": copy.deepcopy(WRONG)}
    for key in ("main:1", "main:2", "main:3", "extra1", "extra2"):
        dan.e[f"cuiyi:C3:r1:{key}"] = bad
    eng = cases.engine("delta", "code", tmp_path, dan)
    eng.start(cases.intake("delta", "code"))
    d = eng.follow_up(cases.g1_block(eng.get("candidates.json")))
    assert d.gate == "G2" and not d.passed
    assert "## C3：提炼不出" in d.answer and "缺" in d.answer and "## C1：" in d.answer
    assert any(n.startswith("C3 提炼不出") and "退回重做或放弃" in n for n in d.needs)
    assert "cuiyi:C3:r1:blind" not in [k for k, _ in dan.seen]  # 没有可盲审的内容，不花这一次
    assert "C3" in eng.x["undistilled"]
    d = eng.follow_up(cases.g2_block(["C1", "C2", "C3"]))
    assert eng.state["step"] == "G2" and any("C3 提炼不出" in n and "不能确认" in n for n in d.needs)
    d = eng.follow_up("【决定 v1】闸点 2\n确认：C1，C2\n退回：无\n放弃：C3")
    assert eng.state["step"] == "G3" and "C3" not in eng.x["undistilled"]
    assert not any(k.startswith("ruwei:C3:") for k, _ in dan.seen)


def test_formal_a_stale_checkpoint_with_an_incomplete_essence_goes_back_to_the_confirmation(tmp_path):
    dan = Spy(cases.recording("delta", "code"))
    eng = cases.engine("delta", "code", tmp_path, dan)
    eng.start(cases.intake("delta", "code"))
    eng.follow_up(cases.g1_block(eng.get("candidates.json")))
    ess = eng.get("essence:C2")
    del ess["masked"]["fusion"]
    eng.put("essence:C2", ess)  # 旧版本留下的检查点：确认点没拦，直接到了归位
    eng.x["confirmed"] = ["C1", "C2", "C3"]
    d = eng._ruwei()
    assert eng.state["step"] == "G2" and d.gate == "G2" and eng.x["confirmed"] == []
    assert d.needs[0].startswith("C2 提炼不出") and "进不了归位" in d.needs[0]
    assert not any(k.startswith("ruwei:") for k, _ in dan.seen)


# ---------------------------------------------------------------- 台账：错不在解析这一步回答的代码里，不让模型重写


def test_a_defect_outside_the_reply_handling_is_not_blamed_on_the_model_and_not_asked_again(tmp_path, monkeypatch):
    """trial-b 的那一次：归位的回答没问题，崩在收尾读上一步的产物。以前台账写“多半是输出的形状不对，按输出形状重写”，
    五次接力每次重问 1–3 次归位。现在：不留给模型的话，不重问（备忘命中），同一处同样的错第二次出现就不再试。"""

    def boom(*a, **kw):
        raise KeyError("fusion")

    monkeypatch.setattr(ruwei, "finish", boom)  # 试算路径上 finish 在“解析回答”的圈外
    rec = cases.recording("delta", "code", ".dry")
    out1, host1 = _dry(tmp_path, Spy(rec), relays_left=4)
    assert out1.status == "relay" and host1.delivered() == [] and "带着原因" not in out1.detail
    (row,) = _load(tmp_path, "attempts.json")["rows"]
    assert row["kind"] == "defect" and row["unit"] == "ruwei:C1" and "note" not in row
    assert "KeyError: 'fusion'" in row["reason"] and "不在解析这一步模型回答的代码里" in row["reason"]
    assert "没有让模型重写" in row["reason"] and "形状不对" not in row["reason"]

    spy = Spy(rec)
    out2, host2 = _dry(tmp_path, spy, relays_left=3)
    assert spy.seen == []  # 一次模型都没重问：输入没变，问过的全取备忘
    (d,) = host2.delivered()  # 还有 3 次接力也不再试：同一处同样的错，再试是原样重演
    assert out2.status == "delivered" and d["outcome"] == "blocked"
    assert "共尝试 2 次" in d["needs"][0] and "不再接着试" in d["needs"][0] and "继续" in d["needs"][0]
    assert len(_load(tmp_path, "attempts.json")["rows"]) == 2


def test_a_defect_inside_the_reply_handling_still_carries_a_note_to_that_unit(tmp_path, monkeypatch):
    real, left = ruwei.precheck, {"n": 1}

    def flaky(*a, **kw):
        if left["n"]:
            left["n"] -= 1
            raise AttributeError("'str' object has no attribute 'get'")
        return real(*a, **kw)

    monkeypatch.setattr(ruwei, "precheck", flaky)
    rec = cases.recording("delta", "code", ".dry")
    out1, _ = _dry(tmp_path, Spy(rec), relays_left=4)
    (row,) = _load(tmp_path, "attempts.json")["rows"]
    assert out1.status == "relay" and "带着原因" in out1.detail
    assert "处理模型的回答（ruwei:C1:r1:place:1）时程序出错" in row["reason"] and "AttributeError" in row["reason"]
    assert "形状不对" in row["note"] and "AttributeError" in row["note"]
    spy = Spy(rec)
    out2, _ = _dry(tmp_path, spy, relays_left=3)
    carried = [k for k, p in spy.seen if "prior_failures" in p]
    assert out2.status == "delivered" and carried and all(k.startswith("ruwei:C1:") for k in carried)


def test_different_defects_outside_the_reply_handling_keep_relaying(tmp_path, monkeypatch):
    n = {"i": 0}

    def boom(*a, **kw):
        n["i"] += 1
        raise RuntimeError(f"第 {n['i']} 种错")

    monkeypatch.setattr(ruwei, "finish", boom)
    rec = cases.recording("delta", "code", ".dry")
    assert _dry(tmp_path, Spy(rec), relays_left=4)[0].status == "relay"
    assert _dry(tmp_path, Spy(rec), relays_left=3)[0].status == "relay"  # 不是同样的错：照常接力


def test_reading_wraps_only_what_is_inside_it():
    with pytest.raises(ReplyDefect) as e, reading("ruwei:C1:r1:place:2"):
        {}["fusion"]
    assert e.value.key == "ruwei:C1:r1:place:2" and str(e.value) == "KeyError: 'fusion'"
    assert isinstance(e.value.__cause__, KeyError)
    with pytest.raises(ReplyDefect) as e2, reading("outer"), reading("inner"):
        raise ValueError("x")
    assert e2.value.key == "inner"  # 嵌套时认最里面那一次
