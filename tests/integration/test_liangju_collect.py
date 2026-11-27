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

from liangju import tici  # noqa: E402


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
    assert a.status == "finished" and a.answer and "候选" in a.answer  # 交付的报告原文，经 Blob 取回
    assert a.models_seen == ["claude-sonnet-5-5"] and a.gongfa == digest and a.settings
    assert a.usage["calls"] == len(s.upstream.reply.requests) > 0 and a.usage["output"] > 0
    assert a.cap_usd_milli == 20_000 and a.booked_usd_milli == budget["spent"]["usd_milli"] > 0
    # 逐次调用向上取整的账面数不小于合计后再取整的折算数，相差不到调用次数个毫美元
    assert 0 < a.cost_usd_milli <= a.booked_usd_milli <= a.cost_usd_milli + a.usage["calls"]
    assert a.elapsed_s is not None and a.price_table == prices["version"]
    assert a.own["route"] == "general" and a.own["timeline_stop"] is None  # 这道题没有点名问题：不是按题读
    tici.save(tmp_path / "batch", a)
    assert tici.load_all(tmp_path / "batch")[0].answer == a.answer
