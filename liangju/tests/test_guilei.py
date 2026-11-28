"""归类器：登记簿、固定版本的一次判断、换题重现集上的四项、金丝雀、整批与汇总。"""

import argparse
import json
import re

import pytest
from lj_rig import JUDGE, attempt, make_batch, simple

from liangju import guilei, huizong, mangpan
from liangju.common import Refused, read_json, read_jsonl, write_json
from liangju.model import Ledger, ModelError, Turn

SET = guilei.test_set()
GROUP = {guilei.tidy(s): f"g{g['id']}" for g in SET["groups"] for s in g["sentences"]}
BASE = sorted(GROUP, key=lambda t: guilei.sha(t.encode()))  # 测试用的那个处理顺序
GROUP |= {SET["canary"]["seed"]: "c-seed", SET["canary"]["paraphrase"]: "c-seed", SET["canary"]["novel"]: "c-novel"}


def book(user: str) -> tuple[str, dict[int, str]]:
    """从送给模型的文字里读回新发现与登记簿的代表句。"""
    new = user.split("【新发现】\n")[1].split("\n\n【登记簿】")[0]
    return new, {int(n): rep for n, rep in re.findall(r"(\d+) 号\n  代表句：(.+)", user)}


class Oracle:
    """懂机制的假模型：两句话的机制（`key`）相同就归到一起。"""

    def __init__(self, key=None) -> None:
        self.key = key or (lambda t: GROUP.get(t, t))
        self.calls: list[str] = []

    def answer(self, new: str, reps: dict[int, str]):
        return next((n for n, rep in reps.items() if self.key(rep) == self.key(new)), "new")

    def chat(self, system, messages, tools=None):
        assert system == guilei.prompt()
        user = messages[0]["text"]
        self.calls.append(user)
        return Turn(
            json.dumps({"class": self.answer(*book(user))}), [], {"input": 9, "cached_input": 0, "output": 1}, "m"
        )


class Splitter(Oracle):  # 什么都算新类别
    def answer(self, new, reps):
        return "new"


class Lumper(Oracle):  # 什么都并进第一类
    def answer(self, new, reps):
        return 1


class OrderBound(Oracle):  # 只看排在第几个：挨着的三条归一类，换个顺序就是另一种划分
    def chat(self, system, messages, tools=None):
        self.full = messages[0]["text"].rsplit(" 号\n", 1)[1].count("例句：") >= 2  # 最近一类已经有三条了
        return super().chat(system, messages, tools)

    def answer(self, new, reps):
        return "new" if self.full else max(reps)


class BaseOnly(Oracle):
    """测试用的那个顺序上全对，换一个顺序就把同机制的句子拆开（只认哈希是偶数的那一半）。"""

    def chat(self, system, messages, tools=None):
        user = messages[0]["text"]
        if user.count(" 号\n") == 1 and "例句：" not in user:  # 一遍的第二句：看这一遍是不是测试用的那个顺序
            new, reps = book(user)
            self.base = [reps[1], new] == BASE[:2]
        return super().chat(system, messages, tools)

    def answer(self, new, reps):
        if self.base or int(guilei.sha(new.encode())[:2], 16) % 2 == 0:
            return super().answer(new, reps)
        return "new"


class Moody(Oracle):  # 同样的输入，两遍答得不一样：第一遍照机制答，之后隔一句拆一句
    def answer(self, new, reps):
        late = len(self.calls) > len(BASE) - 1
        return "new" if late and len(self.calls) % 2 else super().answer(new, reps)


def cfg():
    return guilei.JudgeModel.load({**JUDGE})


# ---------------------------------------------------------------- 登记簿与一次判断


