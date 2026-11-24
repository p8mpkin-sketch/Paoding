"""trial-b-3 读数暴露的三处：截断要认出来并如实交回、放弃时记对原因并逐次留档、给人看的栏里的内部名词提交前就拦。

红线不变：内核与全部验证器零改动；这里只动提议侧与重试侧。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "engine_fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cases  # noqa: E402
from test_engine_kernel import ByKey, Host, brief_for  # noqa: E402
from test_engine_phase2 import _cand, _essence, _organ  # noqa: E402

from paoding_fenjue.engine import dan, kernel, pills, ruwei  # noqa: E402
from paoding_fenjue.engine.dan import Memo, Reply, truncated  # noqa: E402

PLACE_CAP = pills.MAX_TOKENS["ruwei/place/v1"]
GOOD = {
    "atoms": [{"atom": "report.claim_link", "params": {"show": "x"}, "emergent": True}],
    "fire": {"id": "h7.demo-y", "params": {}, "organ": _organ()},
}
BAD = {"atoms": [{"atom": "report.magic"}], "fire": {"id": "h7.demo-y", "params": {}, "organ": _organ()}}
CUT = Reply(None, 100, PLACE_CAP, "max_tokens")


class Scripted:
    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def call(self, role, key, payload):
        self.seen.append((key, dict(payload)))
        r = self.replies.pop(0)
        return r if isinstance(r, Reply) else Reply(r, 10, 5)


def test_truncation_is_told_apart_from_a_reply_that_is_not_json():
    assert truncated(Reply(None, 1, 5, "max_tokens"), 12000)
    assert truncated(Reply(None, 1, 12000), 12000)  # 端点不报停止原因：用满上限也算
    assert not truncated(Reply(None, 1, 300, "end_turn"), 12000)


def test_the_stop_reason_survives_the_call_memo(tmp_path):
    class Inner:
        def call(self, role, key, payload):
            return Reply(None, 1, 7, "max_tokens")

    m = Memo(Inner(), tmp_path / "calls.jsonl")
    assert m.call("placer", "k", {"a": 1}).stop == "max_tokens"
    assert Memo(Inner(), tmp_path / "calls.jsonl").call("placer", "k", {"a": 1}).stop == "max_tokens"  # 回放也带着


def test_a_cut_off_reply_gets_an_honest_error_not_the_empty_proposal_symptoms():
    d = Scripted(CUT, GOOD)
    res = ruwei.place(d, _cand(), _essence(), full=False)
    (err,) = d.seen[1][1]["errors"]
    assert "截断" in err and "思考" in err and str(PLACE_CAP) in err
    for wrong in ("压短", "整份重写", "length_limits"):  # 截断的原因是思考占了上限，不是字段长，不能叫模型缩短
        assert wrong not in err
    assert "不用缩短" in err
    for symptom in ("没有拆出任何决策原子", "要写席位", "要以 h7. 开头"):
        assert symptom not in err
    assert res.problems == [] and [a["kind"] for a in res.attempts] == ["truncated", "ok"]
    rules = d.seen[0][1]["rules"]
    assert "length_limits" not in rules and "思考" in rules["output_note"]


def test_the_output_limits_leave_room_for_thinking():
    m = pills.MAX_TOKENS
    assert m["ruwei/place/v1"] == m["shihuo/v1"] == 24_000
    assert m["reader/v1"] == m["cuiyi/blind/v1"] == 8_000
    assert m["cuiyi/main/v1"] == m["cuiyi/extra/v1"] == m["ruwei/design/v1"] == 16_000


def test_a_refusal_is_its_own_kind_and_is_not_retried():
    d = Scripted(Reply(None, 10, 3, "refusal"), GOOD)
    res = ruwei.place(d, _cand(), _essence(), full=False)
    assert len(d.seen) == 1  # 不再重试同一个请求
    assert [a["kind"] for a in res.attempts] == ["refused"]
    (p,) = res.problems
    assert "模型拒绝了这次请求" in p and "截断" not in p and "JSON" not in p


def test_a_refused_design_stops_too_and_keeps_the_skeleton():
    d = Scripted(GOOD, Reply(None, 10, 3, "refusal"))
    res = ruwei.place(d, _cand(), _essence(emergent=False), full=True)
    assert len(d.seen) == 2 and [a["kind"] for a in res.attempts] == ["ok", "refused"]
    assert res.problems and "模型拒绝了这次请求" in res.problems[0]


def test_the_attempt_after_a_cut_also_carries_the_earlier_validation_problems():
    d = Scripted(BAD, CUT, GOOD)
    ruwei.place(d, _cand(), _essence(), full=False)
    errs = d.seen[2][1]["errors"]
    assert len(errs) >= 2 and "没有这个决策原子：report.magic" in errs[0] and "截断" in errs[-1]
    d = Scripted(BAD, Reply(None, 10, 300, "end_turn"), GOOD)  # 解析不出同理
    ruwei.place(d, _cand(), _essence(), full=False)
    assert "report.magic" in d.seen[2][1]["errors"][0] and "解析不出" in d.seen[2][1]["errors"][-1]


def test_the_design_attempt_after_a_cut_also_carries_the_earlier_problems():
    cap = pills.MAX_TOKENS["ruwei/design/v1"]
    bad_design = {"arms": {}, "readings": [], "steps": []}
    d = Scripted(GOOD, bad_design, Reply(None, 1, cap, "max_tokens"), bad_design)
    ruwei.place(d, _cand(), _essence(emergent=False), full=True)
    errs = d.seen[3][1]["errors"]
    assert len(errs) >= 2 and "截断" in errs[-1] and not any("截断" in e for e in errs[:-1])


def test_not_json_is_its_own_error():
    d = Scripted(Reply(None, 10, 300, "end_turn"), GOOD)
    ruwei.place(d, _cand(), _essence(), full=False)
    (err,) = d.seen[1][1]["errors"]
    assert "解析不出 JSON 对象" in err and "截断" not in err


def test_giving_up_records_the_last_attempt_with_content_and_the_cut_separately():
    d = Scripted(BAD, BAD, CUT)
    res = ruwei.place(d, _cand(), _essence(), full=False)
    assert res.problems and "没有这个决策原子：report.magic" in res.problems[0]  # 最后一次有内容的问题，不是截断的症状
    assert [(a["attempt"], a["kind"]) for a in res.attempts] == [(1, "content"), (2, "content"), (3, "truncated")]
    assert res.attempts[0]["problems"] and "截断" in res.attempts[2]["problems"][0]
    assert res.attempts[2]["tokens_out"] == PLACE_CAP and all(a["step"] == "place" for a in res.attempts)


def test_three_cut_replies_report_the_cut_not_an_empty_proposal():
    res = ruwei.place(Scripted(CUT, CUT, CUT), _cand(), _essence(), full=False)
    assert len(res.problems) == 1 and "截断" in res.problems[0] and "没有拆出" not in res.problems[0]
    assert [a["kind"] for a in res.attempts] == ["truncated"] * 3


def test_a_cut_design_reply_is_handled_the_same_way():
    design = {
        "arms": {"B": "b", "A1": "a", "F": "f", "B1": "b1"},
        "readings": [{"dim": "完成率", "kind": "共有", "dir": "up", "gate": "不低于", "run": "跑"}],
        "steps": [{"do": "改", "slot": "H7", "where": ["web/src/"], "tests": ["t"], "kernel_lines": 0, "accept": "过"}],
    }
    cap = pills.MAX_TOKENS["ruwei/design/v1"]
    d = Scripted(GOOD, Reply(None, 1, cap, "max_tokens"), design)
    res = ruwei.place(d, _cand(), _essence(emergent=False), full=True)
    assert "截断" in d.seen[2][1]["errors"][0]
    assert [(a["step"], a["kind"]) for a in res.attempts] == [
        ("place", "ok"),
        ("design", "truncated"),
        ("design", "ok"),
    ][:3] or [a["kind"] for a in res.attempts][1] == "truncated"


def test_internal_terms_in_the_text_for_people_are_caught_before_submitting():
    bad = {**GOOD, "plain_summary": "新部件顶替旧的，并重新定阶"}
    d = Scripted(bad, GOOD)
    res = ruwei.place(d, _cand(), _essence(), full=False)
    (err,) = d.seen[1][1]["errors"]
    assert "给人看的文字里有内部名词 定阶" in err and res.problems == []


def test_the_attempt_log_lands_in_the_engine_file_of_a_whole_run(tmp_path):
    rec = cases.recording("delta", "code", ".dry")
    entries = ByKey(rec)
    # 录好的是“第 1 次违规、第 2 次改对”：前面再插一次截断，整体顺延
    first, fixed = (copy.deepcopy(entries.e[f"ruwei:C1:r1:place:{i}"]) for i in (1, 2))
    entries.e["ruwei:C1:r1:place:3"], entries.e["ruwei:C1:r1:place:2"] = fixed, first
    entries.e["ruwei:C1:r1:place:1"] = {**first, "output": None, "tokens_out": PLACE_CAP}
    brief = brief_for(tmp_path, fx="delta", intake=cases.intake("delta", "code", "dry_run"))
    out = kernel.Session(tmp_path, brief, entries, Host(brief)).run()
    assert out.status == "delivered"
    x = json.loads((tmp_path / "analysis" / "engine.json").read_text(encoding="utf-8"))
    log = x["placement_attempts"]["C1"]
    assert [a["kind"] for a in log] == ["truncated", "content", "ok"] and x["placement_problems"]["C1"] == []
    assert log[1]["problems"] and log[2]["problems"] == []


def test_a_vocabulary_hit_in_the_essence_is_sent_back_even_in_a_dry_run(tmp_path):
    rec = cases.recording("delta", "code", ".dry")
    entries = ByKey(rec)
    seen = []
    orig = entries.call

    def spy(role, key, payload):
        seen.append((key, dict(payload)))
        return orig(role, key, payload)

    entries.call = spy
    first = copy.deepcopy(entries.e["cuiyi:C2:r1:main:1"])
    first["output"]["masked"]["statement"] += "（需要先定阶）"
    entries.e["cuiyi:C2:r1:main:2"] = copy.deepcopy(entries.e["cuiyi:C2:r1:main:1"])
    entries.e["cuiyi:C2:r1:main:1"] = first
    brief = brief_for(tmp_path, fx="delta", intake=cases.intake("delta", "code", "dry_run"))
    kernel.Session(tmp_path, brief, entries, Host(brief)).run()
    retry = dict(seen)["cuiyi:C2:r1:main:2"]
    assert any("V5" in e and "定阶" in e for e in retry["errors"])
