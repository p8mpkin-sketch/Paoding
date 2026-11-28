"""题目生成器：取样、出题、五项校验、入库与摘要、设计 7.4 的四项测试里机器能做的部分。"""

import argparse
import copy
import json
import shutil
import subprocess

import pytest
from lj_rig import ARMS, CANARY, JUDGE, SAMPLES, attempt, make_batch, parts, simple

from liangju import chuti, mangpan, pici
from liangju.common import Refused, read_json, sha, write_json
from liangju.model import Ledger, ModelError, ToolCall, Turn

SNAP = CANARY / "snapshot"
CASES = chuti.canary()["cases"]
USAGE = {"input": 7, "cached_input": 0, "output": 3}
HOW = {"ask": "how", "premise": "holds", "where": "code"}


def draft(name: str = "good") -> dict:
    return chuti.parse_draft(json.dumps(CASES[name]["draft"]))


def absent_draft() -> dict:
    """前提不成立、而且确实没有：问重试与退避，快照里没有这回事。"""
    d = draft()
    d["text"] = "这个转发器发送失败之后，重试之间等多久？一批至多发多少条？"
    d["subquestions"][0] = {
        "q": "发送失败之后重试之间等多久？",
        "points": [
            {
                "point": "没有重试：发不出去就记一笔、丢掉这一批，不放回队列，也不再试。",
                "evidence": [{"path": "relay/sender.py", "start": 29, "end": 33}],
            }
        ],
    }
    d["absent"] = {
        "sub": 1,
        "searched": ["retry", "backoff"],
        "expected_at": {"path": "relay/sender.py", "start": 27, "end": 33},
        "actual": "捕获异常之后只计数、记日志、返回 0。",
    }
    return d


def doc_draft() -> dict:
    d = draft()
    d["subquestions"][1]["points"][0]["evidence"] = [{"path": "README.md", "start": 3, "end": 7}]
    return d


def fit(axes: dict) -> dict:
    """照格子给一道过得了程序校验的题。"""
    d = absent_draft() if axes["premise"] == "fails" else draft()
    if axes["where"] == "doc":
        d["subquestions"][1]["points"][0]["evidence"] = [{"path": "README.md", "start": 3, "end": 7}]
    return d


class Setter:
    """出题与独立校验的假模型。出题：先查一次目录，再按格子交一道题（`make` 可以换）。校验：每条要点都说支持，
    除非那一块里有 `unsupported` 里的词。"""

    def __init__(self, make=None, unsupported: tuple[str, ...] = ()) -> None:
        self.make = make or (lambda axes, attempt: fit(axes))
        self.unsupported = unsupported
        self.asked: list[str] = []
        self.checked: list[str] = []
        self.tools: list[str] = []

    def chat(self, system, messages, tools=None):
        user = messages[0]["text"]
        if system == chuti.prompts()["chuti"]:
            assert [t["name"] for t in tools] == ["list_dir", "read_file", "search"]
            if len(messages) == 1:
                self.asked.append(user)
                return Turn("", [ToolCall("c1", "list_dir", {"path": "."})], USAGE, "setter")
            self.tools.append(messages[-1]["text"])
            p = parts(user)
            axes = dict(line.split("：", 1) for line in p["格子"].splitlines())
            cell = {"ask": axes["问法"], "premise": axes["前提"], "where": axes["答案在哪里"]}
            out = self.make(cell, int(p["第几次"][0]))
            return Turn(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False), [], USAGE, "setter")
        assert system == chuti.prompts()["yanti"] and tools is None
        self.checked.append(user)
        blocks = user.split("【答案要点与原文】\n")[1].split("\n\n要点 ")
        rows = [{"n": i, "supported": not any(w in b for w in self.unsupported)} for i, b in enumerate(blocks, 1)]
        return Turn(json.dumps({"points": rows}), [], USAGE, "setter")


class Answerer:
    """不给快照作答的假模型：题面里有「标准库」的算是靠常识答得出的，交一份盲判会判过线的回答；别的答错。"""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def chat(self, system, messages, tools=None):
        assert system == chuti.prompts()["zuoda"] and tools is None and len(messages) == 1
        self.asked.append(messages[0]["text"])
        knows = "标准库" in messages[0]["text"]
        return Turn("1: 甲\n2: 乙" if knows else "1: 这条是错的\n2: 乙", [], USAGE, "answerer")


def models(setter=None) -> chuti.Models:
    return chuti.Models(setter or Setter(), [Answerer()], simple())


QUOTA = {
    "set": "GEN-1",
    "licenses": ["MIT", "Apache-2.0"],
    "sizes": {"小": [0, 1000], "大": [1000, None]},
    "cells": {"Python/小": 2, "Python/大": 1, "Go/小": 1},
    "ask": {"how": 1, "why": 1, "whether": 1, "where": 1},
    "premise": {"holds": 3, "fails": 1},
    "where": {"code": 3, "doc": 1},
}


def cand(i: int, lang: str = "Python", size: int = 10, lic: str = "MIT") -> dict:
    return {"repo": f"o/r{i}", "commit": f"{i:040x}", "language": lang, "size_kb": size, "license": lic}


CANDIDATES = [
    *[cand(i) for i in range(1, 7)],
    *[cand(i, size=5000) for i in range(7, 10)],
    *[cand(i, "Go") for i in range(10, 13)],
]


# ---------------------------------------------------------------- 第 1 步：取样


def test_sampling_fills_every_cell_of_the_quota_and_spreads_the_other_three_axes():
    doc = chuti.sample(CANDIDATES, QUOTA, "种子甲", set())
    slots = doc["slots"]
    assert [s["n"] for s in slots] == [1, 2, 3, 4]
    assert sorted(s["cell"] for s in slots) == ["Go/小", "Python/大", "Python/小", "Python/小"]
    for axis in ("ask", "premise", "where"):
        got = sorted(s["axes"][axis] for s in slots)
        assert got == sorted(v for v, n in QUOTA[axis].items() for _ in range(n))
    assert all(s["axes"]["language"] + "/" + s["axes"]["size"] == s["cell"] for s in slots)
    assert all(len(s["commit"]) == 40 and s["url"] == f"https://github.com/{s['repo']}.git" for s in slots)
    picked = {s["repo"] for s in slots}
    spare = {r["repo"] for rows in doc["spares"].values() for r in rows}
    assert not picked & spare and picked | spare == {c["repo"] for c in CANDIDATES}
    assert doc["counts"]["eligible"] == 12 and doc["set"] == "GEN-1" and doc["quota"] == sha(QUOTA)


