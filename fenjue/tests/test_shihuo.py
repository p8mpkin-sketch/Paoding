"""试火计划与试火记录（现行设计 4.5、4.6、4.8、6.1；03 §4、§5），以及定阶处的核对与出身的用处。

按档号划线（lianhua.SHIHUO_FROM）：这里的炼档都在划线之后。
"""

from __future__ import annotations

import copy

import pytest

from paoding_fenjue import lianhua as lh
from paoding_fenjue import shapes, shihuo

TODAY = "2026-11-28"
TARGET = "留出题上的过线数"
ARMS = ("B", "B1", "A1", "F", "A0")
QUESTIONS, MEDIAN_COST, MEDIAN_SECONDS, MAX_SECONDS = 20, 100, 600, 900


def placed(no: str = "900", *, parity: str | None = "equal", target: bool = True, origin: str | None = None) -> dict:
    """走到入位的一份炼档：五条臂，一个吸收目标维、一个新生维、一个本火维、一个共有维。"""
    f = copy.deepcopy(shapes.fire("h7.result"))
    f.update(id="h7.result-first", ver=1, lineage={"dossier": no, "from": ["h7.result"]})
    shihuo_ = {"source": "s", "phenomenon": "p", "gap": "g", "is_fire": "是"}
    d = lh.new(no, "x", "演示", TODAY, shihuo_, origin=origin)
    d = lh.cuiyi(d, dict.fromkeys(lh.CUIYI[:7], "写了"))
    arms = {"B": "本火", "B1": "本火再跑一遍", "A1": "异火单炼", "F": "合火", "A0": "原形"}
    readings = [
        {"dim": TARGET, "kind": "异火", "dir": "up", **({"target": True, "n": QUESTIONS * 2} if target else {})},
        {"dim": "新性质", "kind": "新生", "dir": "up", "gate": 1},
        {"dim": "凭据泄漏数", "kind": "本火", "dir": "down"},
        {"dim": "每题次花费", "kind": "共有", "dir": "down"},
    ]
    why = {"class": parity, **({"reason": "写明的原因"} if parity != "equal" else {})} if parity else None
    return lh.ruwei(d, f, "h7.result", arms, readings, parity=why)


def plan(no: str = "900") -> dict:
    arm = {"model": "m-main", "version": "2026-11", "endpoint": "proxy", "sampling": {"temperature": 0},
           "meter": "ledger", "price_table": "t@1"}  # fmt: skip
    return {
        "dossier": no,
        "arms": {a: {"what": a, **copy.deepcopy(arm)} for a in ARMS},
        "judge": {
            "model": "m-judge",
            "version": "2026-10",
            "prompts": "p@1",
            "sample": {"per_sub": 2, "max": 8},
            "seconds_per_item": MEDIAN_SECONDS,
        },  # fmt: skip
        "questions": {"set": "S1", "digest": "q" * 64, "source": "手出", "count": QUESTIONS, "runs": 2},
        "trial_segment": {
            "batch": "T0-1",
            "median_cost_usd_milli": MEDIAN_COST,
            "median_seconds": MEDIAN_SECONDS,
            "max_seconds": MAX_SECONDS,
        },
        "watchdog_seconds": 3 * MAX_SECONDS,
        "caps": shihuo.caps_from(MEDIAN_COST, QUESTIONS, len(ARMS)),
        "seed": "s1",
    }


def record(p: dict, *, f: int = 30, a0: int = 30, new: float = 1, leaks: int = 0, cost: int = 100, **over) -> dict:
    """一份跑完的判定记录。每条臂 40 个题次，按序号前 n 个过：本火、同火对照、异火单炼都是 30，合火 f，原形 a0。"""
    passed = {"B": 30, "B1": 30, "A1": 30, "F": f, "A0": a0}
    items = []
    for arm in p["arms"]:
        for i in range(QUESTIONS * 2):
            items.append({"arm": arm, "q": f"q{i // 2:02d}", "run": i % 2 + 1, "passed": i < passed[arm],
                          "cost_usd_milli": cost, "task": f"{arm}-{i}", "log_head": f"h{i}"})  # fmt: skip
    r = {
        "plan_hash": shihuo.digest(p),
        "purpose": "判定",
        "status": "complete",
        "arms": {a: {"digest": f"d-{a}", "model": v["model"], "version": v["version"]} for a, v in p["arms"].items()},
        "questions": {"set": p["questions"]["set"], "digest": p["questions"]["digest"]},
        "judge": {k: p["judge"][k] for k in ("model", "version", "prompts")},
        "items": items,
        "readings": {
            "新性质": {"B": 0, "A1": 0, "F": new},
            "凭据泄漏数": {"B": 0, "A1": 0, "F": leaks},
            "每题次花费": {"B": 100, "B1": 104, "A1": 100, "F": 100},
        },
        "cost": {"total_usd_milli": sum(it["cost_usd_milli"] for it in items)},
    }
    return {**r, **over}


