"""量具的题次整理对得上真的导出：整套起来跑一次方案分析（模型回放录音），再只凭运行结束之后的导出与三个只读的
GET（事件、预算、交付的回答）整理出题次记录。这里证明的是 `liangju/tici.py` 读的每个字段在真的导出里确实是那个形状。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from test_stack_analysis import engine_env, make, open_analysis, wait_deliveries  # noqa: F401
from tunshi_rig import Replay, cases

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "fenjue" / "tests"))  # 按题读的脚本模型（qled_script）
sys.path.insert(0, str(ROOT / "fenjue" / "tests" / "engine_fixtures"))

import cases as engine_cases  # noqa: E402
from qled_script import STATEMENT, QScript  # noqa: E402

from liangju import tici  # noqa: E402
from paoding_fenjue.engine import dati, wenti  # noqa: E402
from paoding_fenjue.engine.run import Config, Engine  # noqa: E402


def test_an_attempt_record_is_built_from_the_real_export_alone(tmp_path, engine_env):  # noqa: F811
    s = make(tmp_path)
    s.upstream.reply = Replay(cases.recording("alpha", "code"))
    url = s.start()
    try:
        open_analysis(s)
        (d1,) = wait_deliveries(s, "pa1", 1)
        digest = s.graph.state["problems"]["pa1"]["gongfa"]["digest"]
        spent = s.graph.state["problems"]["pa1"]
        events, budget, answer = tici.fetch(url, "pa1")
        prices = yaml.safe_load(tici.PRICES.read_text(encoding="utf-8"))
        a = tici.from_export(
            s.cfg.home / "analyses" / "pa1", events, budget, answer, arm="B", question="q1", rep=1, prices=prices
        )
    finally:
        s.stop()
    assert spent is not None and d1["outcome"] == "partial"
    assert answer and "候选" in answer  # 交付的报告原文，经 Blob 取回
    # 这道题没有点名问题：交付的只有候选评估，没有回答。运行正常结束，交给盲判的文本是空的（不是把评估当回答）
    assert a.status == "finished" and a.answer is None and a.own["undelivered_items"] == 0
    assert a.models_seen == ["claude-sonnet-5-5"] and a.gongfa == digest and a.settings
    assert a.usage["calls"] == len(s.upstream.reply.requests) > 0 and a.usage["output"] > 0
    assert a.cap_usd_milli == 20_000 and a.booked_usd_milli == budget["spent"]["usd_milli"] > 0
    # 逐次调用向上取整的账面数不小于合计后再取整的折算数，相差不到调用次数个毫美元
    assert 0 < a.cost_usd_milli <= a.booked_usd_milli <= a.cost_usd_milli + a.usage["calls"]
    assert a.elapsed_s is not None and a.price_table == prices["version"]
    assert a.own["route"] == "general" and a.own["timeline_stop"] is None  # 这道题没有点名问题：不是按题读
    tici.save(tmp_path / "batch", a)
    assert tici.load_all(tmp_path / "batch")[0].answer is None


def test_the_engine_arms_blind_text_is_the_answer_alone_on_a_real_run(tmp_path):
    """引擎按题读真跑一次（模型由脚本扮演），拿它真的导出与真的交付报告做转换：交给盲判的文本里只有回答本身。

    不出现读法说明与引擎自己拆的子问，不出现核对标注，不出现「没读到的」「核对记录」两节，不出现预评估。"""
    conf = Config(
        run="p_q",
        source_label=engine_cases.LABELS["delta"],
        date=engine_cases.DATE,
        bang=engine_cases.bang(),
        canaries=engine_cases.CANARIES,
        parallel=4,
    )
    eng = Engine(tmp_path / "ws", QScript(), {"a_1": engine_cases.HERE / "delta" / "code"}, conf)
    intake = engine_cases.intake("delta", "code", "dry_run")
    intake["statement"] = STATEMENT
    delivered = eng.start(intake).answer

    # 交付的报告里确实有这些过程产物（不然下面的「不出现」什么也没证明）
    head, _, assessment = delivered.partition("\n---\n")
    own_subquestions = [q["text"] for q in wenti.questions(STATEMENT)]
    marks = [f"〔{zh}" for zh in dati.LABEL_ZH.values()]
    assert delivered.startswith("> 读法：") and all(q in head for q in own_subquestions)
    assert any(m in head for m in marks) and "## 没读到的" in head and "## 核对记录" in head and assessment.strip()

    text, skipped = tici.answer_only(eng.ws, delivered)
    assert text and skipped == 0 and "出处：" in text
    for banned in (
        "读法",
        "〔",
        "〕",
        "# 回答",
        "## ",
        "没读到的",
        "核对记录",
        "核对不支持",
        "原文只支持一部分",
        "---",
    ):
        assert banned not in text, banned
    for q in own_subquestions:
        assert q not in text, q
    section = lambda title: head.partition(f"## {title}")[2].partition("\n## ")[0]  # noqa: E731
    for part in (delivered.splitlines()[0], section("没读到的"), section("核对记录"), assessment):
        for line in part.splitlines():
            line = line.strip().lstrip("-#> ").strip()
            assert len(line) < 6 or line not in text, line

    run = tici.read_json(eng.ws / "run.json")
    answer = tici._artifact(eng.ws, run, "ql:answer")
    for it in answer["items"]:  # 每条结论的原文都在，逐字，也都在交付的报告里
        assert it["text"] in text and it["text"] in delivered
    # 引擎的结论文字对得上新文本：汇总里「标为已核对而被抽样否定」靠这个对
    marked = [it["text"] for it in tici._own(eng.ws)["engine_items"] if it["verdict"] == "supported"]
    assert marked and all(m in text for m in marked)