def test_the_same_seed_and_quota_give_the_same_repos_and_cells_and_another_seed_does_not():
    """可重复：同样的种子与配额跑两遍，抽到的仓库与各格的分配相同；候选清单里的顺序不影响。"""
    one = chuti.sample(CANDIDATES, QUOTA, "种子甲", set())
    two = chuti.sample(list(reversed(CANDIDATES)), copy.deepcopy(QUOTA), "种子甲", set())
    assert one == two
    other = chuti.sample(CANDIDATES, QUOTA, "种子乙", set())
    assert [s["repo"] for s in other["slots"]] != [s["repo"] for s in one["slots"]] or [
        s["axes"] for s in other["slots"]
    ] != [s["axes"] for s in one["slots"]]
    assert other["candidates"] == one["candidates"] and other["seed"] == "种子乙"


def test_sampling_leaves_out_bad_licenses_used_repos_and_unpinned_candidates():
    base = chuti.sample(CANDIDATES, QUOTA, "s", set())
    first = base["slots"][0]["repo"]
    again = chuti.sample(CANDIDATES, QUOTA, "s", {first.upper()})  # 以前的题集用过：不分大小写
    assert first not in {s["repo"] for s in again["slots"]} | {r["repo"] for v in again["spares"].values() for r in v}
    assert again["counts"]["excluded"] == 1
    extra = [
        cand(20, lic="GPL-3.0"),
        cand(21, lic=""),
        {**cand(22), "commit": "main"},  # 没有钉住提交号
        {**cand(23), "commit": "abc123"},
        cand(24, "Rust"),  # 配额里没有这一格
        cand(1),  # 重复的一行
    ]
    doc = chuti.sample([*CANDIDATES, *extra], QUOTA, "s", set())
    seen = {s["repo"] for s in doc["slots"]} | {r["repo"] for v in doc["spares"].values() for r in v}
    assert not seen & {f"o/r{i}" for i in range(20, 25)}
    assert doc["counts"] == {"eligible": 12, "excluded": 0, "license": 2, "outside_cells": 1, "malformed": 2}
    with pytest.raises(Refused) as e:
        chuti.sample(CANDIDATES, QUOTA, "s", {f"o/r{i}" for i in (10, 11, 12)})
    assert "Go/小" in str(e.value) and "配额取不满" in str(e.value)
    with pytest.raises(Refused):
        chuti.sample(CANDIDATES, QUOTA, " ", set())


def test_a_quota_that_is_incomplete_or_does_not_add_up_is_refused():
    def why(**change) -> str:
        with pytest.raises(Refused) as e:
            chuti.check_quota({**QUOTA, **change})
        return str(e.value)

    assert "题集代号" in why(set="")
    assert "许可证" in why(licenses=[])
    assert "分档" in why(sizes={"小": [10, 5]})
    assert "格子" in why(cells={"Python/特大": 1})
    assert "格子" in why(cells={"Python/小": 0})
    assert "ask" in why(ask={"怎么做": 4})
    assert "两边要相等" in why(premise={"holds": 2, "fails": 1})
    assert "where" in why(where=None)
    assert chuti.check_quota(QUOTA) is QUOTA


def test_candidates_come_from_several_pages_of_a_search_per_cell_and_each_is_pinned(monkeypatch):
    monkeypatch.setattr(chuti, "PER_QUERY", 2)
    monkeypatch.setattr(chuti, "PAGES", 3)
    asked = []

    def item(name: str, lic: str = "MIT") -> dict:
        return {"full_name": name, "default_branch": "main", "size": 12, "license": {"spdx_id": lic}}

    def get(url: str):
        asked.append(url)
        if "/search/repositories" not in url:
            return {"sha": "a" * 40}
        page = int(url.rsplit("page=", 1)[1])
        if "language%3AGo" in url:  # 这一格结果很多：取满三页为止
            return {"items": [item(f"o/go-{page}-a"), item(f"o/go-{page}-b", "GPL-3.0")]}
        if "size%3A0..999" in url:  # Python/小：第二页就到头了
            return {"items": [item("o/py-1"), item("o/py-2")] if page == 1 else [item("o/py-3")]}
        return {"items": [item("o/big-1"), {"full_name": "", "default_branch": "main"}][: 2 if page == 1 else 0]}

    rows = chuti.find_candidates(QUOTA, get)
    assert sorted(r["repo"] for r in rows) == [
        "o/big-1",
        "o/go-1-a",
        "o/go-2-a",
        "o/go-3-a",
        "o/py-1",
        "o/py-2",
        "o/py-3",
    ]
    assert all(r["commit"] == "a" * 40 and r["license"] == "MIT" for r in rows)
    assert all(r["url"] == f"https://github.com/{r['repo']}.git" for r in rows)
    searches = [u for u in asked if "/search/" in u]
    assert all("fork%3Afalse" in u and "archived%3Afalse" in u and "per_page=2" in u for u in searches)
    pages = lambda mark: [int(u.rsplit("page=", 1)[1]) for u in searches if mark in u]  # noqa: E731
    assert pages("language%3AGo") == [1, 2, 3]  # 至多三页
    assert pages("language%3APython%20size%3A0..999") == [1, 2]  # 不满一页就到头了
    assert pages("size%3A1000..%2A") == [1, 2]
    assert not any("go-1-b" in u for u in asked)  # 许可证不在清单里的：不去钉提交号，也不进清单
    assert "stars%3A" not in "".join(searches)
    asked.clear()
    chuti.find_candidates({**QUOTA, "stars": [50, 5000]}, get)
    assert all("stars%3A50..5000" in u for u in asked if "/search/" in u)
    with pytest.raises(Refused):
        chuti.check_quota({**QUOTA, "stars": [10, 5]})
    assert chuti.sample(rows, {**QUOTA, "cells": {"Go/小": 1}, **one_of_each(1)}, "s", set())["slots"]


def one_of_each(n: int) -> dict:
    return {"ask": {"how": n}, "premise": {"holds": n}, "where": {"code": n}}


# ---------------------------------------------------------------- 第 2 步：出题


def test_the_setting_call_reads_the_snapshot_and_hands_over_the_four_things():
    fake = Setter()
    slot = {"n": 3, "axes": {**HOW, "language": "Python", "size": "小"}, "repo": "o/secret-name"}
    got = chuti.set_one(slot, SNAP, 1, fake, Ledger(None))
    assert got == draft() and got["text"] and got["absent"] is None
    assert all(p["evidence"] for s in got["subquestions"] for p in s["points"])
    assert "relay/" in fake.tools[0]  # 工具看到的是快照
    assert "问法：how" in fake.asked[0] and "前提：holds" in fake.asked[0] and "答案在哪里：code" in fake.asked[0]
    assert "secret-name" not in fake.asked[0] and "换一个角度" not in fake.asked[0]
    chuti.set_one(slot, SNAP, 2, fake, Ledger(None))
    assert "换一个角度" in fake.asked[1]