def trialed(no: str = "900", p: dict | None = None, **kw) -> tuple[dict, dict]:
    p = p or plan(no)
    d = lh.approve_design(lh.dengji(placed(no, **kw), p), "cz", TODAY)
    d = lh.yanti(d, 0, [], {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}, "abc1234", measure_lines=0)
    return d, p


def refuses(fn, *words: str) -> None:
    with pytest.raises(lh.StepError) as e:
        fn()
    assert all(w in str(e.value) for w in words), str(e.value)


# ---------------------------------------------------------------- 试火计划：登记时的拒绝


@pytest.mark.parametrize(
    ("path", "words"),
    [
        (("arms", "B", "model"), ("B 臂的模型栏空着",)),
        (("arms", "A0", "version"), ("A0 臂的模型栏空着",)),
        (("judge", "model"), ("盲判的模型栏空着",)),
        (("judge", "version"), ("盲判的模型栏空着",)),
    ],
)
def test_a_plan_with_an_empty_model_column_is_refused(path, words):
    p = plan()
    node = p
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = ""
    refuses(lambda: lh.dengji(placed(), p), *words)


@pytest.mark.parametrize("arm", ARMS)
def test_a_judge_on_the_same_model_as_any_arm_is_refused(arm):
    p = plan()
    p["arms"][arm]["model"] = p["judge"]["model"]
    refuses(lambda: lh.dengji(placed(parity="theirs"), p), f"盲判的模型与 {arm} 臂相同")


def test_arms_on_different_models_need_a_declared_inequality():
    p = plan()
    p["arms"]["A0"] |= {"model": "m-other"}
    refuses(lambda: lh.dengji(placed(parity="equal"), p), "模型名与版本不全相同", "拒跑")
    p2 = plan()
    p2["arms"]["A0"] |= {"version": "2026-12"}  # 同名不同版本也算不同
    refuses(lambda: lh.dengji(placed(parity="equal"), p2), "拒跑")
    assert lh.dengji(placed(parity="theirs"), p)["trial_plan_hash"] == shihuo.digest(p)


def test_caps_and_the_judging_time_limit_follow_the_rule_and_are_not_typed_in():
    assert plan()["caps"] == {"per_item_usd_milli": 300, "total_usd_milli": 300 * QUESTIONS * 5 * 2}
    p = plan()
    p["caps"]["per_item_usd_milli"] += 1
    refuses(lambda: lh.dengji(placed(), p), "花费上限不是按规矩算出的")
    p = plan()
    p["judge"]["seconds_per_item"] = 900
    refuses(lambda: lh.dengji(placed(), p), "每题次的盲判时限", "中位数")
    p["judge"]["limit_given"] = {"by": "cz", "why": "自检计时后每个候选都超时，按实测另给"}
    assert lh.dengji(placed(), p)["trial_plan"]["judge"]["seconds_per_item"] == 900
    p = plan()
    del p["judge"]["seconds_per_item"]
    refuses(lambda: lh.dengji(placed(), p), "每题次的盲判时限要写进计划")


