"""盲判：三段、抽样、发现记录、启动前的三道核对、自检样本、换臂名。"""

import argparse
import hashlib
import json
import re
import shutil
import time

import pytest
from lj_rig import (
    ARMS,
    CANARY,
    JUDGE,
    SAMPLES,
    Fake,
    attempt,
    by_marks,
    by_words,
    lines_as_claims,
    make_batch,
    parts,
    simple,
)

from liangju import mangpan, pici, tici
from liangju.common import Refused, read_json, read_jsonl, sha, write_json
from liangju.model import Ledger, Toolbox, with_tools


def item(answer: str, subs: int = 2) -> mangpan.BlindItem:
    return mangpan.BlindItem("q1", "题面", tuple(f"子问{i}" for i in range(1, subs + 1)), answer, CANARY / "snapshot")


def ns(bdir, qpath, jpath, **kw):
    return argparse.Namespace(batch=str(bdir), questions=str(qpath), judge=str(jpath), selfcheck=None, jobs=2, **kw)


# ---------------------------------------------------------------- 三段


def test_tidy_keeps_only_verbatim_quotes():
    def tidy(p):
        return {
            "subquestions": [
                {
                    "n": 1,
                    "claims": [{"quote": "攒够 16 条就发", "cite": "a.py"}, {"quote": "攒够 17 条就发", "cite": ""}],
                },
                {"n": 2, "claims": [{"quote": "满了丢\n最早的", "cite": ""}, {"quote": "攒够 16 条就发", "cite": ""}]},
            ]
        }

    it = item("它攒够 16 条就发。满了丢  最早的。")
    claims, dropped = mangpan.tidy(it, Fake(tidy, None, None), Ledger(None))
    assert [[it.answer[c["at"][0] : c["at"][1]] for c in cs] for cs in claims] == [
        ["攒够 16 条就发"],
        ["满了丢  最早的"],
    ]
    assert dropped == 2  # 一条改了字，一条重复


def test_stage_output_is_retried_once_then_counts_as_judge_failure():
    calls = []

    def tidy(p):
        calls.append(p)
        return {"subquestions": [{"n": 2, "claims": []}]}  # 编号不全

    with pytest.raises(mangpan.JudgeFailed):
        mangpan.tidy(item("x"), Fake(tidy, None, None), Ledger(None))
    assert len(calls) == 2 and "不合要求" in calls[1]["回答原文"]


def test_pick_is_fixed_by_seed_and_covers_every_subquestion_first():
    assert mangpan.pick([5, 1, 0], "s") == mangpan.pick([5, 1, 0], "s")
    got = mangpan.pick([5, 1, 0], "s")
    assert len([g for g in got if g[0] == 0]) == 2 and (1, 0) in got and len(got) == 3  # 不足 2 条就全查
    wide = mangpan.pick([4] * 6, "s")
    assert len(wide) == 8 and {s for s, _ in wide} == set(range(6))  # 至多 8 条，每个子问先有一条
    assert mangpan.pick([5, 5], "s") != mangpan.pick([5, 5], "另一个种子")


def test_judge_gives_the_two_blind_conditions():
    good = mangpan.judge(item("1: 甲\n1: 乙\n2: 丙"), simple(), Ledger(None), "seed")
    assert good["answered"] and good["true"] and len(good["sampled"]) == 3
    half = mangpan.judge(item("1: 甲\n2: 只说了一半"), simple(), Ledger(None), "seed")
    assert not half["answered"] and half["true"]
    wrong = mangpan.judge(item("1: 甲\n2: 这条是错的"), simple(), Ledger(None), "seed")
    assert wrong["answered"] and not wrong["true"]
    none = mangpan.judge(item("1: 甲"), simple(), Ledger(None), "seed")
    assert [r["verdict"] for r in none["subquestions"]] == ["answered", "missing"]


def test_blind_item_has_no_arm_and_prompts_never_see_one(tmp_path, monkeypatch):
    """换臂名：同一份回答标成不同的臂，判的是同一份（同一个盲号），送进模型的文字里没有臂名。"""
    assert "arm" not in mangpan.BlindItem.__dataclass_fields__
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    arms = {"ARMSENTINELX": ARMS["B"], "ARMSENTINELY": ARMS["B2"]}
    same = "1: 甲\n2: 这条是错的"
    atts = [attempt("ARMSENTINELX", "q1", 1, same), attempt("ARMSENTINELY", "q1", 1, same)]
    bdir, qpath, jpath = make_batch(tmp_path, atts, arms=arms)
    fake = simple()
    assert mangpan.run_judge(ns(bdir, qpath, jpath), fake) == 0
    index = read_json(bdir / "index.json")
    assert index[0]["blind"] == index[1]["blind"] and len(list((bdir / "verdicts").glob("*.json"))) == 1
    assert fake.seen and not any("ARMSENTINEL" in text for _, text in fake.seen)
    found = read_jsonl(bdir / "findings.jsonl")
    assert sorted(f["at"]["arm"] for f in found) == ["ARMSENTINELX", "ARMSENTINELY"]
    a, b = ({k: v for k, v in f.items() if k not in ("at", "hash")} for f in found)
    assert a == b  # 两条臂的发现记录除了定位逐项相同