@pytest.mark.parametrize(
    "broken",
    [
        "这不是 JSON",
        {"text": "", "subquestions": []},
        {**CASES["good"]["draft"], "subquestions": CASES["good"]["draft"]["subquestions"][:1]},  # 只有一个子问
        {**CASES["good"]["draft"], "absent": {"sub": 9, "searched": ["x"], "actual": "y"}},
    ],
)
def test_a_draft_of_the_wrong_shape_is_dropped(broken):
    slot = {"n": 1, "axes": {**HOW, "language": "Python"}}
    with pytest.raises(chuti.Dropped) as e:
        chuti.set_one(slot, SNAP, 1, Setter(lambda axes, attempt: broken), Ledger(None))
    assert e.value.check == "malformed"

    class Down:
        def chat(self, system, messages, tools=None):
            raise ModelError("断了")

    with pytest.raises(chuti.Dropped) as e:
        chuti.set_one(slot, SNAP, 1, Down(), Ledger(None))
    assert e.value.check == "failed"


# ---------------------------------------------------------------- 第 3 步：五项校验


def dropped_by(d: dict, axes: dict | None = None, m: chuti.Models | None = None) -> str | None:
    try:
        chuti.vet(d, SNAP, axes or HOW, m or models(), Ledger(None), "t")
    except chuti.Dropped as e:
        return e.check
    return None


def test_the_four_deliberately_bad_questions_are_each_dropped_by_the_check_meant_for_it():
    """校验拦得住坏题：指针越界、前提标错、题面泄底、不读仓库也能答，四道都被丢弃；做对的那一道通过。"""
    doc = chuti.selfcheck(models(), Ledger(None))
    assert doc["ok"] and doc["generator"] == chuti.version()
    assert {k: (r["expected"], r["got"]) for k, r in doc["results"].items()} == {
        "good": (None, None),
        "pointer": ("evidence", "evidence"),
        "premise": ("evidence", "evidence"),
        "leak": ("leak", "leak"),
        "common": ("needs_repo", "needs_repo"),
    }


def test_a_checker_that_lets_everything_through_or_drops_everything_fails_the_selfcheck():
    class Easy(Answerer):  # 什么题都说不读仓库答不出
        def chat(self, system, messages, tools=None):
            return Turn("1: 这条是错的", [], USAGE, "a")

    lax = chuti.selfcheck(chuti.Models(Setter(), [Easy()], simple()), Ledger(None))
    assert not lax["ok"] and lax["results"]["common"]["got"] is None
    strict = chuti.selfcheck(models(Setter(unsupported=("要点",))), Ledger(None))  # 什么要点都说不支持
    assert not strict["ok"] and strict["results"]["good"]["got"] == "supported"


def test_evidence_must_sit_inside_the_snapshot_and_within_the_file():
    def bad(pointer: dict) -> str:
        d = draft()
        d["subquestions"][0]["points"][0]["evidence"] = [pointer]
        with pytest.raises(chuti.Dropped) as e:
            chuti.check_evidence(d, SNAP, HOW)
        assert e.value.check == "evidence"
        return e.value.why

    assert "越界" in bad({"path": "relay/sender.py", "start": 30, "end": 35})
    assert "越界" in bad({"path": "relay/sender.py", "start": 9, "end": 8})
    assert "快照之外" in bad({"path": "../expected.json", "start": 1, "end": 1})
    assert "不在快照里" in bad({"path": "relay/nothing.py", "start": 1, "end": 1})
    assert "不在快照里" in bad({"path": "relay", "start": 1, "end": 1})
    chuti.check_evidence(draft(), SNAP, HOW)
    long = SNAP.parent / "answers" / "wrong-a.md"
    assert long.exists()  # 另一个真文件：只是用来说明下面这条是按行数卡的
    d = draft()
    d["subquestions"][0]["points"][0]["evidence"] = [{"path": "relay/sender.py", "start": 1, "end": 34}]
    chuti.check_evidence(d, SNAP, HOW)  # 34 行，在 60 行之内


def test_a_premise_label_must_match_the_cell_and_the_missing_words_must_really_be_missing():
    fails = {**HOW, "premise": "fails"}
    chuti.check_evidence(absent_draft(), SNAP, fails)

    def why(d: dict, axes: dict) -> str:
        with pytest.raises(chuti.Dropped) as e:
            chuti.check_evidence(d, SNAP, axes)
        assert e.value.check == "evidence"
        return e.value.why

    assert "与格子不符" in why(absent_draft(), HOW)  # 格子说成立，交了「确实没有」
    assert "与格子不符" in why(draft(), fails)  # 格子说不成立，没交
    d = absent_draft()
    d["absent"]["searched"] = ["retry", "MAX_batch"]  # 其实有，不分大小写
    assert "前提标错了" in why(d, fails)
    d["absent"]["searched"] = ["queue"]  # 文件名里有
    assert "前提标错了" in why(d, fails)
    d["absent"]["searched"] = ["x"]
    assert "太短" in why(d, fails)
    d = absent_draft()
    d["absent"]["expected_at"] = {"path": "relay/sender.py", "start": 1, "end": 500}
    assert "越界" in why(d, fails)


def test_where_the_answer_lives_must_match_the_cell():
    doc = {**HOW, "where": "doc"}
    chuti.check_evidence(doc_draft(), SNAP, doc)
    chuti.check_evidence(doc_draft(), SNAP, HOW)  # 有代码里的证据，也有文档里的
    with pytest.raises(chuti.Dropped) as e:
        chuti.check_evidence(draft(), SNAP, doc)
    assert "位置标得与格子不符" in e.value.why


@pytest.mark.parametrize(
    ("text", "leaks"),
    [
        ("这个转发器是按什么条件把攒着的消息发出去的？", False),
        ("用 Python 写的这个转发器，一批至多发多少条？", False),  # 平常的英文词不算
        ("relay/sender.py 里是按什么条件发的？", True),  # 路径
        ("sender.py 里是按什么条件发的？", True),  # 文件名
        ("MAX_BATCH 是多少？", True),  # 证据里被赋值的名字
        ("max_batch 是多少？", True),  # 不分大小写
        ("due 这个判断在什么时候为真？", True),  # 证据里定义的函数
        ("oldest_age 是怎么算的？", True),  # 证据之外，但一看就是代码里的名字
        ("my_own_word 是什么意思？", False),  # 带下划线，但快照里没有
    ],
)
def test_a_question_may_not_name_a_path_or_the_definition_that_holds_the_answer(text, leaks):
    d = draft()
    d["text"] = text
    if leaks:
        with pytest.raises(chuti.Dropped) as e:
            chuti.check_leak(d, SNAP)
        assert e.value.check == "leak"
    else:
        chuti.check_leak(d, SNAP)