def test_the_watchdog_limit_is_three_times_the_longest_baseline_run_and_is_not_typed_in():
    """看门狗的时限进计划的形状（P6）：试跑段里本火最长一遍用时的 3 倍，按规矩算出，不手填。"""
    good = plan()
    assert good["watchdog_seconds"] == shihuo.watchdog_from(MAX_SECONDS) == 3 * MAX_SECONDS
    done = lh.dengji(placed(), good)
    assert f"看门狗的时限：{3 * MAX_SECONDS} 秒" in lh.render(
        done
    ) and f"最长一遍用时（{MAX_SECONDS} 秒）" in lh.render(done)

    def changed(**kw):
        p = plan()
        for k, v in kw.items():
            if k == "watchdog_seconds":
                p[k] = v
            else:
                p["trial_segment"][k] = v
        return p

    for typed in (3 * MAX_SECONDS + 1, 3600, MAX_SECONDS, 0, None, "2700"):
        refuses(lambda t=typed: lh.dengji(placed(), changed(watchdog_seconds=t)), "看门狗的时限不是按规矩算出的")
    for missing in (None, 0, -1, True, "900"):
        refuses(lambda m=missing: lh.dengji(placed(), changed(max_seconds=m)), "本火最长一遍的用时")
    short = changed(max_seconds=MEDIAN_SECONDS - 1, watchdog_seconds=3 * (MEDIAN_SECONDS - 1))
    refuses(lambda: lh.dengji(placed(), short), "比中位数还短")
    p = plan()
    del p["watchdog_seconds"]
    refuses(lambda: lh.dengji(placed(), p), "试火计划的栏不对", "watchdog_seconds")
    refuses(lambda: lh.dengji(placed(), changed(watchdog_s=2700)), "试跑段一栏多了")


def test_the_plan_names_the_arms_placed_and_the_sample_size_registered():
    p = plan()
    del p["arms"]["A1"]
    refuses(lambda: lh.dengji(placed(), p), "与入位时登记的臂")
    p = plan()
    p["questions"]["count"] = 10
    p["caps"] = shihuo.caps_from(MEDIAN_COST, 10, 5)
    refuses(lambda: lh.dengji(placed(), p), "样本量 40 不等于题数乘次数 20")
    refuses(lambda: lh.dengji(placed(target=False), plan()), "没有登记吸收目标维")
    refuses(lambda: lh.dengji(placed(parity=None), plan()), "没有登记对等声明")


def test_a_registered_plan_cannot_change_and_the_design_ruling_keeps_its_hash():
    p = plan()
    d = lh.dengji(placed(), p)
    assert lh.dengji(d, copy.deepcopy(p)) == d  # 原样再登记一次不算改
    changed = copy.deepcopy(p)
    changed["seed"] = "s2"
    refuses(lambda: lh.dengji(d, changed), "已经登记，不能改")
    approved = lh.approve_design(d, "cz", TODAY)
    assert approved["design_verdict"]["plan_hash"] == shihuo.digest(p) == approved["trial_plan_hash"]
    refuses(lambda: lh.dengji(approved, changed), "plan")  # 设计裁决之后这一步已经过去


def test_no_design_ruling_without_a_plan():
    d = placed()
    assert lh.next_step(d) == "plan"
    refuses(lambda: lh.approve_design(d, "cz", TODAY), "还没有登记试火计划")


def test_the_sampling_seed_comes_from_the_plan_hash_and_the_question():
    h = shihuo.digest(plan())
    assert shihuo.seed_for(h, "q01", 1) == shihuo.seed_for(h, "q01", 1)
    assert len({shihuo.seed_for(h, "q01", 1), shihuo.seed_for(h, "q01", 2), shihuo.seed_for(h, "q02", 1)}) == 3
    other = plan()
    other["seed"] = "s2"
    assert shihuo.seed_for(shihuo.digest(other), "q01", 1) != shihuo.seed_for(h, "q01", 1)


# ---------------------------------------------------------------- 试火记录：读数只从记录读入


def test_readings_come_only_from_the_record_and_the_hand_entry_is_closed():
    d, p = trialed()
    refuses(lambda: lh.ronghuo(d, {"新性质": {"F": 1}}, 2, record=record(p)), "手填的入口已经关掉")
    refuses(lambda: lh.ronghuo(d, {}, 2), "要给试火记录")
    r = record(p)
    out = lh.ronghuo(d, {}, 2, record=r)
    assert out["outcome_proposed"] == "huolian" and out["yuanxing_gate"]["state"] == "passed"
    assert out["trial_record"] == {
        "hash": shihuo.digest(r),
        "plan_hash": shihuo.digest(p),
        "cost_usd_milli": 100 * 200,
        "items": 200,
    }
    assert "读数出自试火记录" in lh.render(out) and "试火计划（登记之后不能改" in lh.render(out)