def test_the_registry_keeps_a_number_a_first_sentence_and_at_most_three_examples():
    reg = guilei.new_registry(cfg())
    one = [guilei.tidy(s) for s in SET["groups"][0]["sentences"]]
    more = [*one, "同一个机制的第四种说法", "第五种说法", "第六种说法"]
    key = lambda t: "同" if t in more else t  # noqa: E731
    fake = Oracle(key)
    got = [guilei.assign(reg, t, fake, Ledger(None)) for t in more]
    assert got == [(1, True), *[(1, False)] * 5]
    assert reg["classes"] == [{"id": 1, "rep": one[0], "examples": more[1:4]}]  # 没有名字；例句至多三条
    assert len(fake.calls) == 5  # 登记簿是空的那一次不用问
    assert guilei.assign(reg, one[0], fake, Ledger(None)) == (1, False) and len(fake.calls) == 5  # 逐字相同：不再问
    assert guilei.assign(reg, "另一个机制", fake, Ledger(None)) == (2, True)
    assert "1 号\n  代表句：" + one[0] in fake.calls[-1] and "例句：" + more[3] in fake.calls[-1]
    assert "第五种说法" not in fake.calls[-1]  # 送去的只有编号、代表句与例句


def test_the_answer_is_only_a_class_number_or_new_and_anything_else_is_retried_once_then_fails():
    classes = [{"id": 1, "rep": "甲", "examples": []}]

    class Scripted:
        def __init__(self, *replies):
            self.replies = list(replies)
            self.users = []

        def chat(self, system, messages, tools=None):
            self.users.append(messages[0]["text"])
            r = self.replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return Turn(r, [], {"input": 1, "cached_input": 0, "output": 1}, "m")

    assert guilei.ask("乙", classes, Scripted('{"class": 1}'), Ledger(None)) == 1
    assert guilei.ask("乙", classes, Scripted('好的：{"class": "new"}'), Ledger(None)) is None
    retry = Scripted('{"class": 7}', '{"class": 1}')  # 登记簿里没有 7 号
    assert guilei.ask("乙", classes, retry, Ledger(None)) == 1 and "上一次的输出不合要求" in retry.users[1]
    for bad in (('{"class": true}', "不知道"), ('{"类别": 1}', '{"class": "合并 1 和 2"}'), (ModelError("断了"),)):
        with pytest.raises(guilei.ClassifyFailed):
            guilei.ask("乙", classes, Scripted(*bad), Ledger(None))


def test_the_version_changes_with_the_prompt_the_two_counts_or_the_test_set(monkeypatch, capsys):
    before = guilei.version()
    assert guilei.main(["version"]) == 0
    assert json.loads(capsys.readouterr().out) == {"id": guilei.version_id(), **before}
    real = guilei.prompt()
    monkeypatch.setattr(guilei, "prompt", lambda: real + "。")
    assert guilei.version()["prompt"] != before["prompt"]
    monkeypatch.undo()
    monkeypatch.setattr(guilei, "EXAMPLES", 2)
    assert guilei.version() != before
    monkeypatch.undo()
    monkeypatch.setattr(guilei, "SHUFFLES", 5)  # 打乱几次也是版本的一部分
    assert guilei.version() != before
    monkeypatch.undo()
    changed = {**SET, "canary": {**SET["canary"], "novel": "换了一句"}}
    monkeypatch.setattr(guilei, "test_set", lambda: changed)
    assert guilei.version()["set"] != before["set"]


# ---------------------------------------------------------------- 7.3 的四项


def test_the_committed_set_has_same_mechanism_pairs_and_different_mechanism_pairs():
    groups = SET["groups"]
    texts = [guilei.tidy(s) for g in groups for s in g["sentences"]]
    assert len(groups) >= 10 and all(len(g["sentences"]) >= 2 for g in groups) and len(set(texts)) == len(texts)
    assert set(SET["canary"]) == {"seed", "paraphrase", "novel"} and not set(SET["canary"].values()) & set(texts)
    names = mangpan.identifiers(mangpan.HERE / "canary" / "snapshot")
    assert not any(mangpan.scrub(t, names)[1] for t in texts)  # 句子里没有专有名词