def test_swapping_the_arm_labels_swaps_nothing_but_the_labels(tmp_path, monkeypatch):
    """换臂名测试（整批）：两条臂交出不同的回答，把臂名对调再判一遍。每份回答的判的记录逐项相同，
    发现记录只有定位里的臂名跟着对调。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    good, bad = "1: 甲\n2: 乙", "1: 甲\n2: 这条是错的"

    def run(tmp, first, second):
        atts = [attempt(first, q, r, good) for q in ("q1", "q2") for r in (1, 2)]
        atts += [attempt(second, q, r, bad) for q in ("q1", "q2") for r in (1, 2)]
        bdir, qpath, jpath = make_batch(tmp, atts)
        assert mangpan.run_judge(ns(bdir, qpath, jpath), simple()) == 0
        verdicts = {f.name: read_json(f) for f in sorted((bdir / "verdicts").glob("*.json"))}
        for v in verdicts.values():
            v.pop("seconds")  # 用时是量出来的，不是判出来的
        return verdicts, read_jsonl(bdir / "findings.jsonl")

    (tmp_path / "一").mkdir()
    (tmp_path / "二").mkdir()
    v1, f1 = run(tmp_path / "一", "B", "B2")
    v2, f2 = run(tmp_path / "二", "B2", "B")
    assert v1 == v2 and len(v1) == 4 and f1
    assert {f["at"]["arm"] for f in f1} == {"B2"} and {f["at"]["arm"] for f in f2} == {"B"}

    def unlabeled(found):
        rows = [{**f, "at": {**f["at"], "arm": "?"}} for f in found]
        return sorted(json.dumps({k: v for k, v in r.items() if k != "hash"}, sort_keys=True) for r in rows)

    assert unlabeled(f1) == unlabeled(f2)


# ---------------------------------------------------------------- 发现记录


def test_findings_cover_the_five_adverse_verdicts_and_carry_no_proper_nouns(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    atts = [
        attempt("B", "q1", 1, "1: 只说了一半"),  # 子问 1 部分答到，子问 2 没答到
        attempt("B", "q2", 1, "1: 这条是错的\n2: 这条是虚的"),
        attempt("B", "q3", 1, None, status="watchdog"),
    ]
    bdir, qpath, jpath = make_batch(tmp_path, atts)

    def read(p):
        doc = by_marks(p)
        for r in doc["subquestions"]:
            if r["mechanism"]:
                r["mechanism"] = "回答把 BoundedQueue 的做法说成了 relay/sender.py 的，half_done"
        return doc

    assert mangpan.run_judge(ns(bdir, qpath, jpath), Fake(lines_as_claims, read, by_words)) == 0
    found = read_jsonl(bdir / "findings.jsonl")
    assert sorted(f["verdict"] for f in found) == sorted(mangpan.ADVERSE)
    assert {f["source"] for f in found} == {"pandu", "hedui", "run"}
    partial = next(f for f in found if f["verdict"] == "partial")
    assert partial["scrubbed"] and "BoundedQueue" not in partial["text"] and "sender" not in partial["text"]
    assert "half_done" in partial["text"]  # 不在快照与题面里的词不动
    refuted = next(f for f in found if f["verdict"] == "refuted")
    assert refuted["evidence"]["path"] == "relay/config.py" and refuted["evidence"]["answer_at"] == [3, 8]
    assert refuted["at"] == {"batch": "T-1", "arm": "B", "question": "q2", "rep": 1, "subq": 1}
    assert all(re.fullmatch(r"[0-9a-f]{64}", f["hash"]) for f in found) and len({f["hash"] for f in found}) == 5


# ---------------------------------------------------------------- 启动前的核对


def test_judge_refuses_without_registration_selfcheck_or_a_different_model(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    bdir, qpath, jpath = make_batch(tmp_path, [attempt("B", "q1", 1, "1: 甲\n2: 乙")])
    good = read_json(jpath)

    def refused(**judge) -> str:
        write_json(jpath, {**good, **judge})
        with pytest.raises(Refused) as e:
            mangpan.run_judge(ns(bdir, qpath, jpath), simple())
        return str(e.value)

    assert "没有登记全" in refused(name="")
    assert "没有登记全" in refused(version="")
    assert "必须与各臂不同" in refused(name="arm-model")
    assert "自检记录不是" in refused(version="8")  # 自检是另一个版本做的
    write_json(jpath, good)
    sc = read_json(bdir / "selfcheck.json")
    write_json(bdir / "selfcheck.json", {**sc, "prompts": "旧的提示词"})
    assert "自检记录不是" in refused()
    write_json(bdir / "selfcheck.json", {**sc, "ok": False})
    assert "自检记录不是" in refused()
    (bdir / "selfcheck.json").unlink()
    assert "没有自检记录" in refused()
    assert not (bdir / "verdicts").exists()  # 被拒绝时一份都没有判


def test_judge_model_seen_in_a_run_counts_even_if_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    atts = [attempt("B", "q1", 1, "1: 甲\n2: 乙", models_seen=["judge-model"])]
    bdir, qpath, jpath = make_batch(tmp_path, atts)
    with pytest.raises(Refused):
        mangpan.run_judge(ns(bdir, qpath, jpath), simple())


def test_question_without_subquestions_is_refused(tmp_path):
    qs = [{"id": "q1", "text": "t", "subquestions": [], "snapshot": str(CANARY / "snapshot")}]
    _, qpath, _ = make_batch(tmp_path, [], questions=qs)
    with pytest.raises(Refused):
        mangpan.load_questions(qpath)


# ---------------------------------------------------------------- 自检样本


def _canary_tidy(p):
    rows = [{"n": i, "claims": []} for i in (1, 2, 3)]
    text = p["回答原文"]
    if text.startswith("# 回答"):  # 文风甲：分节的条目，带出处
        sub = 0
        for line in text.splitlines():
            if line.startswith("## "):
                sub = {"攒批": 1, "队列满": 2, "重试与退避": 3}[line[3:]]
            m = re.match(r"\d+\. (.+?)（(`.+)）。$", line)
            if m and sub:
                rows[sub - 1]["claims"].append({"quote": m.group(1), "cite": m.group(2)})
    else:  # 文风乙：成段的文字，不带出处
        for sub, para in enumerate(text.strip().split("\n\n"), 1):
            for s in para.split("。"):
                if s.strip():
                    rows[sub - 1]["claims"].append({"quote": s.strip(), "cite": ""})
    return {"subquestions": rows}


def _canary_read(p):
    rows = []
    for i, block in enumerate(re.split(r"子问 \d+ 的结论：\n", p["摘出的结论"])[1:], 1):
        empty = "没有摘出结论" in block
        absent = i == 3 and ("实际上没有" in block or "并不存在" in block)
        rows.append(
            {
                "n": i,
                "verdict": "missing" if empty else "answered",
                "premise_false": absent,
                "reason": "r",
                "mechanism": "没有说到" if empty else "",
            }
        )
    return {"subquestions": rows}


def _canary_check(p):
    q = p["结论的逐字片段"]
    bad = "64" in q or "六十四" in q
    return {
        "verdict": "refuted" if bad else "holds",
        "path": "relay/config.py",
        "lines": [3, 3],
        "mechanism": "把缺省值说成了另一个数" if bad else "",
    }


def test_selfcheck_passes_with_a_judge_that_reads_and_fails_with_one_that_waves_everything_through():
    careful = mangpan.selfcheck(Fake(_canary_tidy, _canary_read, _canary_check), Ledger(None))
    assert careful["ok"] and set(careful["results"]) == set(SAMPLES)

    def lenient_read(p):
        doc = _canary_read(p)
        for r in doc["subquestions"]:
            r.update(verdict="answered", premise_false=False)
        return doc

    def lenient_check(p):
        return {"verdict": "holds", "path": "x", "lines": [1, 1], "mechanism": ""}

    sloppy = mangpan.selfcheck(Fake(_canary_tidy, lenient_read, lenient_check), Ledger(None))
    assert not sloppy["ok"] and not any(r["ok"] for r in sloppy["results"].values())


def test_selfcheck_command_writes_the_record_the_gate_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    bdir, qpath, jpath = make_batch(tmp_path, [attempt("B", "q1", 1, "1: 甲\n2: 乙")])
    a = argparse.Namespace(judge=str(jpath), out=str(bdir / "selfcheck.json"))
    assert mangpan.run_selfcheck(a, Fake(_canary_tidy, _canary_read, _canary_check)) == 0
    assert mangpan.run_judge(ns(bdir, qpath, jpath), simple()) == 0
    assert mangpan.run_selfcheck(a, simple()) == 1  # 这个假模型看不懂样本：记成没通过
    with pytest.raises(Refused):
        mangpan.run_judge(ns(bdir, qpath, jpath), simple())


def test_the_committed_samples_are_three_known_answers_each_in_two_styles():
    """自检样本入库：三份已知答案（漏掉一个子问、写错一条承重结论、前提不成立且说清了），两种文风各一份；
    同一份已知答案的两种文风，预期逐项相同。"""
    expected = read_json(CANARY / "expected.json")["samples"]
    assert set(expected) == set(SAMPLES) == {p.stem for p in (CANARY / "answers").glob("*.md")}
    for known in ("missing", "wrong", "premise"):
        assert expected[f"{known}-a"] == expected[f"{known}-b"]
    listed = read_json(CANARY / "expected.json")["snapshot"]
    assert len(listed) == 5 and all((CANARY / "snapshot" / rel).is_file() for rel in listed)
    assert set(mangpan.canary_files()) == {
        "question.json",
        "expected.json",
        *(f"answers/{n}.md" for n in SAMPLES),
        *(f"snapshot/{rel}" for rel in listed),
    }
    styles = {
        s: [(CANARY / "answers" / f"{k}-{s}.md").read_text(encoding="utf-8") for k in ("missing", "wrong")]
        for s in "ab"
    }
    assert all(t.startswith("# 回答") for t in styles["a"]) and not any(t.startswith("#") for t in styles["b"])


def test_selfcheck_records_how_long_each_item_took():
    ticks = iter(range(0, 1000, 7))
    doc = mangpan.selfcheck(Fake(_canary_tidy, _canary_read, _canary_check), Ledger(None), clock=lambda: next(ticks))
    assert doc["v"] == 2 and {r["seconds"] for r in doc["results"].values()} == {7} and doc["seconds_max"] == 7
    assert {k: doc[k] for k in ("prompts", "sample", "canary")} == mangpan.version()
    failed = mangpan.selfcheck(Fake(lambda p: {"oops": 1}, _canary_read, _canary_check), Ledger(None))
    assert not failed["ok"] and all(isinstance(r["seconds"], float) for r in failed["results"].values())


def test_the_version_names_the_prompts_the_sampling_and_the_samples(tmp_path, monkeypatch, capsys):
    """三段提示词的版本进计划哈希：`version` 给出的 prompts 与 sample 原样写进计划的盲判一栏；
    任何一段提示词或任何一份样本改一个字，版本就变。"""
    before = mangpan.version()
    assert mangpan.main(["version"]) == 0 and json.loads(capsys.readouterr().out) == before
    assert before["sample"] == {"per_sub": mangpan.PER_SUBQ, "max": mangpan.PER_ANSWER}
    real = mangpan.prompts()
    for stage in mangpan.STAGES:
        monkeypatch.setattr(mangpan, "prompts", lambda s=stage: {**real, s: real[s] + "。"})
        assert mangpan.version()["prompts"] != before["prompts"]
    monkeypatch.undo()
    shutil.copytree(mangpan.HERE / "canary", tmp_path / "canary")
    shutil.copytree(mangpan.HERE / "prompts", tmp_path / "prompts")
    monkeypatch.setattr(mangpan, "HERE", tmp_path)
    assert mangpan.version() == before
    with (tmp_path / "canary" / "answers" / "wrong-b.md").open("a", encoding="utf-8") as fh:
        fh.write("多一句。")
    after = mangpan.version()
    assert after["canary"] != before["canary"] and after["prompts"] == before["prompts"]


def plan_arm(**kw):
    base = {"what": "臂", "model": "arm-model", "version": "1", "endpoint": "proxy", "sampling": {"temperature": 0}}
    return {**base, "meter": "ledger", "price_table": "t1", **kw}


PLAN = {
    "dossier": "003",
    "arms": {"B": plan_arm(), "B1": plan_arm(), "F": plan_arm()},
    "judge": {"model": "judge-model", "version": "7", "prompts": "", "sample": {}, "seconds_per_item": 40},
    "questions": {},
    "trial_segment": {},
    "caps": {"per_item_usd_milli": 90, "total_usd_milli": 1080},
    "seed": "s",
}


def real_plan(**judge):
    """一份盲判一栏照现在这把尺子填的计划。"""
    ruler = {k: v for k, v in mangpan.version().items() if k != "canary"}
    return {**PLAN, "judge": {**PLAN["judge"], **ruler, **judge}}


def planned(tmp_path, **header_judge):
    """一个登记了试火计划的批次：批次头里的臂、盲判一栏与上限都从计划来。`header_judge` 是登记之后对批次头的手改。"""
    reg = pici.from_plan(real_plan())
    reg["judge"] = {**reg["judge"], **header_judge}
    return make_batch(tmp_path, [attempt("B", "q1", 1, "1: 甲\n2: 乙")], **reg)


def test_judge_refuses_without_a_selfcheck_record_that_is_all_correct_and_within_the_time_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    bdir, qpath, jpath = planned(tmp_path)
    sc = read_json(bdir / "selfcheck.json")

    def refused(**change) -> str:
        write_json(bdir / "selfcheck.json", {**sc, **change})
        with pytest.raises(Refused) as e:
            mangpan.run_judge(ns(bdir, qpath, jpath), simple())
        assert not (bdir / "verdicts").exists()  # 被拒绝时一份都没有判
        return str(e.value)

    def results(**over):
        return {"results": {k: {"ok": True, "seconds": 30.0, **over.get(k.replace("-", "_"), {})} for k in SAMPLES}}

    assert "wrong-b 的盲判用时超过每题次的盲判时限（40.0 秒）" in refused(**results(wrong_b={"seconds": 40.5}))
    assert "没有每个题次的用时" in refused(results={k: {"ok": True} for k in SAMPLES})  # 旧式记录：没有计时
    assert "没有每个题次的用时" in refused(**results(wrong_b={"seconds": "快"}))
    assert "样本不全" in refused(results={k: {"ok": True, "seconds": 1.0} for k in SAMPLES[:5]})
    assert "没有全部判对" in refused(ok=False)  # 在时限内但判错了：照样不启动
    assert "自检样本" in refused(canary="另一套样本")
    write_json(bdir / "selfcheck.json", {**sc, **results(wrong_b={"seconds": 40.0})})  # 正好等于时限：算在时限内
    assert mangpan.run_judge(ns(bdir, qpath, jpath), simple()) == 0
    assert all(isinstance(read_json(f)["seconds"], float) for f in (bdir / "verdicts").glob("*.json"))
    with pytest.raises(Refused):  # 重判走同一道门
        write_json(bdir / "selfcheck.json", {**sc, **results(missing_a={"seconds": 41})})
        mangpan.run_rejudge(ns(bdir, qpath, jpath), simple())


def test_a_batch_without_a_plan_has_no_time_limit_but_still_needs_the_timing(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    bdir, qpath, jpath = make_batch(tmp_path, [attempt("B", "q1", 1, "1: 甲\n2: 乙")])
    sc = read_json(bdir / "selfcheck.json")
    write_json(bdir / "selfcheck.json", {**sc, "results": {k: {"ok": True, "seconds": 9e6} for k in SAMPLES}})
    assert mangpan.run_judge(ns(bdir, qpath, jpath), simple()) == 0  # 起点轮：没有计划，时限一栏是「无」
    write_json(bdir / "selfcheck.json", {**sc, "results": {k: {"ok": True} for k in SAMPLES}})
    (bdir / "verdicts").rename(bdir / "判过的")
    with pytest.raises(Refused):
        mangpan.run_judge(ns(bdir, qpath, jpath), simple())


def test_the_judge_must_be_the_one_the_plan_registered(tmp_path, monkeypatch):
    """计划里登记的盲判一栏（模型、版本、三段提示词的版本、抽样量、时限）随批次头带来，启动前逐项核对。
    登记时已经核过尺子的版本；这里守的是登记之后尺子或批次头又变了。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")

    def refused(where, header=None, **judge) -> str:
        where.mkdir()
        bdir, qpath, jpath = planned(where, **judge)
        if header is not None:
            write_json(bdir / "batch.json", {**read_json(bdir / "batch.json"), **header})
        with pytest.raises(Refused) as e:
            mangpan.run_judge(ns(bdir, qpath, jpath), simple())
        return str(e.value)

    assert "模型或版本与试火计划里登记的不同" in refused(tmp_path / "1", model="别的模型")
    assert "模型或版本与试火计划里登记的不同" in refused(tmp_path / "2", version="8")
    assert "三段提示词的版本与试火计划里登记的不同" in refused(tmp_path / "3", prompts="旧的一版")
    assert "抽样量与试火计划里登记的不同" in refused(tmp_path / "4", sample={"per_sub": 1, "max": 8})
    assert "没有每题次的盲判时限" in refused(tmp_path / "5", seconds_per_item=None)