def test_defined_names_cover_definitions_assignments_and_config_keys():
    got = chuti.defined_names(
        ["def take(self, n):", "class BoundedQueue:", "func NewSender(", "  retry.max-attempts: 5", "x = 1", "  go()"]
    )
    assert {"take", "boundedqueue", "newsender", "retry.max-attempts", "retry", "max", "attempts"} <= got
    assert "x" not in got and "go" not in got


def test_the_independent_check_sees_only_the_question_and_the_quoted_lines():
    fake = Setter()
    chuti.check_supported(draft(), SNAP, fake, Ledger(None), "t")
    seen = fake.checked[0]
    assert draft()["text"] in seen and "要点 3（回答子问 2）" in seen
    assert "18\t    def due(self, now: float) -> bool:" in seen and "3\tMAX_BATCH = 16" in seen
    assert "relay/" not in seen and "sender.py" not in seen  # 路径不给
    assert "class Sender" not in seen  # 指针之外的原文不给
    with pytest.raises(chuti.Dropped) as e:
        chuti.check_supported(draft(), SNAP, Setter(unsupported=("16 条",)), Ledger(None), "t")
    assert e.value.check == "supported" and "[2]" in e.value.why

    fake = Setter()
    chuti.check_supported(absent_draft(), SNAP, fake, Ledger(None), "t")
    assert "前提不成立" in fake.checked[0] and "retry、backoff" in fake.checked[0]
    assert "27\t        try:" in fake.checked[0]  # 本该在的地方实际的原文也给


def test_the_independent_check_retries_a_bad_output_once_and_then_counts_as_not_done():
    class Scripted:
        def __init__(self, *replies):
            self.replies, self.users = list(replies), []

        def chat(self, system, messages, tools=None):
            self.users.append(messages[0]["text"])
            r = self.replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return Turn(r, [], USAGE, "m")

    ok = json.dumps({"points": [{"n": i, "supported": True} for i in (1, 2, 3)]})
    retry = Scripted('{"points": [{"n": 1, "supported": true}]}', ok)  # 少了两条
    chuti.check_supported(draft(), SNAP, retry, Ledger(None), "t")
    assert "上一次的输出不合要求" in retry.users[1]
    for bad in (("不知道", '{"points": "都对"}'), (ModelError("断了"),)):
        with pytest.raises(chuti.Dropped) as e:
            chuti.check_supported(draft(), SNAP, Scripted(*bad), Ledger(None), "t")
        assert e.value.check == "failed"


def test_a_question_answerable_without_the_repository_is_dropped_by_the_blind_judge():
    answerer, judge = Answerer(), simple()
    chuti.check_needs_repo(draft(), SNAP, answerer, judge, Ledger(None), "t")  # 答错了：留下
    assert answerer.asked == [draft()["text"]]  # 只给题面，没有快照，没有子问
    assert {stage for stage, _ in judge.seen} == {"zhengli", "pandu", "hedui"}  # 用的是第 5 节的盲判
    with pytest.raises(chuti.Dropped) as e:
        chuti.check_needs_repo(draft("common"), SNAP, Answerer(), simple(), Ledger(None), "t")
    assert e.value.check == "needs_repo"

    class Silent:
        def chat(self, system, messages, tools=None):
            return Turn("  ", [], USAGE, "a")

    chuti.check_needs_repo(draft("common"), SNAP, Silent(), simple(), Ledger(None), "t")  # 什么都没答：不过线


def test_every_answering_model_is_tried_and_one_that_can_answer_is_enough_to_drop():
    """用到的每个模型各做一遍：强一些的模型凭记忆答得出，这道题就不能用。"""

    class Knows(Answerer):
        def chat(self, system, messages, tools=None):
            return Turn("1: 甲\n2: 乙", [], USAGE, "strong")

    weak, strong = Answerer(), Knows()
    assert dropped_by(draft(), m=chuti.Models(Setter(), [weak], simple())) is None
    assert dropped_by(draft(), m=chuti.Models(Setter(), [weak, strong], simple())) == "needs_repo"
    assert len(weak.asked) == 2


def test_the_cheap_program_checks_run_before_any_model_is_asked():
    m = models()
    assert dropped_by(draft("pointer"), m=m) == "evidence" and dropped_by(draft("leak"), m=m) == "leak"
    assert not m.setter.checked and not m.answerers[0].asked
    assert dropped_by(draft(), m=m) is None and len(m.setter.checked) == 1 and len(m.answerers[0].asked) == 1


# ---------------------------------------------------------------- 第 4 步：整套、入库与摘要


def copy_snapshot(row, dest):
    shutil.copytree(SNAP, dest)


def plan(seed: str = "种子甲") -> dict:
    return chuti.sample(CANDIDATES, QUOTA, seed, set())


def run(tmp_path, monkeypatch, m=None, fetch=copy_snapshot, out="set", sample_doc=None):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    write_json(tmp_path / "m.json", {**JUDGE, "name": "arm-model"})
    write_json(tmp_path / "judge.json", JUDGE)
    write_json(
        tmp_path / "jsc.json",
        {
            "ok": True,
            "model": "judge-model",
            "version": "7",
            **mangpan.version(),
            "results": {name: {"ok": True, "seconds": 3.0} for name in SAMPLES},
        },
    )
    write_json(tmp_path / "sample.json", sample_doc or plan())
    common = {
        "setter": str(tmp_path / "m.json"),
        "answerer": None,
        "judge": str(tmp_path / "judge.json"),
        "judge_selfcheck": str(tmp_path / "jsc.json"),
    }
    sc = tmp_path / "chuti_selfcheck.json"
    if not sc.exists():
        assert chuti.run_selfcheck(argparse.Namespace(**common, out=str(sc)), models()) == 0
    a = argparse.Namespace(
        **common,
        sample=str(tmp_path / "sample.json"),
        out=str(tmp_path / out),
        used=str(tmp_path / "used.json"),
        selfcheck=str(sc),
    )
    return chuti.run_generate(a, m or models(), fetch)