def test_a_classifier_that_reads_the_mechanism_passes_all_four():
    doc = guilei.evaluate(Oracle(), Ledger(None))
    n = sum(len(g["sentences"]) for g in SET["groups"])
    assert doc["ok"] and doc["sentences"] == n and doc["classes"] == len(SET["groups"])
    assert doc["split_error"] == doc["merged_error"] == 0 and doc["order_agreement"] == 1 and doc["repeat_identical"]
    assert doc["pairs"]["same"][1] + doc["pairs"]["different"][1] == n * (n - 1) // 2
    assert doc["line"] == 0.9 == guilei.LINE and doc["classifier"] == guilei.version()
    same = doc["pairs"]["same"][1]
    assert (
        doc["shuffles"]
        == [{"both": same, "either": same, "agreement": 1.0, "same_rate": 1.0, "classes": len(SET["groups"])}]
        * guilei.SHUFFLES
        and guilei.SHUFFLES == 3
    )


def test_a_classifier_that_splits_the_same_mechanism_in_any_other_order_fails_order_stability():
    """测试用的顺序上全对、换一个顺序就拆的归类器：前两项与重复稳定都看不出来，顺序稳定这一项要拦住。

    全部的对一起数的话，绝大多数是两遍都不同类的对，一致率照样在线上；所以一致率只数至少有一遍同类的对。"""
    doc = guilei.evaluate(BaseOnly(), Ledger(None))
    assert doc["split_error"] == doc["merged_error"] == 0 and doc["repeat_identical"]
    assert doc["order_agreement"] < guilei.LINE and not doc["ok"]
    assert doc["order_agreement"] == min(s["agreement"] for s in doc["shuffles"])
    n, same = doc["sentences"], doc["pairs"]["same"][1]
    for s in doc["shuffles"]:
        assert s["either"] == same and s["agreement"] == s["same_rate"] == round(s["both"] / same, 4)
        assert s["classes"] > len(SET["groups"])
        assert 1 - (s["either"] - s["both"]) / (n * (n - 1) // 2) >= guilei.LINE  # 全部的对一起数：拦不住


def test_order_stability_has_no_pairs_to_count_when_nothing_is_ever_put_together():
    doc = guilei.evaluate(Splitter(), Ledger(None))
    assert doc["order_agreement"] == 1.0 and not doc["ok"]  # 什么都不并：这一项无对可数，由拆多了那一项拦


def test_the_set_has_sentences_shaped_like_real_records():
    """照真记录的样子：专有名词换成了占位符、数字留着、运行没有正常结束的状态与超出花费上限各自成组。"""
    by = {g["id"]: [guilei.tidy(s) for s in g["sentences"]] for g in SET["groups"]}
    texts = [t for ts in by.values() for t in ts]
    held = [t for t in texts if "〔名〕" in t]
    assert len(held) >= 6 and sum(1 for t in held if re.search(r"\d", t)) >= 3
    assert len({g for g, ts in by.items() if any("〔名〕" in t for t in ts)}) >= 5  # 不是都挤在一组里
    states = {t.split("：", 1)[1].split("（")[0] for t in texts if t.startswith("运行没有正常结束：")}
    assert len(states) >= 3
    apart = [next(g for g, ts in by.items() if any(t.startswith(f"运行没有正常结束：{s}") for t in ts)) for s in states]
    assert len(set(apart)) == len(states)  # 一种状态一组
    over = next(g for g, ts in by.items() if "运行结束了，花费超出每题上限" in ts)
    assert over not in apart


@pytest.mark.parametrize(
    ("fake", "fails"),
    [
        (Splitter, "split_error"),  # 换题重现：同机制的对没落进同一类
        (Lumper, "merged_error"),  # 换题重现：不同机制的对落进了同一类
        (OrderBound, "order_agreement"),  # 顺序稳定
        (Moody, "repeat_identical"),  # 重复稳定
    ],
)
def test_each_of_the_four_checks_catches_its_own_kind_of_bad_classifier(fake, fails):
    doc = guilei.evaluate(fake(), Ledger(None))
    assert not doc["ok"]
    if fails == "split_error":
        assert doc["split_error"] == 1.0 and doc["merged_error"] == 0
    elif fails == "merged_error":
        assert doc["merged_error"] == 1.0 and doc["split_error"] == 0
    elif fails == "order_agreement":
        assert doc["order_agreement"] < guilei.LINE
    else:
        assert not doc["repeat_identical"]


def test_the_line_is_ninety_percent_on_each_rate(monkeypatch):
    """合格线 90%（P3）：三个比例各自都要不低于它，差一点也不行。"""
    texts = [guilei.tidy(s) for g in SET["groups"] for s in g["sentences"]]

    def with_slips(k: int):  # 把前 k 组各拆出一句：n 句的一组少掉 n-1 对同机制的对
        odd = {guilei.tidy(g["sentences"][-1]) for g in SET["groups"][:k]}
        return Oracle(lambda t: t if t in odd else GROUP.get(t, t))

    def lost(k: int) -> int:
        return sum(len(g["sentences"]) - 1 for g in SET["groups"][:k])

    same = sum(len(g["sentences"]) * (len(g["sentences"]) - 1) // 2 for g in SET["groups"])
    k = max(k for k in range(len(SET["groups"])) if (same - lost(k)) / same >= 0.9)
    assert k >= 1
    ok = guilei.evaluate(with_slips(k), Ledger(None))
    assert ok["pairs"]["same"] == [same - lost(k), same] and ok["ok"] and ok["order_agreement"] == 1
    bad = guilei.evaluate(with_slips(k + 1), Ledger(None))
    assert bad["pairs"]["same"] == [same - lost(k + 1), same] and (same - lost(k + 1)) / same < 0.9 and not bad["ok"]
    assert bad["merged_error"] == 0 and len(texts) == ok["sentences"]


def test_canaries_a_paraphrase_adds_no_class_and_a_new_one_does_and_the_registry_is_untouched():
    reg = guilei.new_registry(cfg())
    guilei.assign(reg, "先有一类", Oracle(), Ledger(None))
    frozen = json.dumps(reg, ensure_ascii=False, sort_keys=True)
    passed = {"paraphrase_kept": True, "novel": "added", "state": "passed"}
    assert guilei.canary(reg, Oracle(), Ledger(None)) == passed
    assert guilei.canary(reg, Splitter(), Ledger(None)) == {**passed, "paraphrase_kept": False, "state": "wrong"}
    assert guilei.canary(reg, Lumper(), Ledger(None)) == {**passed, "novel": "merged_with_seed", "state": "wrong"}
    assert json.dumps(reg, ensure_ascii=False, sort_keys=True) == frozen


SAME_AS_NOVEL = "整篇回答都在寒暄，没有一句落在子问上"  # 与金丝雀里「确实全新的那一句」同一个机制


def knows_novel() -> Oracle:
    return Oracle(lambda t: "c-novel" if t == SAME_AS_NOVEL else GROUP.get(t, t))


def test_a_canary_whose_new_sentence_already_has_a_class_in_the_registry_is_untestable_not_wrong():
    """「全新」只是相对当时的登记簿：登记簿里有了同一机制的类别，新句就不再增类。这不是判错，单独一种状态。"""
    reg = guilei.new_registry(cfg())
    guilei.assign(reg, "先有一类", knows_novel(), Ledger(None))
    assert guilei.canary(reg, knows_novel(), Ledger(None))["state"] == "passed"
    guilei.assign(reg, SAME_AS_NOVEL, knows_novel(), Ledger(None))
    frozen = json.dumps(reg, ensure_ascii=False, sort_keys=True)
    got = guilei.canary(reg, knows_novel(), Ledger(None))
    assert got == {"paraphrase_kept": True, "novel": "class_exists", "state": "untestable"}
    assert json.dumps(reg, ensure_ascii=False, sort_keys=True) == frozen

    class AlsoSplits(Oracle):  # 同时把换述拆开了：判错盖过测不了
        def answer(self, new, reps):
            return "new" if GROUP.get(new) == "c-seed" else knows_novel().answer(new, reps)

    assert guilei.canary(reg, AlsoSplits(), Ledger(None)) == {**got, "paraphrase_kept": False, "state": "wrong"}


# ---------------------------------------------------------------- 整批


WHY, PART = SET["groups"][0]["sentences"][:2], SET["groups"][1]["sentences"][:2]


def judged_batch(tmp, bid: str, answers: dict[tuple[str, str], str], code: str = "SET-A"):
    """搭一个判过的批次。回答里的「错甲」「错乙」各变成一条被原文否定的发现，句子由假盲判按题给。"""
    tmp.mkdir()
    atts = [attempt(arm, q, 1, text) for (arm, q), text in answers.items()]
    bdir, qpath, jpath = make_batch(tmp, atts, id=bid, question_set={"code": code, "source": "手出"})
    assert mangpan.run_judge(argparse.Namespace(batch=str(bdir), questions=str(qpath), judge=str(jpath),
                                                selfcheck=None, jobs=1), simple()) == 0  # fmt: skip
    return bdir, qpath


def rewrite(bdir, sentences: dict[tuple[str, str], str]) -> None:
    """把每条发现的那句话换成指定的句子（按臂与题），哈希重算：归类器只读这句话。"""
    rows = read_jsonl(bdir / "findings.jsonl")
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k != "hash"}
        r["text"] = sentences.get((r["at"]["arm"], r["at"]["question"]), r["text"])
        out.append({**r, "hash": guilei.sha(r)})
    (bdir / "findings.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), "utf-8")


def setup(tmp_path, monkeypatch, fake=None):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    model, ev = tmp_path / "model.json", tmp_path / "guilei_eval.json"
    write_json(model, JUDGE)
    code = guilei.run_evaluate(argparse.Namespace(model=str(model), out=str(ev)), fake or Oracle())
    return model, ev, code


def classify(tmp_path, model, ev, *bdirs, fake=None, registry="registry.json"):
    a = argparse.Namespace(
        batch=[str(b) for b in bdirs], registry=str(tmp_path / registry), model=str(model), eval=str(ev)
    )
    return guilei.run_classify(a, fake or Oracle())


BAD = "1: 甲\n2: 这条是错的"
GOOD = "1: 甲\n2: 乙"


def test_the_same_problem_on_another_question_lands_in_the_existing_class(tmp_path, monkeypatch):
    """换题重现：同一个机制换一道题、换一批再出现，落到已有的类别上；新机制才增类。只回编号与计数。"""
    model, ev, code = setup(tmp_path, monkeypatch)
    assert code == 0
    one, q1 = judged_batch(tmp_path / "一", "S0-1", {("B", "q1"): BAD, ("B2", "q1"): BAD, ("B", "q2"): GOOD})
    rewrite(one, {("B", "q1"): WHY[0], ("B2", "q1"): PART[0]})
    assert classify(tmp_path, model, ev, one) == 0
    first = read_json(one / "classes.json")
    assert [c["id"] for c in first["classes"]] == [1, 2] and all(c["new_in_batch"] for c in first["classes"])
    assert first["cumulative"] == {
        "classes": 2,
        "singletons": 2,
        "findings": 2,
        "unseen_probability": 1.0,
        "questions": 2,
    }

    two, _ = judged_batch(tmp_path / "二", "S0-2", {("B", "q3"): BAD, ("B2", "q3"): BAD, ("B2", "q2"): BAD}, "SET-B")
    rewrite(two, {("B", "q3"): WHY[1], ("B2", "q3"): "一个从没见过的机制", ("B2", "q2"): PART[1]})
    assert classify(tmp_path, model, ev, two) == 0
    second = read_json(two / "classes.json")
    rows = {c["id"]: c for c in second["classes"]}
    assert rows[1] == {"id": 1, "questions": 1, "arms": ["B"], "new_in_batch": False}  # 换述落进已有的类
    assert rows[2]["arms"] == ["B2"] and not rows[2]["new_in_batch"] and rows[3]["new_in_batch"]
    assert second["cumulative"] == {
        "classes": 3,
        "singletons": 1,
        "findings": 5,
        "unseen_probability": 0.2,
        "questions": 4,  # 两批各两道题，题集代号不同
    }
    assert second["per_arm"]["B"] == {"classes": 1, "singletons": 0, "findings": 2, "unseen_probability": 0.0}
    assert second["per_arm"]["B2"]["classes"] == 2 and second["per_arm"]["B2"]["findings"] == 3
    assert (
        second["canary"]["state"] == "passed"
        and second["curve_point_counts"]
        and second["classifier"] == guilei.version_id()
    )
    assert second["evaluation"] == {
        "split_error": 0.0,
        "merged_error": 0.0,
        "order_agreement": 1.0,
        "repeat_identical": True,
        "shuffles": guilei.SHUFFLES,
    }
    reg = read_json(tmp_path / "registry.json")
    assert reg["batches"] == ["S0-1", "S0-2"] and len(reg["assigned"]) == 5 and len(reg["classes"]) == 3
    assert not any(
        k.startswith("c-") for k in map(GROUP.get, (c["rep"] for c in reg["classes"])) if k
    )  # 金丝雀没有落进登记簿
    blob = json.dumps([first, second], ensure_ascii=False)
    assert WHY[0] not in blob and "从没见过" not in blob and "代表句" not in blob  # 批次里的结果不带那句话

    with pytest.raises(Refused) as e:
        classify(tmp_path, model, ev, two)
    assert "已经归过类" in str(e.value)


def test_recomputing_the_same_records_gives_the_same_partition_whatever_order_the_file_is_in(tmp_path, monkeypatch):
    model, ev, _ = setup(tmp_path, monkeypatch)
    answers = {(arm, q): BAD for arm in ("B", "B2") for q in ("q1", "q2", "q3")}
    sentences = dict(zip(answers, [*WHY, *PART, "第三种机制", "第三种机制"], strict=True))
    one, _ = judged_batch(tmp_path / "一", "S0-1", answers)
    rewrite(one, sentences)
    assert classify(tmp_path, model, ev, one) == 0
    again, _ = judged_batch(tmp_path / "二", "S0-1", answers)
    rewrite(again, sentences)
    rows = (again / "findings.jsonl").read_text("utf-8").splitlines()
    (again / "findings.jsonl").write_text("\n".join(reversed(rows)) + "\n", "utf-8")  # 文件里的顺序倒过来
    assert classify(tmp_path, model, ev, again, registry="registry2.json") == 0
    a, b = read_json(tmp_path / "registry.json"), read_json(tmp_path / "registry2.json")
    assert a["assigned"] == b["assigned"] and a["classes"] == b["classes"] and len(a["classes"]) == 3
    assert read_json(one / "classes.json") == read_json(again / "classes.json")


def test_classify_refuses_without_a_passing_evaluation_for_this_model_and_version(tmp_path, monkeypatch):
    model, ev, _ = setup(tmp_path, monkeypatch)
    one, _ = judged_batch(tmp_path / "一", "S0-1", {("B", "q1"): BAD})
    good = read_json(ev)

    def refused(**change) -> str:
        write_json(ev, {**good, **change})
        with pytest.raises(Refused) as e:
            classify(tmp_path, model, ev, one)
        assert not (one / "classes.json").exists() and not (tmp_path / "registry.json").exists()
        return str(e.value)

    assert "四项没有全部合格" in refused(ok=False)
    assert "不是这个模型" in refused(model="另一个模型")
    assert "不是这个模型" in refused(model_version="8")
    assert "不是这个模型" in refused(classifier={**good["classifier"], "prompt": "旧的一版"})
    ev.unlink()
    with pytest.raises(Refused) as e:
        classify(tmp_path, model, ev, one)
    assert "没有归类器的测试记录" in str(e.value)
    assert (
        setup(tmp_path, monkeypatch, Splitter())[2] == 1 and not read_json(ev)["ok"]
    )  # 不合格的归类器：记录照写，不启用
    with pytest.raises(Refused):
        classify(tmp_path, model, ev, one)


def test_a_registry_from_another_version_cannot_be_continued_and_all_batches_are_recomputed(tmp_path, monkeypatch):
    """要合要拆只能改归类器的版本，然后全部记录按新版本重算；不能接着旧登记簿，也不能手改某一条的归属。"""
    model, ev, _ = setup(tmp_path, monkeypatch)
    one, _ = judged_batch(tmp_path / "一", "S0-1", {("B", "q1"): BAD})
    two, _ = judged_batch(tmp_path / "二", "S0-2", {("B", "q2"): BAD})
    rewrite(one, {("B", "q1"): WHY[0]})
    rewrite(two, {("B", "q2"): WHY[1]})
    assert classify(tmp_path, model, ev, one) == 0
    real = guilei.prompt()
    monkeypatch.setattr(guilei, "prompt", lambda: real + "\n新加的一条尺度。")

    class NewOracle(Oracle):
        def chat(self, system, messages, tools=None):
            return Oracle.chat(self, guilei.prompt(), messages, tools)

    assert guilei.run_evaluate(argparse.Namespace(model=str(model), out=str(ev)), NewOracle()) == 0
    with pytest.raises(Refused) as e:
        classify(tmp_path, model, ev, two, fake=NewOracle())
    assert "全部记录按新版本重算" in str(e.value) and not (two / "classes.json").exists()
    assert (
        classify(tmp_path, model, ev, one, two, fake=NewOracle(), registry="registry-v2.json") == 0
    )  # 历次批次按顺序给上
    reg = read_json(tmp_path / "registry-v2.json")
    assert reg["batches"] == ["S0-1", "S0-2"] and len(reg["classes"]) == 1 and reg["classifier"] == guilei.version()
    assert read_json(two / "classes.json")["cumulative"]["findings"] == 2


def test_a_failed_call_leaves_the_registry_and_every_batch_untouched(tmp_path, monkeypatch):
    model, ev, _ = setup(tmp_path, monkeypatch)
    one, _ = judged_batch(tmp_path / "一", "S0-1", {("B", "q1"): BAD})
    two, _ = judged_batch(tmp_path / "二", "S0-2", {("B", "q2"): BAD})
    rewrite(two, {("B", "q2"): "第二批里的另一个机制"})

    class Breaks(Oracle):
        def chat(self, system, messages, tools=None):
            if "第二批里的另一个机制" in messages[0]["text"].split("【登记簿】")[0]:
                raise ModelError("端点断了")
            return super().chat(system, messages, tools)

    with pytest.raises(Refused) as e:
        classify(tmp_path, model, ev, one, two, fake=Breaks())
    assert "登记簿没有动" in str(e.value)
    assert not (tmp_path / "registry.json").exists() and not (one / "classes.json").exists()


def test_a_wrong_canary_voids_the_curve_point_and_findings_without_a_sentence_are_counted_apart(tmp_path, monkeypatch):
    model, ev, _ = setup(tmp_path, monkeypatch)
    one, qpath = judged_batch(tmp_path / "一", "S0-1", {("B", "q1"): BAD, ("B2", "q1"): BAD})
    rewrite(one, {("B", "q1"): WHY[0], ("B2", "q1"): "  "})

    class LaterSplits(Oracle):  # 测试时合格，正式跑的时候把换述也拆开了
        def answer(self, new, reps):
            return "new" if GROUP.get(new, "").startswith("c-") else super().answer(new, reps)

    assert classify(tmp_path, model, ev, one, fake=LaterSplits()) == 0
    doc = read_json(one / "classes.json")
    assert doc["canary"] == {"paraphrase_kept": False, "novel": "added", "state": "wrong"}
    assert not doc["curve_point_counts"]
    assert doc["unsentenced_in_batch"] == 1 and doc["cumulative"]["findings"] == 1
    summary = huizong.build(one, qpath)
    got = summary["发现与类别"]["类别"]
    assert got["这一批的曲线点作数"] is False and got["金丝雀"] == {
        "结果": "判错：这一批的曲线点不作数",
        "已有类别的换述没有增类": False,
        "确实全新的那一句": "增了类",
    }
    assert got["这一批没有写机制、没法归类的发现数"] == 1


def test_an_untestable_canary_is_reported_apart_from_a_wrong_one_and_the_curve_point_stands(
    tmp_path, monkeypatch, capsys
):
    model, ev, _ = setup(tmp_path, monkeypatch)
    one, qpath = judged_batch(tmp_path / "一", "S0-1", {("B", "q1"): BAD, ("B2", "q1"): BAD})
    rewrite(one, {("B", "q1"): WHY[0], ("B2", "q1"): SAME_AS_NOVEL})
    capsys.readouterr()
    assert classify(tmp_path, model, ev, one, fake=knows_novel()) == 0
    assert "这一批测不了增类，要换那一句（版本改动）" in capsys.readouterr().out
    doc = read_json(one / "classes.json")
    assert doc["canary"] == {"paraphrase_kept": True, "novel": "class_exists", "state": "untestable"}
    assert doc["curve_point_counts"] and doc["cumulative"]["classes"] == 2
    got = huizong.build(one, qpath)["发现与类别"]["类别"]
    assert got["这一批的曲线点作数"] is True and got["金丝雀"] == {
        "结果": "测不了增类：新句在登记簿里已有同类，不算判错；要换那一句（归类器的版本改动）",
        "已有类别的换述没有增类": True,
        "确实全新的那一句": "落进了登记簿里已有的另一类",
    }


def test_the_summary_carries_class_numbers_and_counts_and_never_the_sentences(tmp_path, monkeypatch):
    model, ev, _ = setup(tmp_path, monkeypatch)
    one, qpath = judged_batch(tmp_path / "一", "S0-1", {("B", "q1"): BAD, ("B2", "q1"): BAD, ("B2", "q2"): BAD})
    before = huizong.build(one, qpath)
    assert before["批次头"]["归类器的版本"] == "这一批还没有归类" and "还没有归类" in before["发现与类别"]["类别"]
    rewrite(one, {("B", "q1"): WHY[0], ("B2", "q1"): WHY[1], ("B2", "q2"): "独一份的机制"})
    assert classify(tmp_path, model, ev, one) == 0
    after = huizong.build(one, qpath)
    got = after["发现与类别"]["类别"]
    assert after["批次头"]["归类器的版本"] == guilei.version_id()
    assert got["每个类别一行"] == [
        {"类别编号": 1, "这一批出现的题数": 1, "出现在哪几条臂": ["B", "B2"], "这一批才第一次出现": True},
        {"类别编号": 2, "这一批出现的题数": 1, "出现在哪几条臂": ["B2"], "这一批才第一次出现": True},
    ]
    assert got["累计"] == {
        "类别数": 2,
        "只出现过一次的类别数": 1,
        "发现总数": 3,
        "下一次失败属于没见过的类别的概率（约）": round(1 / 3, 4),
        "累计跑过的新题数": 2,
    }
    assert set(got["每条臂的曲线点"]) == {"B", "B2"} and got["每条臂的曲线点"]["B2"]["类别数"] == 2
    assert got["归类器在换题重现集上"] == {
        "拆多了的错误率（同机制的对没落进同一类）": 0.0,
        "并多了的错误率（不同机制的对落进了同一类）": 0.0,
        "打乱顺序后的一致率（只数至少有一遍同类的对；打乱 3 次里最低的一次）": 1.0,
        "两遍划分相同": True,
    }
    assert got["金丝雀"]["结果"] == "判对"
    blob = json.dumps(after, ensure_ascii=False)
    assert WHY[0] not in blob and WHY[1] not in blob and "独一份" not in blob