def test_refusal_reasons_say_which_side_of_the_header_is_missing(tmp_path, monkeypatch):
    """批次头里计划哈希与盲判一栏要么都有要么都没有；缺哪一边，理由就说哪一边。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")

    def refused(where, **header) -> str:
        where.mkdir()
        bdir, qpath, jpath = planned(where)
        write_json(bdir / "batch.json", {**read_json(bdir / "batch.json"), **header})
        with pytest.raises(Refused) as e:
            mangpan.run_judge(ns(bdir, qpath, jpath), simple())
        return str(e.value)

    for n, missing in enumerate((None, "不是一张表", [])):  # 有计划哈希，没有（像样的）盲判一栏
        why = refused(tmp_path / f"a{n}", judge=missing)
        assert "这一批登记了试火计划，批次头里却没有盲判一栏" in why
    for n, extra in enumerate(({"model": "judge-model"}, "不是一张表", [])):  # 没有计划哈希，却有盲判一栏
        why = refused(tmp_path / f"b{n}", plan_hash="无", judge=extra)
        assert "有盲判一栏却没有计划哈希" in why and "登记了试火计划" not in why


def test_registering_a_batch_with_a_plan_checks_everything_already_known(tmp_path):
    """核对发生在花钱之前：三段版本或抽样量对不上、花费上限缺或不是正数、臂与计划逐臂对不上，都拒绝登记。"""
    arms, cfg, plan = tmp_path / "arms.json", tmp_path / "cfg.yaml", tmp_path / "plan.json"
    cfg.write_text("x: 1\n")
    n = 0

    def start(doc, given=None) -> int:
        nonlocal n
        n += 1
        write_json(plan, doc)
        argv = ["start", "--batch", str(tmp_path / f"b{n}"), "--id", "P-1", "--purpose", "判定", "--config", str(cfg)]
        argv += ["--set-code", "SET-A", "--set-source", "生成", "--plan", str(plan)]
        if given is not None:
            write_json(arms, given)
            argv += ["--arms", str(arms)]
        code = pici.main(argv)
        assert (tmp_path / f"b{n}" / "batch.json").exists() == (code == 0)  # 被拒绝时什么都没有登记
        return code

    def why(doc, given=None) -> str:
        with pytest.raises(Refused) as e:
            pici.from_plan(doc, given)
        assert start(doc, given) == 2
        return str(e.value)

    good = real_plan()
    assert "三段提示词的版本" in why(real_plan(prompts="旧的一版"))
    assert "抽样量" in why(real_plan(sample={"per_sub": 1, "max": 8}))
    for caps in ({}, None, {"per_item_usd_milli": 90}, {"per_item_usd_milli": None, "total_usd_milli": 1080}):
        assert "花费上限缺了或不是正数" in why({**good, "caps": caps})
    for bad in (0, -5, True, "90", 1.5):
        assert "花费上限缺了或不是正数" in why({**good, "caps": {"per_item_usd_milli": bad, "total_usd_milli": 1080}})
        assert "花费上限缺了或不是正数" in why({**good, "caps": {"per_item_usd_milli": 90, "total_usd_milli": bad}})

    same = {k: {f: v for f, v in a.items() if f != "what"} for k, a in good["arms"].items()}
    changes = {"model": "另一个", "version": "2", "endpoint": "direct", "sampling": {"temperature": 1}}
    changes |= {"meter": "export", "price_table": "t2"}
    assert tuple(changes) == pici.PLAN_ARM_FIELDS
    for field, other in changes.items():
        assert f"B 臂的 {[field]} 与计划里登记的不同" in why(good, {**same, "B": {**same["B"], field: other}})
        lacking = {k: v for k, v in same["B"].items() if k != field}
        assert f"B 臂的 {[field]}" in why(good, {**same, "B": lacking})
    assert "不一致" in why(good, {k: v for k, v in same.items() if k != "F"})  # 计划有，登记的没有
    assert "不一致" in why(good, {**same, "A1": same["B"]})  # 登记的有，计划没有
    assert "不一致" in why(good, ARMS)  # 没有计划的批次用的那套登记：臂名都对不上
    assert "不认识" in why({**good, "arms": {**good["arms"], "X": plan_arm()}})
    assert "B 臂缺 ['model']" in why({**good, "arms": {**good["arms"], "B": plan_arm(model="")}})
    assert "必须与各臂不同" in why({**good, "arms": {**good["arms"], "F": plan_arm(model="judge-model")}})

    assert start(good, same) == 0  # 逐项相同：照常登记
    assert start(good) == 0  # 不另给：臂从计划里取
    a, b = (read_json(tmp_path / f"b{k}" / "batch.json") for k in (n - 1, n))
    assert a["arms"] == b["arms"] and set(a["arms"]) == {"B", "B1", "F"}
    assert [a["arms"][k]["role"] for k in ("B", "B1", "F")] == ["benhuo", "tonghuo", "hehuo"]
    assert {k: v for k, v in a["arms"]["B"].items() if k != "role"} == good["arms"]["B"]  # 各栏原样，不另抄一种写法
    write_json(arms, ARMS)
    argv = ["start", "--batch", str(tmp_path / "无计划"), "--id", "S0", "--purpose", "起点轮", "--config", str(cfg)]
    argv += ["--set-code", "SET-A", "--set-source", "手出"]
    assert pici.main(argv) == 2 and pici.main([*argv, "--arms", str(arms)]) == 0  # 没有计划的批次照旧用 --arms


def test_qualify_answers_for_a_candidate_judge_before_any_batch_exists(tmp_path, monkeypatch, capsys):
    """选盲判模型：给计划、盲判的登记与一份自检记录，机器回答是否全部判对并且在时限内、是否计划登记的那一个。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    plan, jpath, scpath = tmp_path / "plan.json", tmp_path / "judge.json", tmp_path / "selfcheck.json"
    write_json(plan, real_plan())
    write_json(jpath, JUDGE)
    a = argparse.Namespace(judge=str(jpath), out=str(scpath))
    assert mangpan.run_selfcheck(a, Fake(_canary_tidy, _canary_read, _canary_check)) == 0  # 真走一遍自检命令
    sc = read_json(scpath)
    argv = ["qualify", "--plan", str(plan), "--judge", str(jpath), "--selfcheck", str(scpath)]

    def ask(record=None, judge=None, doc=None) -> tuple[int, dict]:
        write_json(scpath, record or sc)
        write_json(jpath, {**JUDGE, **(judge or {})})
        write_json(plan, doc or real_plan())
        capsys.readouterr()
        code = mangpan.main(argv)
        return code, json.loads(capsys.readouterr().out)

    code, out = ask()
    assert code == 0 and out["不能启用的理由"] == [] and out["每题次的盲判时限（秒）"] == 40.0
    assert [out[k] for k in ("可以启用", "是计划登记的那一个盲判", "与各臂的模型都不同", "每个题次都在时限内")] == [
        "是"
    ] * 4
    assert out["自检全部判对（这个模型、这版提示词、这套样本）"] == out["自检记录里每个题次都有用时"] == "是"

    slow = {**sc, "results": {k: {**r, "seconds": 41.0 if k == "premise-a" else 3.0} for k, r in sc["results"].items()}}
    code, out = ask(slow)
    assert code == 1 and out["可以启用"] == "否" and out["每个题次都在时限内"] == "否"
    assert out["自检全部判对（这个模型、这版提示词、这套样本）"] == "是" and out["自检最慢的一个题次（秒）"] == 41.0
    assert "premise-a 的盲判用时超过每题次的盲判时限" in out["不能启用的理由"][0]

    code, out = ask({**sc, "ok": False})
    assert (
        code == 1
        and out["自检全部判对（这个模型、这版提示词、这套样本）"] == "否"
        and out["每个题次都在时限内"] == "是"
    )
    code, out = ask({**sc, "results": {k: {"ok": True} for k in SAMPLES}})
    assert code == 1 and out["自检记录里每个题次都有用时"] == "否" and out["每个题次都在时限内"] == "没有用时，判不了"
    code, out = ask(judge={"name": "另一个候选"})  # 自检是别的模型做的，它也不是计划登记的那一个
    assert code == 1 and out["是计划登记的那一个盲判"] == "否" and len(out["不能启用的理由"]) == 2
    code, out = ask({**sc, "model": "arm-model"}, judge={"name": "arm-model"}, doc=real_plan(model="arm-model"))
    assert code == 1 and out["与各臂的模型都不同"] == "否" and out["是计划登记的那一个盲判"] == "是"
    code, out = ask(doc=real_plan(prompts="旧的一版"))
    assert code == 1 and "三段提示词的版本" in out["不能启用的理由"][0]
    write_json(plan, {**real_plan(), "judge": {"model": "judge-model"}})
    assert mangpan.main(argv) == 2  # 计划里盲判一栏不全：拒绝

    # 批次启动前走的是同一道核对：同一份计划、同一份慢的自检记录，批次也不启动
    (tmp_path / "批").mkdir()
    bdir, qpath, bj = planned(tmp_path / "批")
    write_json(bdir / "selfcheck.json", slow)
    with pytest.raises(Refused) as e:
        mangpan.run_judge(ns(bdir, qpath, bj), simple())
    assert "premise-a 的盲判用时超过每题次的盲判时限" in str(e.value)