def test_a_whole_set_is_made_admitted_and_only_a_digest_and_counts_come_back(tmp_path, monkeypatch, capsys):
    assert run(tmp_path, monkeypatch) == 0
    out = tmp_path / "set"
    questions, keys, receipt = (read_json(out / f"{n}.json") for n in ("questions", "keys", "receipt"))
    rows = questions["questions"]
    assert [q["id"] for q in rows] == [f"GEN-1-{i:03d}" for i in (1, 2, 3, 4)]
    assert all((out / q["snapshot"] / "relay" / "sender.py").exists() for q in rows)
    assert all(set(q) == {"id", "text", "subquestions", "snapshot", "axes"} for q in rows)  # 答案不在题集文件里
    assert all(isinstance(s, str) for q in rows for s in q["subquestions"])
    assert mangpan.load_questions(out / "questions.json").keys() == {q["id"] for q in rows}  # 盲判读得进
    g = questions["generator"]
    assert g["id"] == chuti.version_id() and g["seed"] == "种子甲" and g["quota"] == sha(QUOTA)
    assert g["models"] == {
        "setter": ["arm-model", "7"],
        "answerers": [["arm-model", "7"]],
        "judge": ["judge-model", "7"],
    }
    assert g["keys"] == sha(keys) and set(keys) == {q["id"] for q in rows}
    assert all(k["repo"].startswith("o/r") and len(k["commit"]) == 40 for k in keys.values())

    assert receipt["digest"] == sha(questions) == pici.set_digest(questions)[0] and receipt["count"] == 4
    assert receipt["cells"]["premise"] == {"fails": 1, "holds": 3} and receipt["cells"]["where"] == {
        "code": 3,
        "doc": 1,
    }
    assert receipt["cells"]["language"] == {"Go": 1, "Python": 3}
    assert receipt["language_by_size"] == {"Go/小": 1, "Python/大": 1, "Python/小": 2}
    assert receipt["discarded"] == dict.fromkeys((*chuti.CHECKS, "malformed", "failed", "fetch"), 0)
    blob = json.dumps(receipt, ensure_ascii=False) + capsys.readouterr().out
    assert "o/r" not in blob and "转发器" not in blob and "relay" not in blob  # 没有仓库名、题面与路径
    used = read_json(tmp_path / "used.json")["repos"]
    assert {u["repo"] for u in used} == {k["repo"] for k in keys.values()} and {u["set"] for u in used} == {"GEN-1"}

    with pytest.raises(Refused) as e:
        run(tmp_path, monkeypatch)
    assert "已经有一套" in str(e.value)


def test_a_failed_question_is_redone_and_then_replaced_by_the_next_spare_of_the_same_cell(tmp_path, monkeypatch):
    doc = plan()
    go = next(s for s in doc["slots"] if s["cell"] == "Go/小")
    fetched: list[str] = []
    other = next(s["repo"] for s in doc["slots"] if s["cell"] != "Go/小")

    def fetch(row, dest):
        fetched.append(row["repo"])
        shutil.copytree(SNAP, dest)
        (dest / "which.txt").write_text(row["repo"], "utf-8")

    def make(axes, attempt):
        d = fit(axes)
        here = fetched[-1]
        if here == go["repo"]:
            d["text"] = "relay/queue.py 里是怎么做的？"  # 这个仓库每次都泄底
        elif here == other and attempt == 1:
            return "第一次没有交出 JSON"
        return d

    assert run(tmp_path, monkeypatch, models(Setter(make)), fetch, sample_doc=doc) == 0
    receipt = read_json(tmp_path / "set" / "receipt.json")
    assert receipt["discarded"]["leak"] == chuti.ATTEMPTS == 3 and receipt["discarded"]["malformed"] == 1
    assert receipt["replaced_repos"] == 1 and receipt["count"] == 4
    keys = read_json(tmp_path / "set" / "keys.json")
    spare = doc["spares"]["Go/小"][0]["repo"]
    assert keys[f"GEN-1-{go['n']:03d}"]["repo"] == spare and go["repo"] not in {k["repo"] for k in keys.values()}
    assert (tmp_path / "set" / "snapshots" / f"GEN-1-{go['n']:03d}" / "which.txt").read_text("utf-8") == spare
    axes = {q["id"]: q["axes"] for q in read_json(tmp_path / "set" / "questions.json")["questions"]}
    assert axes[f"GEN-1-{go['n']:03d}"] == go["axes"]  # 替补接的是这个位置的格子


def test_when_a_cell_runs_out_of_spares_nothing_is_admitted_and_a_rerun_keeps_what_was_done(tmp_path, monkeypatch):
    doc = plan()
    last = doc["slots"][-1]
    asked: list[str] = []
    now: list[str] = []
    broken = [True]

    def fetch(row, dest):
        now.append(dest.name)
        shutil.copytree(SNAP, dest)

    def make(axes, attempt):
        asked.append(now[-1])
        d = fit(axes)
        return {**d, "text": "sender.py 里是怎么做的？"} if now[-1] == "GEN-1-004" and broken[0] else d

    with pytest.raises(Refused) as e:
        run(tmp_path, monkeypatch, models(Setter(make)), fetch, sample_doc=doc)
    assert "替补都用完了" in str(e.value) and last["cell"] in str(e.value)
    tried = 1 + len(doc["spares"][last["cell"]])
    assert asked.count("GEN-1-004") == tried * chuti.ATTEMPTS  # 每个仓库出三次，替补一个一个用完
    out = tmp_path / "set"
    assert not (out / "questions.json").exists() and not (out / "receipt.json").exists()
    assert not (tmp_path / "used.json").exists()
    assert sorted(p.stem for p in (out / "work").iterdir()) == ["GEN-1-001", "GEN-1-002", "GEN-1-003"]
    assert not (out / "snapshots" / "GEN-1-004").exists()
    broken[0] = False
    before = len(asked)
    assert run(tmp_path, monkeypatch, models(Setter(make)), fetch, sample_doc=doc) == 0
    assert asked[before:] == ["GEN-1-004"]  # 出好的不重出
    assert read_json(out / "receipt.json")["count"] == 4


def test_one_repository_gives_one_question_and_a_used_repository_gives_none(tmp_path, monkeypatch):
    """第五项：与已有的题不重复。"""
    doc = plan()
    twice = copy.deepcopy(doc)
    twice["slots"][1].update({k: twice["slots"][0][k] for k in ("repo", "commit", "url")})  # 同一个仓库排了两个位置
    assert run(tmp_path, monkeypatch, sample_doc=twice) == 0
    receipt, keys = read_json(tmp_path / "set" / "receipt.json"), read_json(tmp_path / "set" / "keys.json")
    assert receipt["discarded"]["duplicate"] == 1 and receipt["replaced_repos"] == 1
    assert len({k["repo"] for k in keys.values()}) == 4

    again = chuti.sample(CANDIDATES, QUOTA, "种子甲", set())  # 取样时没有排除用过的
    assert run(tmp_path, monkeypatch, out="set2", sample_doc=again) == 0  # used.json 里记着：出题时照样不用
    keys2 = read_json(tmp_path / "set2" / "keys.json")
    assert not {k["repo"] for k in keys.values()} & {k["repo"] for k in keys2.values()}
    assert read_json(tmp_path / "set2" / "receipt.json")["discarded"]["duplicate"] >= 1

    one = {"id": "a", "repo": "o/x", "commit": "c", "axes": HOW, "draft": draft()}
    small = {**doc, "slots": doc["slots"][:2]}
    names = {"setter": ["m", "1"]}
    with pytest.raises(Refused) as e:
        chuti.admit(small, [one, {**one, "id": "b", "repo": "O/X"}], names, set())
    assert "不止一道题" in str(e.value)
    with pytest.raises(Refused):
        chuti.admit(small, [one, {**one, "id": "b", "repo": "o/y"}], names, {"o/y"})
    with pytest.raises(Refused) as e:
        chuti.admit(small, [one], names, set())
    assert "配额是 2 道" in str(e.value)


