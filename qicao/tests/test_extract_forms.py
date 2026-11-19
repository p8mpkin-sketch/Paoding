"""抽取器形态用例（cz 2026-11-19，按 #91 降级后的功能面排优先级）。

一档：答案行，决定练习道资格与保密库。
二档：金额与时长，抽到才用原文数作预算缺省。
三档：地址形态，纯展示，只影响确认卡高亮与扩权卡对原文段号。

每类一组参数化用例，不建语料、不做召回度量。用例全部走 Intake.extract，与生产调用点同一条路。
"""

from __future__ import annotations

import pytest

from paoding_qicao.contract import Intake, Settings, parse_draft, placeholder_priors, vet
from paoding_qicao.draft import prompt
from paoding_qicao.service import heuristic_drafter

INTAKE = Intake.load()
SETTINGS = Settings.from_doc(
    {"version": "s1", "settings": {"caps": {"open_usd_milli": 20_000, "open_wall_s": 14_400}, "risk": []}}
)


def ext(text: str):
    e = INTAKE.extract(text)
    for s in e.spans:  # 偏移不变式：每个区间都是题面的原样切片
        assert e.text[s.start : s.end] == s.text
    return e


def toks(text: str) -> list[tuple[str, str, object]]:
    return [(s.kind, s.text, s.value) for s in ext(text).spans if s.kind != "sentence"]


# ---------- 一档：答案行 ----------


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("求两数之和。\n答案：42", "42"),
        ("求两数之和。\n答案:42", "42"),
        ("求两数之和。答案是42", "42"),
        ("求两数之和。\n答案是 42", "42"),
        ("求两数之和。\n答案是：42", "42"),
        ("求两数之和。答案是42。写进 answer.txt", "42"),
        ("求两数之和。\n答案为 PD-7Q2M9XKD", "PD-7Q2M9XKD"),
        ("Add the numbers.\nanswer: 42", "42"),
        ("Add the numbers.\nAnswer: 42", "42"),
        ("Add the numbers. Answer:42", "42"),
        ("Add the numbers.\nANSWER： 42", "42"),
        ("求两数之和。\n答案：42。", "42"),  # 末尾中文句号是句读，不是答案
        ("求两数之和。\n标准答案：PD-1", "PD-1"),
    ],
)
def test_answer_label_forms(text, answer):
    e = ext(text)
    assert e.answers == (answer,)
    assert answer not in e.text  # 剪出的答案不进题面
    assert answer not in prompt(e, True)  # 也不给起草模型


def test_answer_is_cut_but_rest_of_line_stays():
    e = ext("求两数之和。答案是42，写进 answer.txt")
    assert e.answers == ("42",)
    assert "写进 answer.txt" in e.text and "答案" not in e.text
    assert ("file", "answer.txt") in {(s.kind, s.text) for s in e.spans}


@pytest.mark.parametrize(
    "text",
    [
        "答案是什么？",
        "先想想答案是多少，再动手。",
        "\n答案是否唯一不重要。",
        "答案为几都行吗",
        "我知道答案是42",  # 标签前不是行首或句读：不是标签行
        "这份答案：留空",
    ],
)
def test_not_answer_lines(text):
    e = ext(text)
    assert e.answers == ()
    assert e.text == text.rstrip()  # 疑问句原样留在题面


def test_two_answer_forms_count_as_two():
    e = ext("题一。\n答案：a\n题二。答案是b")
    assert e.answers == ("a", "b") and "multiple_answers" in e.notes


# ---------- 二档：时长与金额 ----------


@pytest.mark.parametrize(
    ("text", "secs"),
    [
        ("限时半小时。", 1800),
        ("限时半个小时。", 1800),
        ("一个半小时内完成。", 5400),
        ("两个半小时内完成。", 9000),
        ("限时30分钟。", 1800),
        ("限时 45 分钟。", 2700),
        ("限时十五分钟。", 900),
        ("限时2小时。", 7200),
        ("限时两个小时。", 7200),
        ("限时1.5小时。", 5400),
    ],
)
def test_cn_durations(text, secs):
    d = [v for k, _, v in toks(text) if k == "duration"]
    assert d == [secs]