def test_structural_readings_still_come_from_their_tests_and_nothing_else_is_typed_in():
    """结构读数由确定性测试给出（03 §5）：登记了出处测试的那一维由命令跑测试得出，不在记录里；别的维不许填。"""
    p = plan()
    d = placed()
    d["readings"][1]["test"] = "tests/x.py::test_new_property"
    d = lh.approve_design(lh.dengji(d, p), "cz", TODAY)
    d = lh.yanti(d, 0, [], {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}, "abc1234", measure_lines=0)
    r = record(p)
    refuses(lambda: lh.ronghuo(d, {"新性质": {"F": 1}}, 2, record=r), "既有测试跑出的结构读数，记录里又报了一份")
    del r["readings"]["新性质"]
    refuses(lambda: lh.ronghuo(d, {"凭据泄漏数": {"F": 0}}, 2, record=r), "手填的入口已经关掉")
    out = lh.ronghuo(d, {"新性质": {"B": 0, "A1": 0, "F": 1}}, 2, record=r)
    assert out["outcome_proposed"] == "huolian"
    g = shapes._read("gongfa.json")
    assert lh.jue(out, g, "cz", TODAY, "huolian", [], record=r)[0]["verdict"]["system"] == "huolian"


def test_the_four_cells_are_recounted_from_the_item_runs():
    d, p = trialed()
    r = record(p, f=36, a0=38)
    assert shihuo.pairs(r, p)["F:A0"] == {"both": 36, "first": 0, "second": 2, "neither": 2}
    assert shihuo.pairs(r, p)["F:B"] == {"both": 30, "first": 6, "second": 0, "neither": 4}
    out = lh.ronghuo(d, {}, 2, record=r)
    assert out["outcome_proposed"] == "buji" and out["yuanxing_gate"]["state"] == "failed"
    # 记录自己不能替目标维报数：四格只由逐题次的结果算
    stuffed = record(p)
    stuffed["readings"][TARGET] = {"F": 40, "B": 0}
    stuffed["cost"] = dict(stuffed["cost"])
    refuses(lambda: lh.ronghuo(trialed()[0], {}, 2, record=stuffed), "目标维不收各臂自己报的数")


def test_a_run_over_the_per_item_cap_counts_as_not_passed():
    d, p = trialed()
    r = record(p)
    for it in r["items"]:
        if it["arm"] == "F" and it["q"] in ("q00", "q01", "q02"):
            it["cost_usd_milli"] = p["caps"]["per_item_usd_milli"] + 1
    r["cost"] = {"total_usd_milli": sum(it["cost_usd_milli"] for it in r["items"])}
    assert shihuo.pairs(r, p)["F:B"] == {"both": 24, "first": 0, "second": 6, "neither": 10}
    assert lh.ronghuo(d, {}, 2, record=r)["outcome_proposed"] == "binghuo"  # 目标维对本火退了


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"plan_hash": "0" * 64}, ("计划哈希与登记的计划对不上",)),
        ({"purpose": "试跑"}, ("试跑段的记录只作旗帜",)),
        ({"status": "aborted"}, ("没有跑完", "未判")),
        ({"questions": {"set": "S2", "digest": "x"}}, ("题集与计划登记的不是同一套",)),
        ({"judge": {"model": "m-judge", "version": "2026-10", "prompts": "p@2"}}, ("盲判",)),
        ({"cost": {"total_usd_milli": 1}}, ("花费合计",)),
    ],
)
def test_a_record_that_does_not_match_the_plan_is_refused(change, words):
    d, p = trialed()
    refuses(lambda: lh.ronghuo(d, {}, 2, record={**record(p), **change}), "试火记录不能用来出结局", *words)


def test_an_arm_that_ran_on_another_model_voids_the_trial():
    d, p = trialed()
    r = record(p)
    r["arms"]["A0"]["model"] = "m-other"
    refuses(lambda: lh.ronghuo(d, {}, 2, record=r), "A0 臂读回的模型标识与计划不符")


def test_spending_past_the_total_cap_leaves_the_trial_unjudged():
    d, p = trialed()
    r = record(p, cost=p["caps"]["per_item_usd_milli"] + 1)
    assert r["cost"]["total_usd_milli"] > p["caps"]["total_usd_milli"]
    refuses(lambda: lh.ronghuo(d, {}, 2, record=r), "超过了计划登记的总上限")


def test_a_plan_is_judged_only_once():
    d, p = trialed()
    out = lh.ronghuo(d, {}, 2, record=record(p, f=36, a0=38))
    refuses(lambda: lh.ronghuo(out, {}, 2, record=record(p)), "一份计划只判一次")


# ---------------------------------------------------------------- 定阶处的核对