def test_a_snapshot_that_cannot_be_fetched_moves_on_to_a_spare(tmp_path, monkeypatch):
    doc = plan()
    first = doc["slots"][0]["repo"]

    def fetch(row, dest):
        if row["repo"] == first:
            raise OSError("取不到")
        shutil.copytree(SNAP, dest)

    assert run(tmp_path, monkeypatch, fetch=fetch, sample_doc=doc) == 0
    receipt = read_json(tmp_path / "set" / "receipt.json")
    assert receipt["discarded"]["fetch"] == 1 and receipt["replaced_repos"] == 1


def test_generation_refuses_without_a_passing_selfcheck_for_this_version_and_these_models(tmp_path, monkeypatch):
    assert run(tmp_path, monkeypatch) == 0
    sc = tmp_path / "chuti_selfcheck.json"
    good = read_json(sc)

    def why(**change) -> str:
        write_json(sc, {**good, **change})
        with pytest.raises(Refused) as e:
            run(tmp_path, monkeypatch, out="again")
        assert not (tmp_path / "again").exists()
        return str(e.value)

    assert "先跑 chuti selfcheck" in why(ok=False)
    assert "先跑 chuti selfcheck" in why(generator={**good["generator"], "prompts": "旧的一版"})
    assert "先跑 chuti selfcheck" in why(models={**good["models"], "setter": ["另一个模型", "1"]})
    write_json(sc, good)
    write_json(tmp_path / "judge.json", {**JUDGE, "name": "arm-model"})
    common = {
        "setter": str(tmp_path / "m.json"),
        "answerer": None,
        "judge": str(tmp_path / "judge.json"),
        "judge_selfcheck": str(tmp_path / "jsc.json"),
    }
    with pytest.raises(Refused) as e:
        chuti.run_selfcheck(argparse.Namespace(**common, out=str(tmp_path / "x.json")), models())
    assert "盲判的模型必须与被它判的模型不同" in str(e.value)
    write_json(tmp_path / "judge.json", JUDGE)
    write_json(tmp_path / "jsc.json", {**read_json(tmp_path / "jsc.json"), "ok": False})
    with pytest.raises(Refused) as e:
        chuti.run_selfcheck(argparse.Namespace(**common, out=str(tmp_path / "x.json")), models())
    assert "自检记录" in str(e.value)


def test_the_version_changes_with_a_prompt_a_limit_the_bad_questions_or_the_ruler(monkeypatch, capsys):
    before = chuti.version()
    assert chuti.main(["version"]) == 0
    assert json.loads(capsys.readouterr().out) == {"id": chuti.version_id(), **before}
    real = chuti.prompts()
    monkeypatch.setattr(chuti, "prompts", lambda: {**real, "yanti": real["yanti"] + "。"})
    assert chuti.version()["prompts"] != before["prompts"]
    monkeypatch.undo()
    monkeypatch.setattr(chuti, "ATTEMPTS", 5)
    assert chuti.version() != before
    monkeypatch.undo()
    cases = chuti.canary()
    monkeypatch.setattr(chuti, "canary", lambda: {**cases, "note": "改了"})
    assert chuti.version()["canary"] != before["canary"]
    monkeypatch.undo()
    monkeypatch.setattr(mangpan, "PER_SUBQ", 3)
    assert chuti.version()["ruler"] != before["ruler"]