def test_a_stray_file_among_the_samples_changes_nothing(tmp_path, monkeypatch):
    """样本的版本只由自检真读的文件决定：目录里多出与样本无关的文件，版本不变，旧的自检记录照常能用，
    盲判对着的快照里也没有它。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    before = mangpan.version()
    shutil.copytree(mangpan.HERE / "canary", tmp_path / "canary")
    shutil.copytree(mangpan.HERE / "prompts", tmp_path / "prompts")
    monkeypatch.setattr(mangpan, "HERE", tmp_path)
    bdir, qpath, jpath = planned(tmp_path)  # 自检记录是在多出文件之前做的
    for where in ("", "answers", "snapshot", "snapshot/relay"):
        (tmp_path / "canary" / where / ".DS_Store").write_bytes(b"\x00\x01")
    (tmp_path / "canary" / "answers" / "草稿.md").write_text("不是样本", encoding="utf-8")
    (tmp_path / "canary" / "snapshot" / "relay" / "notes.py.swp").write_text("x", encoding="utf-8")
    assert mangpan.version() == before
    assert mangpan.run_judge(ns(bdir, qpath, jpath), simple()) == 0

    seen: list[list[str]] = []
    inner = mangpan._selfcheck

    def spy(files, snapshot, *rest):
        seen.append(sorted(p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()))
        return inner(files, snapshot, *rest)

    monkeypatch.setattr(mangpan, "_selfcheck", spy)
    doc = mangpan.selfcheck(Fake(_canary_tidy, _canary_read, _canary_check), Ledger(None))
    assert doc["ok"] and doc["canary"] == before["canary"] and set(doc["results"]) == set(SAMPLES)
    assert seen == [sorted(read_json(tmp_path / "canary" / "expected.json")["snapshot"])]
    (tmp_path / "canary" / "snapshot" / "relay" / "config.py").write_text("改了一个真读的文件", encoding="utf-8")
    assert mangpan.version()["canary"] != before["canary"]


PARITY_DOC = {"b": [1, 2, {"丙": None}], "a": "甲", "c": 1.5}
PARITY_HASH = "874ca7719efb75b5789c8f28e9856c716abffa9bee9ccbcb83c94ee181be1c1e"


def test_batch_header_takes_hash_judge_and_caps_from_the_plan_file(tmp_path):
    cfg, plan = tmp_path / "cfg.yaml", tmp_path / "plan.json"
    cfg.write_text("x: 1\n")
    doc = real_plan()
    write_json(plan, doc)
    argv = ["start", "--batch", str(tmp_path / "b"), "--id", "P-1", "--purpose", "判定"]
    argv += ["--config", str(cfg), "--set-code", "SET-A", "--set-source", "生成", "--plan", str(plan)]
    assert pici.main(argv) == 0
    head = read_json(tmp_path / "b" / "batch.json")
    # 哈希的算法与登记计划的那一处相同：键排序、紧凑分隔的 JSON 的 sha256。量具与组件互不 import，
    # 所以两边各钉同一份文档的同一个值（另一边是 fenjue/tests/test_shihuo.py 里同名的测试）。
    assert sha(PARITY_DOC) == PARITY_HASH
    assert (
        head["plan_hash"]
        == hashlib.sha256(
            json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert head["judge"] == doc["judge"] and head["judge"]["seconds_per_item"] == 40
    assert head["caps"] == {"per_question_usd_milli": 90, "total_usd_milli": 1080}
    write_json(plan, {**doc, "judge": {**doc["judge"], "seconds_per_item": None}})
    argv[2] = str(tmp_path / "b2")
    assert pici.main(argv) == 2 and not (tmp_path / "b2").exists()  # 计划里没有时限：不登记


# ---------------------------------------------------------------- 整批：接着做、没做成、重判


def test_batch_resumes_counts_judge_failures_and_rejudges_a_fifth(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    atts = [attempt("B", f"q{q}", r, f"1: 甲{q}{r}\n2: 乙") for q in (1, 2, 3) for r in (1, 2)]
    atts.append(attempt("B2", "q1", 1, "1: 坏掉\n2: 乙"))
    bdir, qpath, jpath = make_batch(tmp_path, atts)

    def flaky(p):
        if "坏掉" in p["回答原文"]:
            return {"oops": 1}
        return lines_as_claims(p)

    fake = Fake(flaky, by_marks, by_words)
    assert mangpan.run_judge(ns(bdir, qpath, jpath), fake) == 0
    assert len(list((bdir / "verdicts").glob("*.json"))) == 6
    assert len(read_json(bdir / "judge_failures.json")) == 1
    n = len(fake.seen)
    assert mangpan.run_judge(ns(bdir, qpath, jpath), Fake(lines_as_claims, by_marks, by_words)) == 0
    assert len(list((bdir / "verdicts").glob("*.json"))) == 7 and n > 0  # 判过的不重判，上次没做成的补上
    calls = read_jsonl(bdir / "judge_calls.jsonl")
    assert {c["stage"] for c in calls} == set(mangpan.STAGES) and all(c["model"] == "fake-judge" for c in calls)
    assert mangpan.run_rejudge(ns(bdir, qpath, jpath), simple()) == 0
    assert read_json(bdir / "rejudge.json") == {"v": 1, "chosen": 2, "agree": 2, "failed": 0}


def test_rejudge_reports_the_agreement_rate_and_counts_a_changed_conclusion(tmp_path, monkeypatch, capsys):
    """重判一致率报出：重判五分之一，第二遍结论变了的不算一致，比例写进 rejudge.json、打在屏幕上、进汇总。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    atts = [attempt("B", f"q{q}", r, f"1: 甲{q}{r}\n2: 乙") for q in (1, 2, 3) for r in (1, 2)]
    atts += [attempt("B2", f"q{q}", r, f"1: 丙{q}{r}\n2: 乙") for q in (1, 2, 3) for r in (1, 2)]
    bdir, qpath, jpath = make_batch(tmp_path, atts)
    assert mangpan.run_judge(ns(bdir, qpath, jpath), simple()) == 0

    def strict_read(p):  # 第二遍换了一个什么都判成没答到的：结论全变
        doc = by_marks(p)
        for r in doc["subquestions"]:
            r.update(verdict="missing", mechanism="没有说到")
        return doc

    capsys.readouterr()
    assert mangpan.run_rejudge(ns(bdir, qpath, jpath), Fake(lines_as_claims, strict_read, by_words)) == 0
    assert read_json(bdir / "rejudge.json") == {"v": 1, "chosen": 3, "agree": 0, "failed": 0}
    assert "重判一致率 0/3" in capsys.readouterr().out
    assert mangpan.run_rejudge(ns(bdir, qpath, jpath), simple()) == 0
    assert "重判一致率 3/3" in capsys.readouterr().out
    from liangju import huizong

    check = huizong.build(bdir, qpath)["量具自检"]
    assert check["重判一致率"].startswith("3/3")
    assert check["自检时每个题次的盲判用时（秒）"] == dict.fromkeys(SAMPLES, 30.0)
    assert huizong.build(bdir, qpath)["批次头"]["每题次的盲判时限（秒）"] == "无"