def judged(**kw) -> tuple[dict, dict, dict]:
    origin = kw.pop("origin", None)
    d, p = trialed(origin=origin)
    r = record(p, **kw)
    return lh.ronghuo(d, {}, 2, record=r), p, r


def test_three_refusals_before_anything_enters_the_gongfa():
    d, p, r = judged()
    g = shapes._read("gongfa.json")
    # 一、没有记录，或不是出结局的那一份
    refuses(lambda: lh.jue(d, g, "cz", TODAY, "huolian", []), "定阶要给试火记录")
    refuses(lambda: lh.jue(d, g, "cz", TODAY, "huolian", [], record=record(p, f=36)), "哈希与融火时记下的对不上")
    # 二、记录里的计划哈希不等于设计裁决时记下的
    moved = copy.deepcopy(d)
    moved["design_verdict"]["plan_hash"] = "0" * 64
    refuses(lambda: lh.jue(moved, g, "cz", TODAY, "huolian", [], record=r), "不等于设计裁决时记下的")
    # 三、按记录重算的结局不允许装入：炼档里记的提议被改高了也没有用
    low, _, r2 = judged(f=36, a0=38)
    forged = {**copy.deepcopy(low), "outcome_proposed": "huolian"}
    refuses(lambda: lh.jue(forged, g, "cz", TODAY, "huolian", [], record=r2), "系统判出的结局是不及原形", "不能越过门")
    done, g2 = lh.jue(d, g, "cz", TODAY, "huolian", [], record=r)
    assert done["status"] == "adopted" and done["verdict"]["system"] == "huolian" and g2["jie"] == g["jie"] + 1


@pytest.mark.parametrize(
    ("system", "given", "allowed"),
    [
        ("huolian", "huolian", True),
        ("huolian", "helian", True),
        ("huolian", "binghuo", True),
        ("helian", "huolian", False),
        ("buji", "helian", False),
        ("buji", "binghuo", False),  # 同一级的两种不收，诊断不同，不能互换
        ("buji", "fanshi", True),
        ("binghuo", "buji", False),
        ("fanshi", "binghuo", False),
    ],
)
def test_a_person_may_only_give_the_system_outcome_or_a_lower_one(system, given, allowed):
    kw = {
        "huolian": {},
        "helian": {"new": 0.5, "f": 36},
        "buji": {"f": 36, "a0": 38},
        "binghuo": {"new": 0.5},
        "fanshi": {"leaks": 1},
    }[system]
    d, _, r = judged(**kw)
    assert d["outcome_proposed"] == system
    g = shapes._read("gongfa.json")
    if allowed:
        assert lh.jue(d, g, "cz", TODAY, given, [], record=r)[0]["verdict"]["outcome"] == given
    else:
        refuses(lambda: lh.jue(d, g, "cz", TODAY, given, [], record=r), "只能等于或低于系统判出的")


# ---------------------------------------------------------------- 出身的用处


def test_a_hand_made_dossier_enters_as_a_revision_without_a_grade_and_is_not_a_success():
    d, _, r = judged(origin="手工", f=36, a0=38)  # 结局照实是不及原形
    g = shapes._read("gongfa.json")
    done, g2 = lh.jue(d, g, "cz", TODAY, "buji", [], record=r)
    assert done["status"] == "adopted" and "jie" not in done["verdict"]
    assert done["verdict"] | {"conditions": []} == done["verdict"] and done["verdict"]["outcome"] == "buji"
    assert done["verdict"]["installed"] == lh.MANUAL and done["verdict"]["mark"] == "原形门未过"
    assert g2["jie"] == g["jie"] and "h7.result-first@1" in g2["fires"]["H7"]
    assert g2["history"][-1] == {
        "jie": g["jie"],
        "change": "手工修订：演示（炼档 900）",
        "dossier": "900",
        "manual": True,
        "mark": "原形门未过",
        "replaces": "h7.result@1",
    }
    assert "手工修订：不加品阶，不计成功；原形门未过" in lh.render(done)
    back, g3 = lh.sanhuo(done, g2, "cz", TODAY, "演示")
    assert g3["jie"] == g["jie"] and g3["history"][-1]["manual"] and g3["fires"]["H7"] == g["fires"]["H7"]