def test_the_real_fetch_takes_exactly_the_pinned_commit_and_leaves_no_git_directory(tmp_path):
    src = tmp_path / "src"
    src.mkdir()

    def git(*args: str) -> str:
        env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
        return subprocess.run(["git", "-C", str(src), *env, *args], capture_output=True, check=True, text=True).stdout

    git("init", "-q")
    (src / "a.txt").write_text("第一版\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "one")
    pinned = git("rev-parse", "HEAD").strip()
    (src / "a.txt").write_text("第二版\n", "utf-8")
    git("commit", "-q", "-am", "two")
    git("config", "uploadpack.allowAnySHA1InWant", "true")
    chuti.git_fetch({"url": src.as_uri(), "commit": pinned}, tmp_path / "snap")
    assert (tmp_path / "snap" / "a.txt").read_text("utf-8") == "第一版\n" and not (tmp_path / "snap" / ".git").exists()
    with pytest.raises(OSError):
        chuti.git_fetch({"url": src.as_uri(), "commit": "0" * 40}, tmp_path / "none")


# ---------------------------------------------------------------- 题目质量的抽检


def test_the_spot_check_picks_by_the_set_digest_and_reports_a_rate_only_when_filled_in(tmp_path, monkeypatch, capsys):
    assert run(tmp_path, monkeypatch) == 0
    sheet = tmp_path / "sheet.json"
    argv = ["spot", "--set", str(tmp_path / "set"), "--n", "3", "--out", str(sheet)]
    assert chuti.main(argv) == 0
    doc = read_json(sheet)
    assert len(doc["rows"]) == 3 and doc == chuti.spot_pick(tmp_path / "set", 3)  # 抽哪几道是定死的
    assert doc["digest"] == read_json(tmp_path / "set" / "receipt.json")["digest"]
    assert chuti.main(["spot", "--tally", str(sheet)]) == 2  # 还没填
    doc["rows"][0].update(reads_like_a_real_question=True, points_are_right=True)
    doc["rows"][1].update(reads_like_a_real_question=True, points_are_right=False)
    doc["rows"][2].update(reads_like_a_real_question=True, points_are_right=True)
    write_json(sheet, doc)
    capsys.readouterr()
    assert chuti.main(["spot", "--tally", str(sheet)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["checked"] == 3 and got["both"] == 2 and got["rate"] == round(2 / 3, 4)
    assert got["reads_like_a_real_question"] == 3 and got["points_are_right"] == 2


# ---------------------------------------------------------------- 与人出的题是不是同一把尺子

GOOD, BAD = "1: 甲\n2: 乙", "1: 甲\n2: 这条是错的"
GEN = {"generator": {"id": chuti.version_id(), "quota": "配额甲的摘要"}}
RECORD = {"generator": chuti.version_id(), "quota": "配额甲的摘要", "ok": True}


def judged(tmp, passes: dict[str, list[bool]], header: dict | None = None, **batch):
    """搭一个判过的批次：每条臂在每道题上过不过线照 `passes` 给。回 (批次目录, 题集文件)。"""
    tmp.mkdir()
    atts = [attempt(arm, f"q{i}", 1, GOOD if ok else BAD) for arm, oks in passes.items() for i, ok in enumerate(oks, 1)]
    n = max(len(v) for v in passes.values())
    qs = [
        {"id": f"q{i}", "text": f"题{i}", "subquestions": ["子问甲", "子问乙"], "snapshot": str(SNAP)}
        for i in range(1, n + 1)
    ]
    arms = {k: v for k, v in ARMS.items() if k in passes}
    bdir, qpath, jpath = make_batch(tmp, atts, qs, arms=arms, **batch)
    write_json(qpath, {**read_json(qpath), **(header or {})})
    assert mangpan.run_judge(judge_args(bdir, qpath), simple()) == 0
    return bdir, qpath


def judge_args(bdir, qpath) -> argparse.Namespace:
    jpath = qpath.parent / "judge.json"
    return argparse.Namespace(batch=str(bdir), questions=str(qpath), judge=str(jpath), selfcheck=None, jobs=1)


def anchor_cli(tmp_path, ab, aq, gb, gq, name: str = "anchor.json") -> int:
    argv = ["anchor", "--anchor", str(ab), "--anchor-questions", str(aq), "--generated", str(gb)]
    return chuti.main([*argv, "--generated-questions", str(gq), "--out", str(tmp_path / name)])


def anchor(tmp_path, a: dict, g: dict, name: str = "anchor.json") -> tuple[int, dict]:
    n = len(list(tmp_path.iterdir()))
    ab, aq = judged(tmp_path / f"锚{n}", a)
    gb, gq = judged(tmp_path / f"生成{n}", g, GEN)
    return anchor_cli(tmp_path, ab, aq, gb, gq, name), read_json(tmp_path / name)


T, F = True, False
ANCHOR_RUN = {"B": [T] * 8 + [F] * 2, "B2": [T] * 7 + [F] * 3}  # 本火 10 题过 8；同火对照 1 题不一致，噪声底 m = 2


def test_a_generated_set_within_the_noise_floor_of_the_anchor_may_be_used_for_verdicts(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    code, doc = anchor(tmp_path, ANCHOR_RUN, {"B": [T] * 6 + [F] * 4})  # 生成的：过 6，差 0.2，刚好在内
    assert code == 0 and doc["ok"] and doc["gap"] == 0.2 and doc["floor"] == 0.2  # 噪声底折成比例 2/10
    assert doc["anchor"]["noise_floor"] == 2 and doc["generated"]["noise_floor"] is None
    assert doc["generator"] == chuti.version_id() and doc["anchor"]["passed"] == 8
    assert doc["quota"] == "配额甲的摘要"  # 记录钉住配额
    assert doc["benhuo"] == {"model": "arm-model", "version": "1", "gongfa": ["g" * 8]}
    assert doc["judge"] == {
        "model": "judge-model",
        "version": "7",
        "prompts": mangpan.prompts_digest(),
        "sampling": [mangpan.PER_SUBQ, mangpan.PER_ANSWER],
    }
    assert mangpan.anchored(GEN, doc) is None
    code, doc = anchor(tmp_path, ANCHOR_RUN, {"B": [T] * 5 + [F] * 5}, "far.json")  # 过 5，差 0.3
    assert code == 1 and not doc["ok"] and doc["gap"] == 0.3
    assert "只能用于旗帜" in mangpan.anchored(GEN, doc)


def test_the_two_sides_of_an_anchor_comparison_must_use_the_same_arm_and_the_same_ruler(tmp_path, monkeypatch, capsys):
    """两边不可比就不出记录：本火要是同一条，盲判要是同一把，两边的自检都过。理由说清是哪一样。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    ab, aq = judged(tmp_path / "锚", ANCHOR_RUN)
    n = 0

    def why(change, side: str = "生成") -> str:
        nonlocal n
        n += 1
        gb, gq = judged(tmp_path / f"生成{n}", {"B": [T] * 6 + [F] * 4}, GEN)
        ab2 = tmp_path / f"锚{n}" / "batch"
        shutil.copytree(ab, ab2)
        change(gb if side == "生成" else ab2)
        capsys.readouterr()
        assert anchor_cli(tmp_path, ab2, aq, gb, gq, f"r{n}.json") == 2
        assert not (tmp_path / f"r{n}.json").exists()  # 不出记录
        return capsys.readouterr().err

    def verdicts(bdir, **change) -> None:  # 这一边是另一把尺子判的：判的记录与自检记录都是它的
        for f in (bdir / "verdicts").glob("*.json"):
            write_json(f, {**read_json(f), **change})
        renamed = {{"model_version": "version"}.get(k, k): v for k, v in change.items() if k != "sampling"}
        write_json(bdir / "selfcheck.json", {**read_json(bdir / "selfcheck.json"), **renamed})

    def arm(bdir, **change) -> None:
        doc = read_json(bdir / "batch.json")
        doc["arms"]["B"] = {**doc["arms"]["B"], **change}
        write_json(bdir / "batch.json", doc)

    def gongfa(bdir) -> None:
        for f in (bdir / "attempts").rglob("attempt.json"):
            doc = read_json(f)
            if doc["arm"] == "B":
                write_json(f, {**doc, "gongfa": "h" * 8})

    assert "盲判的模型不同" in why(lambda b: verdicts(b, model="另一个盲判"))
    assert "盲判的版本不同" in why(lambda b: verdicts(b, model_version="8"))
    assert "盲判三段的版本不同" in why(lambda b: verdicts(b, prompts="旧的一版"))
    assert "盲判的抽样量不同" in why(lambda b: verdicts(b, sampling=[1, 8]))
    assert "本火的版本不同" in why(lambda b: arm(b, version="2"))
    assert "本火的模型不同" in why(lambda b: arm(b, model="arm-model-2"))
    assert "本火的功法摘要不同" in why(gongfa)
    assert "本火的版本、盲判的模型不同" in why(lambda b: (arm(b, version="2"), verdicts(b, model="另一个盲判")))

    def unchecked(bdir) -> None:
        write_json(bdir / "selfcheck.json", {**read_json(bdir / "selfcheck.json"), "ok": False})

    assert "生成的那一边没有这把盲判通过的自检记录" in why(unchecked)
    assert "锚的那一边没有这把盲判通过的自检记录" in why(unchecked, side="锚")
    assert "锚的那一边" in why(lambda b: (b / "selfcheck.json").unlink(), side="锚")

    def mixed(bdir) -> None:  # 一边里的记录是两把尺子判的
        first = sorted((bdir / "verdicts").glob("*.json"))[0]
        write_json(first, {**read_json(first), "prompts": "旧的一版"})

    assert "不是同一个模型、同一版尺子判出来的" in why(mixed)


def test_the_anchor_comparison_needs_a_noise_floor_a_human_anchor_and_a_generated_set(tmp_path, monkeypatch):
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    b, q = judged(tmp_path / "一", {"B": [T, T], "B2": [T, T]})
    lone, lq = judged(tmp_path / "二", {"B": [T, T]}, GEN)
    side = chuti.anchor_side
    with pytest.raises(Refused) as e:
        chuti.anchor(side(b, q), read_json(q), side(b, q), read_json(q))
    assert "没有 generator 一栏" in str(e.value)
    with pytest.raises(Refused) as e:
        chuti.anchor(side(lone, lq), read_json(lq), side(lone, lq), read_json(lq))
    assert "人出的" in str(e.value)
    human_lone, hq = judged(tmp_path / "三", {"B": [T, T]})
    with pytest.raises(Refused) as e:
        chuti.anchor(side(human_lone, hq), read_json(hq), side(lone, lq), read_json(lq))
    assert "没有噪声底" in str(e.value)
    with pytest.raises(Refused) as e:
        chuti.anchor_side(tmp_path / "三" / "batch", tmp_path / "二" / "questions.json")  # 题集里的题号对得上，臂不在
        side(*judged(tmp_path / "四", {"B2": [T, T]}))
    assert "没有本火臂的题次" in str(e.value)


def test_a_generated_set_cannot_be_registered_for_a_verdict_until_its_generator_and_quota_were_anchored(tmp_path):
    """P2：生成的题集先与 cz 手出的那一套对过才能用于判定。记录跟生成器的版本与配额走。旗帜与起点轮不查；
    人出的题集不查。用途是判定的批次必须给题集文件，记录记进批次头。"""
    arms, cfg = tmp_path / "arms.json", tmp_path / "cfg.yaml"
    write_json(arms, ARMS)
    cfg.write_text("x: 1\n")
    gen, human, rec = tmp_path / "gen.json", tmp_path / "human.json", tmp_path / "anchor.json"
    rows = [{"id": "q1", "text": "题", "subquestions": ["甲"], "snapshot": "s"}]
    write_json(gen, {**GEN, "questions": rows})
    write_json(human, {"questions": rows})
    n = 0

    def start(purpose: str, questions, record=None) -> int:
        nonlocal n
        n += 1
        argv = ["start", "--batch", str(tmp_path / f"b{n}"), "--id", "P", "--purpose", purpose, "--config", str(cfg)]
        argv += ["--arms", str(arms), "--set-code", "S", "--set-source", "生成"]
        if questions is not None:
            argv += ["--questions", str(questions)]
        if record is not None:
            write_json(rec, record)
            argv += ["--anchor", str(rec)]
        code = pici.main(argv)
        assert (tmp_path / f"b{n}" / "batch.json").exists() == (code == 0)
        return code

    assert start("判定", gen) == 2
    assert start("判定", gen, {**RECORD, "ok": False}) == 2
    assert start("判定", gen, {**RECORD, "generator": "另一版"}) == 2
    assert start("判定", gen, {**RECORD, "quota": "配额乙的摘要"}) == 2  # 同一版生成器，换了一份配额
    assert start("判定", gen, {k: v for k, v in RECORD.items() if k != "quota"}) == 2  # 旧记录没有钉配额
    assert start("判定", gen, RECORD) == 0
    head = read_json(tmp_path / f"b{n}" / "batch.json")
    assert head["anchor"] == RECORD and head["question_set"]["digest"] == sha(read_json(gen))  # 记进批次头
    assert head["question_set"]["count"] == 1
    assert start("判定", None) == 2 and start("判定", None, RECORD) == 2  # 判定必须给题集文件
    assert start("中期旗帜", gen) == 0 and start("起点轮", gen) == 0 and start("起点轮", None) == 0
    assert start("判定", human) == 0 and read_json(tmp_path / f"b{n}" / "batch.json")["anchor"] is None
    assert "只能用于旗帜" in chuti.anchored(read_json(gen), {**RECORD, "ok": False})
    assert "另一版生成器" in chuti.anchored(read_json(gen), {**RECORD, "generator": "另一版"})
    assert "配额换了，要重新对" in chuti.anchored(read_json(gen), {**RECORD, "quota": "配额乙的摘要"})
    assert "先与人出的锚题集对一次" in chuti.anchored(read_json(gen), None)


def test_judge_and_rejudge_check_again_that_a_generated_set_was_anchored(tmp_path, monkeypatch):
    """这条线在每一处都守着：批次头是用途判定、题集是生成的，开判前再核一次；judge 与 rejudge 都核。"""
    monkeypatch.setenv("LIANGJU_TEST_KEY", "k")
    atts = [attempt("B", "q1", 1, GOOD), attempt("B2", "q1", 1, GOOD)]
    qs = [{"id": "q1", "text": "题", "subquestions": ["子问甲", "子问乙"], "snapshot": str(SNAP)}]
    bdir, qpath, _ = make_batch(tmp_path, atts, qs, purpose="判定")
    write_json(qpath, {**read_json(qpath), **GEN})
    args = judge_args(bdir, qpath)

    def head(**change) -> None:
        write_json(bdir / "batch.json", {**read_json(bdir / "batch.json"), **change})

    for record, reason in (
        (None, "先与人出的锚题集对一次"),
        ({**RECORD, "quota": "配额乙的摘要"}, "配额换了，要重新对"),
        ({**RECORD, "generator": "另一版"}, "另一版生成器"),
        ({**RECORD, "ok": False}, "只能用于旗帜"),
    ):
        head(anchor=record)
        for run in (mangpan.run_judge, mangpan.run_rejudge):
            with pytest.raises(Refused) as e:
                run(args, simple())
            assert reason in str(e.value)
        assert not (bdir / "verdicts").exists()  # 一份都没有判
    head(anchor=RECORD)
    assert mangpan.run_judge(args, simple()) == 0 and mangpan.run_rejudge(args, simple()) == 0
    head(anchor=None, purpose="中期旗帜")  # 别的用途不查
    assert mangpan.run_rejudge(args, simple()) == 0
    head(purpose="判定", question_set={"code": "S", "source": "生成", "digest": "登记时的另一套"})
    with pytest.raises(Refused) as e:
        mangpan.run_judge(args, simple())
    assert "不是这一批登记的那一套题" in str(e.value)