@pytest.mark.parametrize(
    ("text", "milli"),
    [
        ("花费不超过$5。", 5000),
        ("花费不超过 $ 0.5。", 500),
        ("最多5美元。", 5000),
        ("最多 5 美元。", 5000),
    ],
)
def test_money(text, milli):
    m = [v for k, _, v in toks(text) if k == "money"]
    assert m == [milli]


def test_yuan_needs_rate_and_is_not_tuple():
    e = ext("返回一个3元组。")
    assert not e.of("money")
    no_cny = Intake(INTAKE.labels, INTAKE.url_ports, INTAKE.defaults, False, INTAKE.envelope, {"usd": 1.0})
    assert not no_cny.extract("预算20元。").of("money")  # 没有换算表就不猜


def test_money_and_duration_feed_budget_default():
    """抽到才用原文数：草案指认金额与时长区间后，预算缺省取原文数，出处记"span"。"""
    e = ext("在一个半小时内算出结果，预算 5 美元。\n答案：7")
    d = parse_draft(heuristic_drafter(e, True), e, "cheap")
    v = vet(e, None, d, INTAKE, SETTINGS, placeholder_priors())
    assert v.input is not None and v.input["budget"]["wall_s"] == 5400 and v.input["budget"]["usd_milli"] == 5000
    src = {r["field"]: r["source"] for r in v.derivation}
    assert src["budget.wall_s"] == "span" and src["budget.usd_milli"] == "span"
    assert v.secret == "7"  # 答案行仍决定保密库


# ---------- 三档：地址形态（纯展示） ----------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        # 指令前导词后跟主机与端口
        ("用 nc q1.lab 31337 连上去。", ("addr", "nc q1.lab 31337", "q1.lab:31337")),
        ("nc -v 10.0.0.5 9000", ("addr", "nc -v 10.0.0.5 9000", "10.0.0.5:9000")),
        ("先 telnet box.example 23 看看。", ("addr", "telnet box.example 23", "box.example:23")),
        ("跑 `nc q1.lab 31337` 拿到串。", ("addr", "nc q1.lab 31337", "q1.lab:31337")),
        # 无端口纯域名
        ("文档在 example.com 上。", ("host", "example.com", "example.com")),
        ("查一下docs.python.org里的说明。", ("host", "docs.python.org", "docs.python.org")),
        # 带路径 URL（有协议 / 无协议 / host:port 后跟路径）
        ("看 https://docs.lab/api/v2/ref.html。", ("url", "https://docs.lab/api/v2/ref.html", "docs.lab:443")),
        ("see https://docs.lab/api/v2.", ("url", "https://docs.lab/api/v2", "docs.lab:443")),
        ("看 http://q1.lab:8080/flag?x=1，然后提交。", ("url", "http://q1.lab:8080/flag?x=1", "q1.lab:8080")),
        ("接口在 q1.lab:8080/api/v1 下。", ("addr", "q1.lab:8080/api/v1", "q1.lab:8080")),
        ("参考 example.com/guide/start 一节。", ("host", "example.com/guide/start", "example.com")),
        # 中文括号围栏
        ("地址（q1.lab:8080）", ("addr", "q1.lab:8080", "q1.lab:8080")),
        ("地址【q1.lab:8080】里", ("addr", "q1.lab:8080", "q1.lab:8080")),
        ("见「http://q1.lab/x」里的说明", ("url", "http://q1.lab/x", "q1.lab:80")),
        ("见《https://docs.lab/a/b》", ("url", "https://docs.lab/a/b", "docs.lab:443")),
        ("入口『nc q1.lab 31337』", ("addr", "nc q1.lab 31337", "q1.lab:31337")),
        ("连接到q1.lab:8080就行", ("addr", "q1.lab:8080", "q1.lab:8080")),
    ],
)
def test_address_forms(text, want):
    assert want in toks(text)


@pytest.mark.parametrize("text", ["改 main.py 和 notes.md。", "写进 answer.txt。", "版本 v1.5 与 e.g. 无关。"])
def test_files_are_not_domains(text):
    assert not ext(text).of("host")


def test_bare_domain_is_display_only():
    """没写端口的域名不给起草模型指认，所以不可能生成授权规则。"""
    e = ext("文档在 example.com 上，入口 q1.lab:8080。")
    assert [s.text for s in e.of("host")] == ["example.com"]
    p = prompt(e, False)
    assert "q1.lab:8080" in p.split("句子：")[0] and "example.com" not in p.split("句子：")[0]