def test_a_hand_made_dossier_that_passes_the_gate_still_gets_no_grade():
    d, _, r = judged(origin="手工")
    g = shapes._read("gongfa.json")
    done, g2 = lh.jue(d, g, "cz", TODAY, "huolian", [], record=r)
    assert g2["jie"] == g["jie"] and done["verdict"]["installed"] == lh.MANUAL and "mark" not in done["verdict"]


@pytest.mark.parametrize(
    ("kw", "outcome", "mark"),
    [
        ({}, "huolian", None),
        ({"new": 0.5, "f": 36}, "helian", None),
        ({"new": 0.5}, "binghuo", None),  # 并火：没有可量的增益，但验体全过、对本火不退
        ({"f": 36, "a0": 38}, "buji", "原形门未过"),
    ],
)
def test_a_hand_made_dossier_is_installed_as_a_revision_under_every_outcome_but_backfire(kw, outcome, mark):
    """手工的炼档装不装入只看三条（验体全过、对本火不退、人没有把结局往低里改），不看结局是哪一种：
    判成并火也按「手工修订」装入，不加品阶、不计成功。"""
    d, _, r = judged(origin="手工", **kw)
    assert d["outcome_proposed"] == outcome
    g = shapes._read("gongfa.json")
    done, g2 = lh.jue(d, g, "cz", TODAY, outcome, [], record=r)
    assert done["status"] == "adopted" and done["verdict"]["installed"] == lh.MANUAL and "jie" not in done["verdict"]
    assert done["verdict"]["outcome"] == outcome and done["verdict"].get("mark") == mark
    assert g2["jie"] == g["jie"] and "h7.result-first@1" in g2["fires"]["H7"]
    last = g2["history"][-1]
    assert last["manual"] and last["dossier"] == "900" and last.get("mark") == mark
    one = {"dossier": "001", "verdict": {"by": "cz", "outcome": "huolian", "jie": 2}}
    assert lh.check_history(g2, {"900": done, "001": one}) == []


def test_a_hand_made_dossier_judged_parallel_is_not_installed_when_the_person_lowered_it_there():
    """系统判的是火莲，人改低成并火：这不是照实的结局，手工的不装入。"""
    d, _, r = judged(origin="手工")
    g = shapes._read("gongfa.json")
    done, g2 = lh.jue(d, g, "cz", TODAY, "binghuo", [], record=r)
    assert done["status"] == "rejected" and "installed" not in done["verdict"] and g2 == g


@pytest.mark.parametrize("kw", [{"leaks": 1}, {"f": 20, "new": 0.5}], ids=["本火维退步", "目标维对本火退了"])
def test_a_hand_made_dossier_that_falls_behind_the_baseline_is_not_installed(kw):
    d, _, r = judged(origin="手工", **kw)
    g = shapes._read("gongfa.json")
    done, g2 = lh.jue(d, g, "cz", TODAY, d["outcome_proposed"], [], record=r)
    assert done["status"] == "rejected" and "installed" not in done["verdict"] and g2 == g


# ---------------------------------------------------------------- 划线


def test_the_plan_line_is_drawn_by_dossier_number(monkeypatch):
    two = placed("002")
    assert lh.gated(two) and not lh.needs_plan(two)  # 002 没有计划：读数照旧填，定阶不收记录
    assert lh.approve_design(two, "cz", TODAY)["design_verdict"].keys() == {"by", "date"}
    assert lh.needs_plan(placed("003"))
    monkeypatch.setattr(lh, "SHIHUO_FROM", None)
    assert not lh.needs_plan(placed("003"))
    assert lh.approve_design(placed("900"), "cz", TODAY)["status"] == "design_approved"


def test_a_dossier_before_the_plan_line_still_cannot_be_ruled_above_the_system():
    d = lh.approve_design(placed("002"), "cz", TODAY)
    d = lh.yanti(d, 0, [], {t: {"ok": True, "summary": "ok"} for t in lh.TRIALS}, "abc1234", measure_lines=0)
    same = {"both": 30, "first": 3, "second": 3, "neither": 4}
    d = lh.ronghuo(
        d,
        {
            TARGET: {"pairs": {"B:B1": same, "F:B": same, "F:A1": same}},
            "新性质": {"B": 0, "A1": 0, "F": 1},
            "凭据泄漏数": {"B": 0, "A1": 0, "F": 0},
            "每题次花费": {"B": 100, "B1": 104, "A1": 100, "F": 100},
        },
        2,
    )
    assert d["outcome_proposed"] == "helian" and d["yuanxing_gate"]["state"] == "unjudged"
    g = shapes._read("gongfa.json")
    refuses(lambda: lh.jue(d, g, "cz", TODAY, "huolian", []), "只能等于或低于系统判出的")
    refuses(lambda: lh.jue(d, g, "cz", TODAY, "helian", [], record={}), "没有登记试火计划")
    assert lh.jue(d, g, "cz", TODAY, "helian", [])[0]["verdict"]["system"] == "helian"