def test_summary_reports_median_and_max_seconds_of_the_real_judging_with_or_without_a_limit(tmp_path, monkeypatch):
    """正式判每题次用时的中位数与最大值，有没有时限都报：起点轮跑完就能拿它与自检的用时比出倍数。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    from liangju import huizong

    def build(where, reg, seconds):
        where.mkdir()
        atts = [attempt("B", f"q{q}", 1, f"1: 甲{q}\n2: 乙") for q in (1, 2, 3)]
        atts += [attempt("B1", f"q{q}", 1, f"1: 丙{q}\n2: 乙") for q in (1, 2)]
        arms = reg.get("arms") or {"B": ARMS["B"], "B1": ARMS["B2"]}
        bdir, qpath, jpath = make_batch(where, atts, **{**reg, "arms": arms})
        assert mangpan.run_judge(ns(bdir, qpath, jpath), simple()) == 0
        index = {(r["arm"], r["question"]): r["blind"] for r in read_json(bdir / "index.json")}
        for key, sec in seconds.items():
            f = bdir / "verdicts" / f"{index[key]}.json"
            write_json(f, {**read_json(f), "seconds": sec})
        return huizong.build(bdir, qpath)

    seconds = {("B", "q1"): 10.0, ("B", "q2"): 50.0, ("B", "q3"): 20.0, ("B1", "q1"): 400.0, ("B1", "q2"): 30.0}
    want = {"份数": 5, "中位数": 30.0, "最大值": 400.0}
    free = build(tmp_path / "无计划", {}, seconds)
    assert free["量具自检"]["正式判每题次的盲判用时（秒）"] == want
    assert free["量具自检"]["正式判时用时超过时限的回答份数"] == "无（没有时限）"
    bound = build(tmp_path / "有计划", pici.from_plan(real_plan()), seconds)
    assert bound["量具自检"]["正式判每题次的盲判用时（秒）"] == want
    assert bound["批次头"]["每题次的盲判时限（秒）"] == 40 and bound["量具自检"]["正式判时用时超过时限的回答份数"] == 2
    assert [a["计量来源"] for a in bound["逐臂登记"]["各臂"]] == ["ledger"] * 3  # 计划的词表原样带到汇总


# ---------------------------------------------------------------- 只读工具


def test_a_search_that_runs_past_the_time_limit_is_stopped_and_counted(tmp_path):
    """模型给的正则在一行上回溯个没完：到时限就停，按「没有搜到」回给模型，并记一笔。别的搜索照常。"""
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "a.txt").write_text("a" * 60 + "!\nMAX = 1\n", encoding="utf-8")
    box = Toolbox(snap, search_seconds=1.0)
    t0 = time.monotonic()
    out = box.run("search", {"pattern": r"^(a+)+$"})
    assert time.monotonic() - t0 < 10 and out.startswith("没有搜到（这次搜索超过了 1 秒的上限")
    assert box.timeouts == 1
    assert box.run("search", {"pattern": "MAX"}) == "a.txt:2:MAX = 1" and box.timeouts == 1


def test_search_timeouts_are_written_into_the_verdict(tmp_path, monkeypatch):
    class Slow(Toolbox):
        def __init__(self, root):
            super().__init__(root)
            self.timeouts = 2

    monkeypatch.setattr(mangpan, "Toolbox", Slow)
    v = mangpan.judge(item("1: 甲\n2: 乙"), simple(), Ledger(None), "seed")
    assert v["search_timeouts"] == 2


def test_toolbox_sees_only_the_snapshot(tmp_path):
    box = Toolbox(CANARY / "snapshot")
    assert "relay/" in box.run("list_dir", {"path": "."})
    assert "3\tMAX_BATCH = 16" in box.run("read_file", {"path": "relay/config.py", "start": 2, "end": 4})
    assert "relay/config.py:3:MAX_BATCH = 16" in box.run("search", {"pattern": r"MAX_BATCH\s*="})
    for bad in ("../question.json", "/etc/passwd", "relay/../../expected.json"):
        assert "路径在快照之外" in box.run("read_file", {"path": bad})
    assert "没做成" in box.run("search", {"pattern": "("}) and "没有这个工具" in box.run("write_file", {})
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET")
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "link").symlink_to(outside)
    assert "SECRET" not in Toolbox(snap).run("read_file", {"path": "link"})
    assert "SECRET" not in Toolbox(snap).run("search", {"pattern": "SECRET"})


def test_check_uses_tools_then_concludes_and_is_told_when_lookups_run_out(monkeypatch):
    fake = Fake(None, None, by_words, lookups=3)
    it = item("1: 甲")
    v = mangpan.check(it, 0, {"at": [3, 4], "cite": ""}, fake, Ledger(None), Toolbox(it.snapshot))
    assert v["verdict"] == "holds" and any("relay/config.py:3" in t for t in fake.tools_seen)
    monkeypatch.setattr(mangpan, "STEPS", 2)
    stubborn = Fake(None, None, by_words, lookups=99)
    with pytest.raises(mangpan.JudgeFailed):  # 到了上限还在查、不下结论：这一条算盲判没做成
        mangpan.check(it, 0, {"at": [3, 4], "cite": ""}, stubborn, Ledger(None), Toolbox(it.snapshot))
    assert any("不要再调用工具" in t for t in stubborn.tools_seen)