def test_the_record_and_the_judge_read_the_same_four_cells():
    assert (shihuo.PAIRS, shihuo.CELLS) == (lh.PAIRS, lh.CELLS)
    assert "fenjue/src/paoding_fenjue/shihuo.py" in lh.MEASURE_PATHS


# ---------------------------------------------------------------- 品阶史的核对（前一半）


def test_every_grade_history_row_points_to_a_ruling_and_past_the_line_to_a_trial_record():
    d, _, r = judged()
    g = shapes._read("gongfa.json")
    done, g2 = lh.jue(d, g, "cz", TODAY, "huolian", [], record=r)
    ds = {"900": done, "001": {"dossier": "001", "verdict": {"by": "cz", "outcome": "huolian", "jie": 2}}}
    assert lh.check_history(g2, ds) == []

    def errors(dossier=None, row=None, drop=()):
        c = copy.deepcopy(done)
        for path, v in (dossier or {}).items():
            node = c
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] = v
        for k in drop:
            del c[k]
        hist = [*g2["history"][:-1], {**g2["history"][-1], **(row or {})}]
        return lh.check_history({**g2, "history": hist}, {**ds, "900": c})

    def one(words, **kw):
        got = errors(**kw)
        assert len(got) == 1 and words in got[0], got

    one("没有试火记录", dossier={("trial_record",): None})
    one("没有试火记录", drop=("trial_record",))
    one("试火记录的计划哈希与设计裁决时记下的不同", dossier={("trial_record", "plan_hash"): "0" * 64})
    one("登记的试火计划与设计裁决时记下的哈希对不上", dossier={("trial_plan", "seed"): "换过了"})
    one("那里没有裁决", dossier={("verdict",): None})
    one("那里没有裁决", dossier={("verdict", "by"): ""})
    one("对不上", dossier={("verdict", "jie"): 9})
    one("对不上", dossier={("verdict", "outcome"): "binghuo"})
    one("不是按手工修订装入的", row={"manual": True})
    one("那里没有裁决", row={"dossier": "999"})
    extra = {**g2, "history": [*g2["history"], {"jie": g2["jie"] + 1, "change": "凭空多出的一阶"}]}
    assert "没有指向任何炼档" in lh.check_history(extra, ds)[0]
    back, g3 = lh.sanhuo(copy.deepcopy(done), g2, "cz", TODAY, "演示")
    assert lh.check_history(g3, {**ds, "900": back}) == []
    assert "没有散火记录" in lh.check_history(g3, ds)[0]  # 品阶史记了散火，炼档里没有


def test_dossiers_before_the_plan_line_need_no_trial_record_in_the_history(monkeypatch):
    """按档号划线：划线之前的炼档（001、002）品阶史只要指向裁决。"""
    live = {"001": {"dossier": "001", "verdict": {"by": "cz", "outcome": "huolian", "jie": 2}}}
    assert lh.check_history(shapes._read("gongfa.json"), live) == []
    assert "那里没有裁决" in lh.check_history(shapes._read("gongfa.json"), {})[0]
    monkeypatch.setattr(lh, "YUANXING_GATE_FROM", "001")
    monkeypatch.setattr(lh, "SHIHUO_FROM", "001")
    assert "没有试火记录" in lh.check_history(shapes._read("gongfa.json"), live)[0]


def test_plan_hash_is_the_same_value_the_batch_header_tool_computes():
    """批次头（liangju/pici.py）自己算计划哈希，量具与组件互不 import：两边各钉同一份文档的同一个值
    （另一边是 liangju/tests/test_mangpan.py::test_batch_header_takes_hash_judge_and_caps_from_the_plan_file）。"""
    doc = {"b": [1, 2, {"丙": None}], "a": "甲", "c": 1.5}
    assert shihuo.digest(doc) == "874ca7719efb75b5789c8f28e9856c716abffa9bee9ccbcb83c94ee181be1c1e"
